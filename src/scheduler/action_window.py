"""Tier 3: Action Window scheduler (first, rule-based version).

Scans the hourly Open-Meteo forecast (next 96 h, working hours 06-16) for the best time to carry out an action.
Rules come from 07_operational_constraints.csv:
  fertilizer: forecast rain in the next 12 h <= 5 mm, max rain probability in the next 12 h <= 30 %,
              soil moisture inside the band WP + 0.25..0.85 x (FC - WP); among the hours that pass, the one with the
              lowest runoff loss predicted by the Tier 1 runoff model (on FORECAST rain) is chosen.
  fungicide:  rain-free (<= 1 mm) for 4 h after spraying, wind <= 4 m/s.
  dolomite:   less than 20 mm forecast rain in the next 24 h.
  irrigation: the dataset's own rule (generate_hybrid.py), on irrigated blocks: soil moisture below the trigger and
              < 5 mm rain in 2 days -> Irrigate 6-25 mm (first working hour with no rain in the next 12 h);
              below the trigger but rain coming -> Skip irrigation.
  Blight risk uses sunshine derived from radiation (Angstrom), the same way as the training data.

Also here: the two rule-based actions the optimizer must NOT choose through the yield model
  - dolomite when the 7-day mean soil pH is below 4.45 (dolomite_trigger_ph)
  - fungicide when the blister-blight risk (wet, cloudy days at > 600 m) is above 0.35 (same rule as the data generator)
Gaps between repeats use what the user marked as done: dolomite 730 days, sprays 7 days (+ no plucking for 7 days
after a spray), irrigation 3 days; a fertilizer marked as done counts toward the 45-day rule (main.py).
The amounts for dolomite (1,250 kg/ha) and fungicide (1,200 ml/ha) are placeholders to be checked against TRI guidance.
"""
import numpy as np
import pandas as pd


HYBRID = "data/processed/hybrid"
WINDOW_HOURS = 4          # an application block shown to the user, e.g. 06:00-10:00
DOLOMITE_KG = 1250
FUNGICIDE_ML = 1200
ROOT_ZONE_MM = 400        # same root zone as the data generator
IRR_SKIP_RAIN_MM = 5      # irrigate only when under this much rain is forecast in 2 days (the dataset's rule)
IRR_MIN_MM = 6            # dataset: irrigation events are 6-25 mm
IRR_EFFICIENCY = 0.85     # share of the water reaching the root zone (the data generator's value)
IRR_MIN_GAP_DAYS = 3      # the dataset irrigates at most every 3 days
SPRAY_MIN_GAP_DAYS = 7    # the dataset sprays at most every 7 days
IRR_STEP_PTS = 3.2        # typical soil-moisture step of one event in the dataset (15 mm x 0.85 / 400 mm), in points


def load_rules(hybrid=HYBRID):
    c = pd.read_csv(f"{hybrid}/07_operational_constraints.csv")
    return {(r.constraint_name, r.applies_to): float(r.value) for r in c.itertuples()}


def candidate_hours(h, now, rules):
    horizon = rules[("action_window_forecast_horizon_hrs", "scheduler")]
    start, end = rules[("working_hours_start", "scheduler")], rules[("working_hours_end", "scheduler")]
    t = h.index[(h.index > now) & (h.index <= now + pd.Timedelta(hours=horizon))]
    return [x for x in t if start <= x.hour <= end - WINDOW_HOURS]


def ahead(h, t, hours, col="precipitation", how="sum"):
    s = h.loc[t:t + pd.Timedelta(hours=hours - 1), col]
    return float(s.sum() if how == "sum" else s.max())


def window_label(t):
    return f"{t:%Y-%m-%d %H:00}–{t + pd.Timedelta(hours=WINDOW_HOURS):%H:00}"


def soil_band(ctx, rules):
    aw = ctx.field_capacity - ctx.wilting_point
    return (ctx.wilting_point + rules[("soil_moisture_min_for_fertilizer", "fertilizer")] * aw,
            ctx.wilting_point + rules[("soil_moisture_max_for_fertilizer", "fertilizer")] * aw)


def fertilizer_window(h, now, ctx, sur, lim, product, kg, rules):
    """Every candidate hour with its checks and predicted runoff; the best passing hour (or None)."""
    lo, hi = soil_band(ctx, rules)
    sm_ok = lo <= ctx.soil_moisture <= hi
    cols = sur.features["runoff"]
    rows = []
    for t in candidate_hours(h, now, rules):
        r12, p12 = ahead(h, t, 12), ahead(h, t, 12, "precipitation_probability", "max") / 100
        x = ctx.runoff_row.copy()
        x["hour"] = t.hour
        x["fc_rain_next_12h_mm"], x["fc_rain_next_24h_mm"] = r12, ahead(h, t, 24)
        x["fc_rain_next_48h_mm"], x["fc_rain_next_72h_mm"] = ahead(h, t, 48), ahead(h, t, 72)
        x["amount_per_ha"], x["n_kg_per_ha"] = kg, kg * lim.n_frac[product]
        for q in lim.n_frac:
            x[f"product_code__{q}"] = float(q == product)
        rows.append(dict(time=t, rain_next_12h_mm=round(r12, 1), rain_prob_12h=round(p12, 2),
                         rain_next_24h_mm=round(x["fc_rain_next_24h_mm"], 1), X=x[cols].to_numpy(float),
                         rain_ok=r12 <= rules[("max_rain_next_12h_mm", "fertilizer")],
                         prob_ok=p12 <= rules[("max_rain_probability", "fertilizer")]))
    if not rows:
        return None, []
    loss = sur.runoff(np.vstack([r.pop("X") for r in rows]))
    for r, l in zip(rows, loss):
        r["runoff_loss_pct"] = round(float(l), 1)
        r["ok"] = bool(r["rain_ok"] and r["prob_ok"] and sm_ok)
    ok = [r for r in rows if r["ok"]]
    best = min(ok, key=lambda r: (r["runoff_loss_pct"], r["time"])) if ok else None
    return best, rows


def simple_window(h, now, rules, check):
    for t in candidate_hours(h, now, rules):
        if check(t):
            return t
    return None


def sunshine_hours(days):
    """Daily sunshine hours from solar radiation (Angstrom relation), exactly as the training data derives them
    (generate_hybrid.py). Open-Meteo's own sunshine_duration over-states sunshine on cloudy hill days."""
    doy = days.index.dayofyear.to_numpy()
    rad = days.shortwave_radiation_sum.to_numpy(float)
    return np.clip((rad / (34.5 + 2.0 * np.cos(2 * np.pi * (doy - 80) / 365)) - 0.25) / 0.5 * 12, 0, 11.5)


def irrigation_plan(h, now, ctx, lim, rules):
    """Daily irrigation rule (Tier 3). It follows the rule the dataset's historical irrigation records were made with
    (generate_hybrid.py; 611 events): an irrigated block, soil moisture below WP + trigger x (FC - WP), and less than
    5 mm rain in the next 2 days. Rain coming -> "Skip irrigation". Dose = what lifts the soil back above the trigger
    plus the dataset's typical step (~3 points of moisture), 6-25 mm per event, 85 % of the water reaching the root zone
    (400 mm). The dose never exceeds the estate reservoir (07_operational_constraints: 3,000,000 L; 1 mm on 1 ha = 10,000 L).
    The block's last irrigation date is not known live, so the dataset's 3-day minimum gap is not applied."""
    if not ctx.irrigation_available:
        return None
    aw = ctx.field_capacity - ctx.wilting_point
    trigger = ctx.wilting_point + lim.irr_trigger * aw
    if ctx.soil_moisture >= trigger:
        return None
    start = h.index[h.index > now]
    rain48 = ahead(h, start[0], 48) if len(start) else 0.0
    if rain48 >= IRR_SKIP_RAIN_MM:
        return dict(action="Skip irrigation", amount=0, unit="", window=None,
                    reason=f"Soil moisture {ctx.soil_moisture:.1f}% is below the trigger {trigger:.1f}%, but "
                           f"{rain48:.0f} mm rain is forecast in the next 48 h (the rule irrigates only when under "
                           f"{IRR_SKIP_RAIN_MM:g} mm is coming); rain will refill the soil")
    need = (trigger - ctx.soil_moisture + IRR_STEP_PTS) / 100 * ROOT_ZONE_MM / IRR_EFFICIENCY
    mm = float(np.clip(round(need), IRR_MIN_MM, lim.max_irr_event_mm))
    cap_mm = int(lim.water_l_month / (ctx.area_ha * 1e4))   # the reservoir limits one event
    note = ""
    if cap_mm < mm:
        mm, note = float(max(cap_mm, 0)), f"; limited by the estate reservoir ({lim.water_l_month / 1e6:.1f} million L)"
    if mm < IRR_MIN_MM:
        return dict(action="Irrigation needed: not enough water", amount=0, unit="", window=None,
                    reason=f"Soil moisture {ctx.soil_moisture:.1f}% is below the trigger {trigger:.1f}%, but the estate "
                           f"reservoir ({lim.water_l_month / 1e6:.1f} million L) covers under {IRR_MIN_MM:g} mm on "
                           f"{ctx.area_ha:g} ha")
    litres = mm * ctx.area_ha * 1e4
    t = simple_window(h, now, rules, lambda t: ahead(h, t, 12) < 1)
    return dict(action="Irrigate", amount=mm, unit="mm", window=window_label(t) if t is not None else None,
                water_needed_l=round(litres),
                reason=f"Dry soil: moisture {ctx.soil_moisture:.1f}% is below the trigger {trigger:.1f}% and only "
                       f"{rain48:.0f} mm rain is forecast in 48 h. Add {mm:g} mm ({litres / 1e6:.2f} million L for "
                       f"{ctx.area_ha:g} ha); about {IRR_EFFICIENCY * 100:.0f}% reaches the roots, lifting moisture to "
                       f"about {ctx.soil_moisture + mm * IRR_EFFICIENCY / ROOT_ZONE_MM * 100:.1f}%{note}")


def day_plan(h, now, ctx, rules, scan):
    """'Best time' planner: for each of the next forecast days, the best hour for each kind of field work, or why
    the day is not suitable. scan = the fertilizer scan (every working hour with its runoff prediction)."""
    by_day = {}
    for r in scan:
        by_day.setdefault(r["time"].normalize(), []).append(r)
    wind = rules[("max_wind_for_spray_ms", "fungicide")]
    rf = int(rules[("min_rainfree_time_hrs", "fungicide")])
    days = []
    for d in sorted({t.normalize() for t in candidate_hours(h, now, rules)}):
        hours = [t for t in candidate_hours(h, now, rules) if t.normalize() == d]
        day = h.loc[d:d + pd.Timedelta(hours=23)]
        out = dict(date=str(d.date()), rain_mm=round(float(day.precipitation.sum()), 1),
                   max_rain_prob=int(day.precipitation_probability.max()),
                   max_wind_ms=round(float(day.wind_speed_10m.max()), 1))
        f = by_day.get(d, [])
        ok = [r for r in f if r["ok"]]
        if ok:
            b = min(ok, key=lambda r: (r["runoff_loss_pct"], r["time"]))
            out["fertilizer"] = dict(ok=True, hour=f"{b['time']:%H:00}", runoff_loss_pct=b["runoff_loss_pct"],
                                     why=f"{b['rain_next_12h_mm']} mm rain in the 12 h after; {b['runoff_loss_pct']}% predicted loss")
        elif f:
            b = min(f, key=lambda r: r["rain_next_12h_mm"])
            out["fertilizer"] = dict(ok=False, hour=None, runoff_loss_pct=b["runoff_loss_pct"],
                                     why=("soil moisture outside the band" if b["rain_ok"] and b["prob_ok"] else
                                          f"at least {b['rain_next_12h_mm']} mm rain / {b['rain_prob_12h'] * 100:.0f}% chance in the 12 h after"))
        spray = [t for t in hours if ahead(h, t, rf) <= 1 and ahead(h, t, WINDOW_HOURS, "wind_speed_10m", "max") <= wind]
        out["spray"] = dict(ok=bool(spray), hour=f"{spray[0]:%H:00}" if spray else None,
                            why=f"{rf} h rain-free, wind ≤ {wind:g} m/s" if spray else f"rain within {rf} h or wind over {wind:g} m/s")
        dolo = [t for t in hours if ahead(h, t, 24) < 20]
        out["dolomite"] = dict(ok=bool(dolo), hour=f"{dolo[0]:%H:00}" if dolo else None,
                               why="under 20 mm rain in the next 24 h" if dolo else "20 mm or more rain in the next 24 h")
        irr = [t for t in hours if ahead(h, t, 12) < 1]
        out["irrigation"] = dict(ok=bool(irr), hour=f"{irr[0]:%H:00}" if irr else None,
                                 why="no rain in the 12 h after" if irr else "rain within 12 h would do the job")
        days.append(out)
    return days


def blight_risk(past, elevation_m):
    """Smoothed blister-blight risk over the past days (same formula as the data generator; 0 below 600 m)."""
    if elevation_m <= 600 or len(past) < 6:
        return 0.0
    rain = past.precipitation_sum.to_numpy(float)
    sun = sunshine_hours(past)
    rh = past.relative_humidity_2m_mean.to_numpy(float)
    s = 0.0
    for i in range(5, len(past)):
        wet5 = (rain[i - 5:i] > 1).sum() / 5
        risk = np.clip(wet5 * (1 - min(sun[i - 5:i].mean(), 6) / 6) * 1.7 * (0.8 + rh[i] / 500), 0, 1)
        s = 0.8 * s + 0.2 * risk
    return float(s)


def schedule(tier2, ctx, info, h, sur, lim, rules=None):
    """Turns the Tier 2 plan + the rule-based checks into a list of actions, each with a time window."""
    rules = rules or load_rules()
    now = info["now"]
    actions = []
    planned = tier2.get("n_kg_per_ha", 0) > 0
    # the planner always shows fertilizer timing: the planned dose, or a typical 240 kg/ha NPK when none is planned
    product, kg = (tier2["product"], tier2["amount_kg_per_ha"]) if planned else ("NPK_BAL", 240.0)
    best, scan = fertilizer_window(h, now, ctx, sur, lim, product, kg, rules)
    plan_days = day_plan(h, now, ctx, rules, scan)

    if planned:
        lo, hi = soil_band(ctx, rules)
        if best is not None:
            actions.append(dict(
                action="Apply fertilizer", product=tier2["product"], amount=tier2["amount_kg_per_ha"], unit="kg/ha",
                window=window_label(best["time"]), window_start=str(best["time"]),
                efficiency_score=round(1 - best["runoff_loss_pct"] / 100, 2),
                expected_runoff_loss_pct=best["runoff_loss_pct"],
                reason=(f"Soil moisture {ctx.soil_moisture:.1f}% in band {lo:.1f}–{hi:.1f}%; "
                        f"{best['rain_next_12h_mm']} mm rain forecast in the 12 h after; "
                        f"lowest predicted runoff ({best['runoff_loss_pct']}%) of the safe hours")))
        else:
            why = []
            if not lo <= ctx.soil_moisture <= hi:
                why.append(f"soil moisture {ctx.soil_moisture:.1f}% outside band {lo:.1f}–{hi:.1f}%")
            if scan and not any(r["rain_ok"] and r["prob_ok"] for r in scan):
                why.append("no working hour in the next 96 h with ≤5 mm rain and ≤30% rain probability in the 12 h after")
            actions.append(dict(action="Delay fertilizer", product=tier2["product"], amount=tier2["amount_kg_per_ha"],
                                unit="kg/ha", window=None, efficiency_score=None, blocked_by=why or ["no safe window"],
                                reason="Fertilizer is needed, but " + "; ".join(why or ["no safe window"]) +
                                       ". Re-checked every hour as the forecast changes."))

    # what the user marked as done (Mark as done): enforces the gaps between repeats of dolomite, sprays and irrigation
    today = now.normalize()
    done = info.get("actions_done") or []

    def since(kind):
        ds = [pd.Timestamp(a["date"]) for a in done if a["type"] == kind]
        return (today - max(ds).normalize()).days if ds else None

    suppressed, reminders = [], []
    ago = lambda d: "today" if d == 0 else "1 day ago" if d == 1 else f"{d} days ago"

    irr = irrigation_plan(h, now, ctx, lim, rules)   # a daily soil-moisture rule, not a yield-model choice
    if irr is not None:
        d_irr = since("irrigation")
        if irr["action"] == "Irrigate" and d_irr is not None and d_irr < IRR_MIN_GAP_DAYS:
            suppressed.append(f"Irrigation was done {ago(d_irr)} (at least {IRR_MIN_GAP_DAYS} days between irrigations)")
        else:
            actions.append(irr)

    ph = info.get("ph_mean")
    trig = rules[("dolomite_trigger_ph", "dolomite")]
    if ph is not None and ph < trig:
        gap = int(rules[("min_days_between_dolomite", "dolomite")])
        d_dol = since("dolomite")
        if d_dol is not None and d_dol < gap:
            suppressed.append(f"pH is low ({ph:.2f}), but dolomite was applied {ago(d_dol)} "
                              f"(at least {gap} days between applications; it acts slowly)")
        else:
            t = simple_window(h, now, rules, lambda t: ahead(h, t, 24) < 20)
            actions.append(dict(action="Apply dolomite (pH correction)", amount=DOLOMITE_KG, unit="kg/ha",
                                window=window_label(t) if t is not None else None,
                                reason=f"7-day mean soil pH {ph:.2f} below trigger {trig}; target 4.5–5.5"))

    blk_elev = float(ctx.runoff_row.elevation_m)
    risk = blight_risk(info["past"], blk_elev)
    if risk > 0.35:
        wind = rules[("max_wind_for_spray_ms", "fungicide")]
        rf = int(rules[("min_rainfree_time_hrs", "fungicide")])
        pre = int(rules[("pre_harvest_interval_days", "fungicide")])
        d_spray = since("fungicide")
        if d_spray is not None and d_spray < SPRAY_MIN_GAP_DAYS:
            suppressed.append(f"Blight risk is {risk:.2f}, but the block was sprayed {ago(d_spray)} "
                              f"(at least {SPRAY_MIN_GAP_DAYS} days between sprays)")
        else:
            t = simple_window(h, now, rules, lambda t: ahead(h, t, rf) <= 1 and ahead(h, t, WINDOW_HOURS, "wind_speed_10m", "max") <= wind)
            actions.append(dict(action="Spray fungicide (blister blight)", amount=FUNGICIDE_ML, unit="ml/ha",
                                window=window_label(t) if t is not None else None,
                                reason=f"Blister-blight risk {risk:.2f} (> 0.35) after wet, cloudy days; "
                                       f"window needs {rf} h rain-free and wind ≤ {wind:g} m/s. "
                                       f"Do not pluck for {pre} days after spraying (pre-harvest interval)"))
    d_spray = since("fungicide")      # a spray already done: no plucking until the pre-harvest interval has passed
    pre = int(rules[("pre_harvest_interval_days", "fungicide")])
    if d_spray is not None and d_spray < pre:
        until = (today + pd.Timedelta(days=pre - d_spray)).date()
        reminders.append(f"Sprayed {ago(d_spray)}: do not pluck before {until} (pre-harvest interval {pre} days)")

    if not actions:
        why = [tier2["reason"]]
        if ph is not None:
            why.append(f"7-day mean pH {ph:.2f} (dolomite only below {trig:g})")
        if blk_elev > 600:
            why.append(f"blister-blight risk {risk:.2f} (fungicide only above 0.35)")
        why += suppressed
        actions.append(dict(action="No action", amount=0, unit="", window=None, reason="; ".join(why)))
    scan_out = [dict(time=str(r["time"]), rain_next_12h_mm=r["rain_next_12h_mm"], rain_prob_12h=r["rain_prob_12h"],
                     runoff_loss_pct=r["runoff_loss_pct"], ok=r["ok"]) for r in scan]
    aw = ctx.field_capacity - ctx.wilting_point
    return actions, dict(blight_risk=round(risk, 2), ph_mean_7d=None if ph is None else round(ph, 2),
                         soil_moisture_band=[round(v, 1) for v in soil_band(ctx, rules)],
                         irrigation_trigger=round(ctx.wilting_point + lim.irr_trigger * aw, 1),
                         fertilizer_scan=scan_out, fertilizer_scan_dose=dict(product=product, kg_per_ha=kg, planned=planned),
                         day_plan=plan_days, suppressed=suppressed, reminders=reminders)
