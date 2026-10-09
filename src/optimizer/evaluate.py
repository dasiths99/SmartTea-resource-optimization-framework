"""Closed-loop test of the Tier 2 optimizer on 2025 (the test year), all 50 blocks.

Every 2025 plucking round is processed in date order. At each round start the optimizer sees the block's fertilizer
history, which includes its OWN earlier 2025 recommendations, and the estate's remaining monthly water. Its plan is
compared with what was actually done (historical practice in the hybrid data).

The soil-N reading before each round is made counterfactual: the effect of the actual 2025 applications is removed
and the effect of the optimizer's applications is added (soil-N response model, soil_n.py). Other round conditions
(weather, moisture, pruning) stay as observed.

Both yields are MODEL PREDICTIONS (the yield surrogate), so the difference is the model's view, not a field result.
Treat the yield comparison as indicative; the resource and rule-violation numbers are exact.

Usage:
    python -m src.optimizer.evaluate                     # default setting -> artifacts/reports/optimizer/
    python -m src.optimizer.evaluate --sweep 1,2,3,4,5   # min_ae sensitivity (exhaustive solver) -> min_ae_sweep_2025.csv
    python -m src.optimizer.evaluate --check-solver      # NSGA-II vs exhaustive search -> solver_check.csv
"""
import argparse
import os
import time

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.optimizer.context import History
from src.optimizer.limits import load_limits
from src.optimizer.optimize import SETTINGS, Surrogates, recommend, window_mean

OUT = "artifacts/reports/optimizer"
YEAR = 2025


def violations(ev, lim, zone, start, end):
    """Rule breaks among applications in [start, end): dose > max, gap < min (vs previous application), annual N."""
    e = ev.sort_values("date").reset_index(drop=True)
    gap = e.date.diff().dt.days
    w = (e.date >= start) & (e.date < end)
    yearly = e[w].groupby(e[w].date.dt.year).n_kg_per_ha.sum()
    return dict(dose_over_max=int((e[w].amount_per_ha > lim.max_app_kg).sum()),
                gap_under_min=int((w & (gap < lim.min_gap_days)).sum()),
                annual_n_over_ceiling=int((yearly > lim.annual_n[zone]).sum()))


def soil_n_effect(ev, when, sur):
    """Soil-N (7-day mean before `when`) added by the applications in ev (date, n_eff)."""
    if ev.empty:
        return 0.0
    age = (when - ev.date).dt.days.to_numpy()
    return float(sur.alpha * (ev.n_eff.to_numpy() * window_mean(age, 0, sur.tau)).sum())


def run(settings, hist, sur, lim, write=True):
    os.makedirs(OUT, exist_ok=True)
    r = hist.rounds[hist.rounds.year == YEAR].copy()
    r["decision_date"] = r.pluck_date - pd.to_timedelta(r.round_days, unit="D")
    r = r.sort_values(["decision_date", "block_id"])
    hist_rows = r.copy()
    first = r.groupby("block_id").decision_date.min()
    last = r.groupby("block_id").pluck_date.max()
    actual = {b: g for b, g in hist.fert.groupby("block_id")}
    events = {b: actual[b][actual[b].date < first[b]].copy() for b in first.index}   # history before 2025 decisions
    water_used = {}
    live = sur.features["yield"]
    rows, t0 = [], time.time()
    for i, (_, row) in enumerate(r.iterrows()):
        b, est = row.block_id, row.estate_id
        dd = row.decision_date
        a = actual[b]
        own = events[b][events[b].date >= first[b]]                       # optimizer's 2025 applications
        done = a[(a.date >= first[b]) & (a.date < dd)]                      # actual 2025 applications so far
        row = row.copy()
        row["start_soil_n_ppm_7d"] = float(np.clip(row.start_soil_n_ppm_7d + soil_n_effect(own, dd, sur)
                                                   - soil_n_effect(done, dd, sur), 0, sur.soil_n_max))
        ctx = hist.context(row, events[b])
        key = (est, ctx.decision_date.strftime("%Y-%m"))
        rec = recommend(ctx, sur, lim, settings=settings, water_l=lim.water_l_month - water_used.get(key, 0.0))
        if rec["n_kg_per_ha"] > 0:
            events[b] = pd.concat([events[b], pd.DataFrame([dict(
                block_id=b, date=ctx.decision_date, n_kg_per_ha=rec["n_kg_per_ha"], n_eff=rec["n_eff_kg_ha"],
                amount_per_ha=rec["amount_kg_per_ha"], product_code=rec["product"])])], ignore_index=True)
        water_used[key] = water_used.get(key, 0.0) + rec["irrigation_mm"] * ctx.area_ha * 1e4
        in_round = a[(a.date >= ctx.decision_date) & (a.date < row.pluck_date)]
        rows.append(dict(rec, estate_id=est, agro_zone=ctx.agro_zone, area_ha=ctx.area_ha,
                         limits="; ".join(rec["limits"]), runoff_by_product_pct=str(rec.get("runoff_by_product_pct", "")),
                         hist_n_kg_per_ha=in_round.n_kg_per_ha.sum(), hist_amount_kg_per_ha=in_round.amount_per_ha.sum(),
                         hist_irrigation_mm=row.irrigation_mm_in_round,
                         soil_n_counterfactual=row.start_soil_n_ppm_7d, hist_n_eff_kg_ha=in_round.n_eff.sum(),
                         hist_predicted_yield_kg_ha_day=float(sur.yield_(hist_rows.loc[row.name, live].to_numpy(float)[None])[0]),
                         actual_yield_kg_ha_day=row.green_leaf_kg_per_ha_per_day))
        if (i + 1) % 300 == 0:
            print(f"  {i + 1}/{len(r)} rounds  ({time.time() - t0:.0f} s)")
    rec = pd.DataFrame(rows)
    for c in ["product", "amount_kg_per_ha", "expected_runoff_loss_pct"]:     # absent when nothing was applied
        if c not in rec:
            rec[c] = np.nan

    # ---- per block-year totals, then by estate and overall ----
    rec["opt_yield_kg_ha"] = rec.predicted_yield_kg_ha_day * rec.round_days
    rec["hist_yield_kg_ha"] = rec.hist_predicted_yield_kg_ha_day * rec.round_days
    rec["opt_water_m3"] = rec.irrigation_mm * rec.area_ha * 10
    rec["hist_water_m3"] = rec.hist_irrigation_mm * rec.area_ha * 10
    blk = rec.groupby(["estate_id", "block_id", "agro_zone"]).agg(
        rounds=("round_days", "size"),
        opt_n=("n_kg_per_ha", "sum"), hist_n=("hist_n_kg_per_ha", "sum"),
        opt_n_eff=("n_eff_kg_ha", "sum"), hist_n_eff=("hist_n_eff_kg_ha", "sum"),
        opt_kg=("amount_kg_per_ha", "sum"), hist_kg=("hist_amount_kg_per_ha", "sum"),
        opt_apps=("n_kg_per_ha", lambda s: (s > 0).sum()),
        opt_irr_mm=("irrigation_mm", "sum"), hist_irr_mm=("hist_irrigation_mm", "sum"),
        opt_water_m3=("opt_water_m3", "sum"), hist_water_m3=("hist_water_m3", "sum"),
        opt_yield=("opt_yield_kg_ha", "sum"), hist_yield=("hist_yield_kg_ha", "sum")).reset_index()
    vio = []
    for _, x in blk.iterrows():
        a, o = actual[x.block_id], events[x.block_id]
        hv = violations(a, lim, x.agro_zone, first[x.block_id], last[x.block_id])
        ov = violations(o, lim, x.agro_zone, first[x.block_id], last[x.block_id])
        vio.append({**{f"hist_{k}": v for k, v in hv.items()}, **{f"opt_{k}": v for k, v in ov.items()},
                    "hist_apps": int(((a.date >= first[x.block_id]) & (a.date < last[x.block_id])).sum())})
    blk = pd.concat([blk, pd.DataFrame(vio)], axis=1)

    def summarise(g):
        return pd.Series({
            "blocks": len(g),
            "N kg/ha/yr (historical)": g.hist_n.mean(), "N kg/ha/yr (optimizer)": g.opt_n.mean(),
            "N change %": 100 * (g.opt_n.sum() / g.hist_n.sum() - 1),
            "N lost to runoff kg/ha/yr (historical)": (g.hist_n - g.hist_n_eff).mean(),
            "N lost to runoff kg/ha/yr (optimizer)": (g.opt_n - g.opt_n_eff).mean(),
            "fertilizer kg/ha/yr (historical)": g.hist_kg.mean(), "fertilizer kg/ha/yr (optimizer)": g.opt_kg.mean(),
            "applications/yr (historical)": g.hist_apps.mean(), "applications/yr (optimizer)": g.opt_apps.mean(),
            "irrigation water m3 (historical)": g.hist_water_m3.sum(), "irrigation water m3 (optimizer)": g.opt_water_m3.sum(),
            "predicted yield kg/ha (historical)": g.hist_yield.mean(), "predicted yield kg/ha (optimizer)": g.opt_yield.mean(),
            "predicted yield change %": 100 * (g.opt_yield.sum() / g.hist_yield.sum() - 1),
            "green leaf per kg N (historical)": g.hist_yield.sum() / g.hist_n.sum(),
            "green leaf per kg N (optimizer)": g.opt_yield.sum() / g.opt_n.sum() if g.opt_n.sum() > 0 else np.nan,
            "rule breaks (historical)": g.filter(like="hist_").filter(regex="over|under").sum().sum(),
            "rule breaks (optimizer)": g.filter(like="opt_").filter(regex="over|under").sum().sum()})
    summ = blk.groupby("estate_id").apply(summarise)
    summ.loc["ALL"] = summarise(blk)
    print(f"  done in {time.time() - t0:.0f} s; min_ae {settings['min_ae']}: "
          f"N {summ.loc['ALL', 'N change %']:+.1f}%, yield {summ.loc['ALL', 'predicted yield change %']:+.1f}%")
    if write:
        rec.to_csv(f"{OUT}/recommendations_{YEAR}.csv", index=False)
        blk.round(2).to_csv(f"{OUT}/block_totals_{YEAR}.csv", index=False)
        summ.round(2).to_csv(f"{OUT}/summary_{YEAR}.csv")
        pd.set_option("display.width", 250)
        print(summ.round(1).T.to_string())
        print("\nactions:", rec.action.value_counts().to_dict())
        print("model check, historical rounds: predicted vs actual yield R2 =",
              round(1 - ((rec.actual_yield_kg_ha_day - rec.hist_predicted_yield_kg_ha_day) ** 2).sum()
                    / ((rec.actual_yield_kg_ha_day - rec.actual_yield_kg_ha_day.mean()) ** 2).sum(), 3))
        pareto_figure(rec, r, actual, settings, hist, sur, lim)
    return summ


def pareto_figure(rec, r, actual, settings, hist, sur, lim):
    """Pareto front of one recommended application: horizon gain vs N, with the efficiency line of the pick rule."""
    fert = rec[rec.n_kg_per_ha > 0]
    if fert.empty:
        return
    ex = fert.iloc[len(fert) // 2]
    row = r[(r.block_id == ex.block_id) & (r.decision_date == pd.Timestamp(ex.decision_date))].iloc[0]
    full = recommend(hist.context(row, actual[ex.block_id]), sur, lim, settings=settings, keep_front=True)
    fr = pd.DataFrame(full["pareto"]).sort_values("n")
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.plot(fr.n, fr.gain, "o-", color="#2a78d6", ms=4, lw=1, label="Pareto front (NSGA-II)")
    xs = np.array([0, fr.n.max()])
    ax.plot(xs, settings["min_ae"] * xs, "--", color="#898781", lw=1,
            label=f"efficiency threshold ({settings['min_ae']:g} kg leaf per kg N)")
    ax.scatter([full["n_kg_per_ha"]], [full["horizon_gain_kg_ha"]], color="#e08a1e", s=90, zorder=4,
               label=f"chosen: {full['n_kg_per_ha']:.0f} kg N/ha")
    ax.set_xlabel("N applied now (kg N/ha)"); ax.set_ylabel(f"extra green leaf over {full['horizon_days']} days (kg/ha)")
    ax.set_title(f"{full['block_id']}, round starting {full['decision_date']}", loc="left", fontsize=10)
    ax.grid(alpha=0.3); ax.spines[["top", "right"]].set_visible(False); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(f"{OUT}/pareto_example.png", dpi=200); plt.close(fig)


def solver_check(hist, sur, lim, n_plans=40, values=(1.0, 3.0)):
    """Does NSGA-II find the best plan? Compare with the exhaustive grid on rounds where fertilizer is allowed."""
    from src.optimizer.optimize import decision_bounds
    rows = hist.rounds[hist.rounds.year == YEAR].sample(400, random_state=5)
    ctxs = [c for c in (hist.context(r, hist.fert[hist.fert.block_id == r.block_id]) for _, r in rows.iterrows())
            if decision_bounds(c, lim)["n_hi"] > 0][:n_plans]
    score = lambda rec, v: rec["horizon_gain_kg_ha"] - v * rec["n_kg_per_ha"]
    out = []
    for v in values:
        ref = [recommend(c, sur, lim, settings=dict(SETTINGS, solver="grid", min_ae=v)) for c in ctxs]
        for pop, gen in [(40, 40), (20, 20), (12, 10)]:
            t = time.time()
            got = [recommend(c, sur, lim, settings=dict(SETTINGS, pop_size=pop, n_gen=gen, min_ae=v)) for c in ctxs]
            best, reached = np.array([score(r, v) for r in ref]), np.array([score(g, v) for g in got])
            out.append(dict(min_ae=v, pop_size=pop, n_gen=gen, plans=len(ctxs),
                            seconds_per_plan=(time.time() - t) / len(ctxs),
                            score_reached_pct=100 * reached.sum() / best.sum(),
                            same_dose_pct=100 * np.mean([abs(g["n_kg_per_ha"] - r["n_kg_per_ha"]) < 3 for g, r in zip(got, ref)]),
                            worst_gap_kg_leaf=float(np.max(best - reached))))
    out = pd.DataFrame(out)
    out.round(2).to_csv(f"{OUT}/solver_check.csv", index=False)
    print(out.round(2).to_string(index=False))


def sweep_figure(path=f"{OUT}/min_ae_sweep_{YEAR}.csv"):
    """Year-level trade-off: N used vs predicted yield, one point per efficiency threshold."""
    d = pd.read_csv(path)
    fig, ax = plt.subplots(figsize=(6.4, 3.9))
    ax.axhline(0, color="#c3c2b7", lw=0.8); ax.axvline(0, color="#c3c2b7", lw=0.8)
    ax.plot(d["N change %"], d["predicted yield change %"], "o-", color="#2a78d6", ms=5, lw=1.2)
    for _, r in d.iterrows():
        ax.annotate(f"{r.min_ae:g}", (r["N change %"], r["predicted yield change %"]), textcoords="offset points",
                    xytext=(5, 4), fontsize=7.5, color="#52514e")
    dflt = d[d.min_ae == SETTINGS["min_ae"]]
    ax.scatter(dflt["N change %"], dflt["predicted yield change %"], s=110, color="#e08a1e", zorder=4,
               label=f"default threshold {SETTINGS['min_ae']:g}")
    ax.set_xlabel("N used vs historical practice (%)"); ax.set_ylabel("predicted yield vs historical (%)")
    ax.set_title(f"{YEAR}: each point = one efficiency threshold (kg leaf per kg N)", loc="left", fontsize=10)
    ax.grid(alpha=0.3); ax.spines[["top", "right"]].set_visible(False); ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout(); fig.savefig(f"{OUT}/min_ae_sweep_{YEAR}.png", dpi=200); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sweep", help="comma-separated min_ae values (kg green leaf per kg N)")
    ap.add_argument("--check-solver", action="store_true")
    a = ap.parse_args()
    hist, sur, lim = History(), Surrogates(), load_limits()
    os.makedirs(OUT, exist_ok=True)
    if a.check_solver:
        solver_check(hist, sur, lim)
        return
    if not a.sweep:
        run(SETTINGS, hist, sur, lim)
        print(f"written {OUT}/ (settings {SETTINGS})")
        return
    rows = []
    for v in [float(x) for x in a.sweep.split(",")]:
        s = run(dict(SETTINGS, min_ae=v, solver="grid"), hist, sur, lim, write=False).loc["ALL"]
        rows.append(dict(min_ae=v, **s.to_dict()))
    out = pd.DataFrame(rows)
    out.round(2).to_csv(f"{OUT}/min_ae_sweep_{YEAR}.csv", index=False)
    sweep_figure()
    pd.set_option("display.width", 250)
    print(out.set_index("min_ae").round(1).T.to_string())


if __name__ == "__main__":
    main()
