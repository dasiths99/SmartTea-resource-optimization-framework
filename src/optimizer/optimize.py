"""Tier 2: NSGA-II optimizer for one block at the start of a plucking round.

Decisions (continuous):  N to apply now (kg N/ha; 0 = no fertilizer)  and  irrigation this round (mm).
Objectives:              maximise predicted yield over the look-ahead horizon  |  minimise N  |  minimise water.
Hard limits:             07_operational_constraints.csv intersected with the training ranges (limits.py):
                         min/max dose, min 45 days between applications, no fertilizer within 30 days of pruning,
                         annual N ceiling per zone, irrigation only on irrigated blocks below the soil-moisture trigger,
                         max 25 mm per event, estate water budget.
Not decided here:        fungicide (the yield model shows a confounded, negative effect; decided by a blight-risk rule)
                         and the exact hour (Tier 3 Action Window scans the hourly forecast).

How a plan is scored (all three Tier 1 models work together):
  1. Runoff model: % of the N lost under the decision-time forecast, for each product allowed at that dose; the product
     with the lowest loss is used.  N_eff = N x (1 - loss).
  2. Soil-N response (soil_n.py): N_eff raises the soil-N reading by alpha x N_eff x exp(-days / tau).
  3. Yield model: predicted yield of every plucking round in the horizon (default 90 days), with the raised soil N and
     the applied-N / days-since-fertilizer features. Rounds after the current one use the current round's conditions
     as a proxy (the future weather is unknown), so only the DIFFERENCE between plans is meaningful.

Picking one plan from the Pareto front (agronomic efficiency rule, no cost variables):
  score = horizon yield gain (kg green leaf/ha)  -  min_ae x N  -  min_water_return x irrigation mm
  The plan with the highest score wins; if no plan beats "no action" (score 0), the answer is "No action".
  min_ae = the extra green leaf each kg of N must at least produce. It is a decision-maker setting: see the
  sensitivity sweep in evaluate.py, and check it against TRI guidance.

Usage:
    python -m src.optimizer.optimize --block E03-B07 --date 2025-06-01     # recommendation for the next round
"""
import argparse
import json

import joblib
import numpy as np
import pandas as pd
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import Problem
from pymoo.optimize import minimize

from src.data.load import load_spec
from src.optimizer.context import History
from src.optimizer.limits import load_limits
from src.optimizer.soil_n import load_response

SETTINGS = dict(solver="nsga2",           # "nsga2", or "grid" = exhaustive search (same answers, used for sweeps)
                pop_size=40, n_gen=40, seed=0,
                horizon_days=90,          # how long one application is followed (the 90-day N window of the yield model)
                min_ae=3.5,               # kg green leaf per kg N the last kg N must add (decision-maker setting;
                                          # 3.5 keeps 2025 N near historical practice, see min_ae_sweep_2025.csv)
                min_water_return=2.0)     # kg green leaf/ha per mm irrigation (decision-maker setting)
MODELS = {"yield": "artifacts/models/yield_catboost", "runoff": "artifacts/models/runoff_xgboost"}


class Surrogates:
    """The saved Tier 1 models (feature order from their .json) and the soil-N response."""

    def __init__(self, models=MODELS):
        self.meta = {t: json.load(open(f"{p}.json")) for t, p in models.items()}
        self.model = {t: joblib.load(f"{p}.joblib") for t, p in models.items()}
        self.features = {t: m["features"] for t, m in self.meta.items()}
        self.alpha, self.tau = load_response()
        self.soil_n_max = load_spec()["yield"]["training_ranges"]["start_soil_n_ppm_7d"][1]

    def yield_(self, X):
        return self.model["yield"].predict(np.asarray(X, np.float32))

    def runoff(self, X):
        return np.clip(self.model["runoff"].predict(np.asarray(X, np.float32)), 0, 100)


def decision_bounds(ctx, lim, water_l=None):
    """Allowed range of each decision for this block today, with the reason for every limit that binds."""
    notes = []
    n_lo, n_hi = lim.n_bounds()
    if not np.isnan(ctx.days_since_fert) and ctx.days_since_fert < lim.min_gap_days:
        n_hi = 0.0; notes.append(f"last fertilizer {ctx.days_since_fert:.0f} days ago (min {lim.min_gap_days})")
    if ctx.days_since_pruning < lim.no_fert_after_pruning_days:
        n_hi = 0.0; notes.append(f"pruned {ctx.days_since_pruning} days ago (wait {lim.no_fert_after_pruning_days})")
    if n_hi > 0:
        caps = {"annual N ceiling": lim.annual_n[ctx.agro_zone] - ctx.n_this_year,
                "60-day N (training range)": lim.n60_max - ctx.n_prior_60d,
                "90-day N (training range)": lim.n90_max - ctx.n_prior_90d}
        name, cap = min(caps.items(), key=lambda kv: kv[1])
        if cap < n_hi:
            n_hi = max(cap, 0.0); notes.append(f"N capped at {n_hi:.0f} kg/ha by the {name}")
        if n_hi < n_lo:
            n_hi = 0.0; notes.append(f"remaining N allowance below the minimum dose ({n_lo:.0f} kg N/ha)")
    trigger = ctx.wilting_point + lim.irr_trigger * (ctx.field_capacity - ctx.wilting_point)
    irr_hi = 0.0
    if not ctx.irrigation_available:
        pass
    elif ctx.soil_moisture >= trigger:
        notes.append(f"soil moisture {ctx.soil_moisture:.1f}% above irrigation trigger {trigger:.1f}%")
    else:
        water = lim.water_l_month if water_l is None else water_l
        irr_hi = min(lim.max_irr_event_mm, lim.irr_round_max, water / (ctx.area_ha * 1e4))   # 1 mm on 1 ha = 10,000 L
        notes.append(f"soil moisture {ctx.soil_moisture:.1f}% below irrigation trigger {trigger:.1f}%")
    return dict(n_lo=n_lo, n_hi=n_hi, irr_hi=irr_hi, notes=notes)


def window_mean(age, start, tau):
    """Mean of exp(-t/tau) over the 7 days before a round that starts `start` days after the decision,
    for an application made `age` days before the decision (0 = applied at the decision; effect from day 1)."""
    t = np.asarray(age, float)[:, None] + np.arange(start - 7, start)[None, :]
    return np.where(t >= 1, np.exp(-np.maximum(t, 1) / tau), 0.0).mean(axis=1)


class Horizon:
    """Yield-model rows for the plucking rounds in the look-ahead horizon, for any candidate plan."""

    def __init__(self, ctx, sur, days):
        k = ctx.round_days
        self.J = max(1, int(np.ceil(days / k)))
        self.days = self.J * k
        cols = sur.features["yield"]
        self.base = ctx.yield_row[cols].to_numpy(float)
        self.i = {c: cols.index(c) for c in ["n_applied_60d_kg_ha", "n_applied_90d_kg_ha", "days_since_last_fertilizer",
                                             "irrigation_mm_in_round", "start_soil_n_ppm_7d"]}
        ends, starts = (np.arange(self.J) + 1) * k, np.arange(self.J) * k
        ev = ctx.prior_events if ctx.prior_events is not None else pd.DataFrame(columns=["date", "n_kg_per_ha", "n_eff"])
        age = (ctx.decision_date - pd.to_datetime(ev.date)).dt.days.to_numpy()
        n, ne = ev.n_kg_per_ha.to_numpy(float), ev.n_eff.to_numpy(float)
        self.p60 = np.array([n[age <= 60 - e].sum() for e in ends])        # earlier N still inside each round's window
        self.p90 = np.array([n[age <= 90 - e].sum() for e in ends])
        self.new60, self.new90 = (ends <= 60).astype(float), (ends <= 90).astype(float)
        self.dsf_none = (np.full(self.J, 365.0) if np.isnan(ctx.days_since_fert)
                         else np.minimum(365.0, ctx.days_since_fert + ends))
        self.dsf_new = ends.astype(float)
        soil_now = self.base[self.i["start_soil_n_ppm_7d"]]
        drift = np.array([(ne * (window_mean(age, s, sur.tau) - window_mean(age, 0, sur.tau))).sum() for s in starts])
        self.soil_base = soil_now + sur.alpha * drift                       # earlier applications keep fading
        self.new_w = sur.alpha * np.array([window_mean([0], s, sur.tau)[0] for s in starts])
        self.soil_max = sur.soil_n_max
        self.sur = sur

    def predict(self, n, n_eff, irr):
        """(candidates x rounds) predicted kg/ha/day."""
        P = len(n)
        X = np.tile(self.base, (P, self.J, 1))
        X[:, :, self.i["n_applied_60d_kg_ha"]] = self.p60 + n[:, None] * self.new60
        X[:, :, self.i["n_applied_90d_kg_ha"]] = self.p90 + n[:, None] * self.new90
        X[:, :, self.i["days_since_last_fertilizer"]] = np.where(n[:, None] > 0, self.dsf_new, self.dsf_none)
        X[:, :, self.i["irrigation_mm_in_round"]] = 0.0
        X[:, 0, self.i["irrigation_mm_in_round"]] = irr
        X[:, :, self.i["start_soil_n_ppm_7d"]] = np.clip(self.soil_base + n_eff[:, None] * self.new_w, 0, self.soil_max)
        return self.sur.yield_(X.reshape(P * self.J, -1)).reshape(P, self.J)


def runoff_plan(ctx, sur, lim, n):
    """For each candidate N: the product with the lowest predicted runoff, its dose (kg/ha, whole 5 kg) and loss %."""
    cols = sur.features["runoff"]
    prods = list(lim.n_frac)
    lo, hi = max(lim.min_app_kg, lim.amount_range[0]), min(lim.max_app_kg, lim.amount_range[1])
    base = ctx.runoff_row[cols].to_numpy(float)
    ia, inn = cols.index("amount_per_ha"), cols.index("n_kg_per_ha")
    loss = np.full((len(n), len(prods)), np.inf)
    kg = np.zeros((len(n), len(prods)))
    for j, p in enumerate(prods):
        kg[:, j] = np.floor(n / lim.n_frac[p] / 5) * 5
        ok = (n > 0) & (kg[:, j] >= lo) & (kg[:, j] <= hi)
        if ok.any():
            X = np.tile(base, (ok.sum(), 1))
            X[:, ia], X[:, inn] = kg[ok, j], kg[ok, j] * lim.n_frac[p]
            for q in prods:
                X[:, cols.index(f"product_code__{q}")] = float(q == p)
            loss[ok, j] = sur.runoff(X)
    best = np.argmin(loss, axis=1)
    rows = np.arange(len(n))
    has = np.isfinite(loss[rows, best])
    frac = np.array([lim.n_frac[prods[b]] for b in best])
    n_snap = np.where(has, kg[rows, best] * frac, 0.0)
    return dict(product=np.array([prods[b] if h else "" for b, h in zip(best, has)]), kg=np.where(has, kg[rows, best], 0.0),
                n=n_snap, loss=np.where(has, loss[rows, best], 0.0), by_product=loss)


class RoundProblem(Problem):
    def __init__(self, ctx, sur, lim, bounds, horizon):
        self.ctx, self.sur, self.lim, self.b, self.h = ctx, sur, lim, bounds, horizon
        self.names = [v for v, hi in (("n", bounds["n_hi"]), ("irr", bounds["irr_hi"])) if hi > 0]
        xu = [bounds["n_hi"] if v == "n" else bounds["irr_hi"] for v in self.names]
        super().__init__(n_var=len(xu), n_obj=1 + len(xu), xl=np.zeros(len(xu)), xu=np.array(xu))

    def plan(self, x):
        """Decode raw variables into real plans: doses below the minimum = none; dose snapped to the product."""
        x = np.atleast_2d(x)
        n = x[:, self.names.index("n")] if "n" in self.names else np.zeros(len(x))
        n = np.where(n < self.b["n_lo"], 0.0, n)
        irr = x[:, self.names.index("irr")] if "irr" in self.names else np.zeros(len(x))
        rp = runoff_plan(self.ctx, self.sur, self.lim, n)
        return rp["n"], irr, rp

    def _evaluate(self, x, out, *args, **kwargs):
        n, irr, rp = self.plan(x)
        y = self.h.predict(n, n * (1 - rp["loss"] / 100), irr).mean(axis=1)
        out["F"] = np.column_stack([-y] + [n if v == "n" else irr for v in self.names])


def initial_population(prob, size, rng):
    """Corners (no action, minimum dose, maximum) plus random points, so the front always contains 'no action'."""
    xu = prob.xu
    corners = [np.zeros_like(xu), xu.copy()]
    if "n" in prob.names:
        c = np.zeros_like(xu); c[prob.names.index("n")] = prob.b["n_lo"]; corners.append(c)
    return np.vstack(corners + [rng.uniform(0, xu) for _ in range(size - len(corners))])


def recommend(ctx, sur, lim, settings=SETTINGS, water_l=None, keep_front=False):
    b = decision_bounds(ctx, lim, water_l)
    h = Horizon(ctx, sur, settings["horizon_days"])
    zero = np.zeros(1)
    y0 = h.predict(zero, zero, zero)[0]                         # no action: per round in the horizon
    out = dict(block_id=ctx.block_id, decision_date=str(ctx.decision_date.date()), round_days=ctx.round_days,
               horizon_days=h.days, baseline_yield_kg_ha_day=round(float(y0[0]), 2), limits=b["notes"],
               n_max_allowed=round(b["n_hi"], 1), irrigation_max_allowed_mm=round(b["irr_hi"], 1))
    pick = dict(n=0.0, irr=0.0, gain=0.0, score=0.0)
    front = pd.DataFrame()
    if b["n_hi"] > 0 or b["irr_hi"] > 0:
        prob = RoundProblem(ctx, sur, lim, b, h)
        if settings["solver"] == "grid":                        # every 0.5 kg N x every 1 mm
            axes = [np.arange(0, hi + 1e-9, 0.5 if v == "n" else 1.0) for v, hi in zip(prob.names, prob.xu)]
            X = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, len(axes))
            F = prob.evaluate(X, return_values_of=["F"])
        else:
            res = minimize(prob, NSGA2(pop_size=settings["pop_size"], eliminate_duplicates=True,
                                       sampling=initial_population(prob, settings["pop_size"],
                                                                   np.random.default_rng(settings["seed"]))),
                           ("n_gen", settings["n_gen"]), seed=settings["seed"], verbose=False)
            X, F = res.opt.get("X"), res.opt.get("F")           # non-dominated plans
        n, irr, _ = prob.plan(X)
        front = pd.DataFrame({"n": n, "irr": irr, "horizon_yield": -F[:, 0]}).drop_duplicates()
        front["gain"] = (front.horizon_yield - y0.mean()) * h.days                 # kg green leaf/ha over the horizon
        front["score"] = front.gain - settings["min_ae"] * front.n - settings["min_water_return"] * front.irr
        best = front.sort_values(["score", "n"], ascending=[False, True]).iloc[0]
        if best.score > 0:
            pick = best.to_dict()
    n, irr = np.array([pick["n"]]), np.array([pick["irr"]])
    rp = runoff_plan(ctx, sur, lim, n)
    y = h.predict(rp["n"], rp["n"] * (1 - rp["loss"] / 100), irr)[0]
    action, reason = [], []
    if pick["n"] > 0:
        loss, nn = float(rp["loss"][0]), float(rp["n"][0])
        action.append("Apply fertilizer")
        out.update(product=str(rp["product"][0]), amount_kg_per_ha=float(rp["kg"][0]),
                   expected_runoff_loss_pct=round(loss, 1), n_lost_kg_ha=round(nn * loss / 100, 1),
                   efficiency_score=round(1 - loss / 100, 2),
                   runoff_by_product_pct={p: round(float(v), 1) for p, v in zip(lim.n_frac, rp["by_product"][0]) if np.isfinite(v)},
                   forecast_rain_next_24h_mm=round(float(ctx.runoff_row.fc_rain_next_24h_mm), 1),
                   agronomic_efficiency_kg_leaf_per_kg_n=round(pick["gain"] / nn, 1))
        reason.append(f"{nn:.0f} kg N/ha adds about {pick['gain']:.0f} kg green leaf/ha over {h.days} days "
                      f"({pick['gain'] / nn:.0f} kg per kg N; threshold {settings['min_ae']:.0f})")
    if pick["irr"] > 0:
        action.append("Irrigate")
        reason.append(f"{pick['irr']:.0f} mm irrigation")
    if not action:
        action = ["No action"]
        reason.append(f"no allowed plan adds at least {settings['min_ae']:.0f} kg green leaf per kg N"
                      if (b["n_hi"] or b["irr_hi"]) else "fertilizer and irrigation not allowed now")
    out.update(action=" + ".join(action), n_kg_per_ha=round(float(rp["n"][0]), 1), irrigation_mm=round(pick["irr"], 1),
               predicted_yield_kg_ha_day=round(float(y[0]), 2),
               predicted_yield_change_pct=round(100 * (y[0] - y0[0]) / y0[0], 1),
               horizon_gain_kg_ha=round(pick["gain"], 1),
               horizon_gain_pct=round(100 * (y.mean() - y0.mean()) / y0.mean(), 1),
               n_eff_kg_ha=round(float(rp["n"][0] * (1 - rp["loss"][0] / 100)), 1),
               reason="; ".join(reason + b["notes"]))
    if keep_front:
        out["pareto"] = front.round(2).to_dict("records")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--block", required=True)
    ap.add_argument("--date", required=True, help="first round starting on/after this date")
    a = ap.parse_args()
    hist, sur, lim = History(), Surrogates(), load_limits()
    r = hist.rounds[hist.rounds.block_id == a.block].copy()
    r["start"] = r.pluck_date - pd.to_timedelta(r.round_days, unit="D")
    row = r[r.start >= pd.Timestamp(a.date)].sort_values("start").iloc[0]
    ctx = hist.context(row, hist.fert[hist.fert.block_id == a.block])
    print(json.dumps(recommend(ctx, sur, lim), indent=2, default=float))


if __name__ == "__main__":
    main()
