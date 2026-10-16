"""Plain-language explanation of a recommendation: a headline, each factor rated good / warning / bad with the
number behind it, and the predicted yield over the horizon with and without the plan.

Everything here is computed from values the pipeline already produced (no new model); thresholds come from
07_operational_constraints.csv, and soil-N levels are compared with the 2021-2025 readings of the training data.
"""
import numpy as np

RUNOFF_HIGH_PCT = 23.9   # the high/low runoff-risk cut used in the thesis (median loss 2021-2023)


def _factor(key, label, value, status, text):
    return dict(key=key, label=label, value=value, status=status, text=text)


def soil_n_levels(store):
    n = store.rounds.start_soil_n_ppm_7d.to_numpy(float)
    return {q: float(np.percentile(n, q)) for q in (25, 50, 75)}


def explain(ctx, info, t2, actions, t3, rules, settings, n_levels):
    s = info["sensor_7d"]
    plan = t3["day_plan"]
    min_ae = settings["min_ae"]
    factors = []

    # 1. soil nitrogen and whether fertilizer pays
    n = s.get("soil_n_ppm")
    if n is not None:
        lvl = "low" if n < n_levels[25] else "below average" if n < n_levels[50] else "good"
        st = "bad" if lvl == "low" else "warn" if lvl == "below average" else "good"
        txt = (f"{n:.1f} ppm is {lvl} (2021–25 readings: median {n_levels[50]:.0f} ppm, lowest quarter "
               f"under {n_levels[25]:.0f} ppm). ")
        if t2.get("n_kg_per_ha", 0) > 0:
            txt += (f"Adding {t2['n_kg_per_ha']:.0f} kg N/ha is predicted to add "
                    f"{t2['agronomic_efficiency_kg_leaf_per_kg_n']:.1f} kg green leaf per kg N (needs at least {min_ae:g}).")
        elif t2.get("best_ae_kg_leaf_per_kg_n") is not None:
            txt += (f"The best allowed dose would add only {t2['best_ae_kg_leaf_per_kg_n']:.1f} kg leaf per kg N; "
                    f"at least {min_ae:g} is needed, so fertilizer is not worth it now.")
        elif t2.get("n_max_allowed", 0) == 0:
            txt += "Fertilizer is not allowed now by the rules (see below)."
        factors.append(_factor("soil_n", "Soil nitrogen", f"{n:.1f} ppm", st, txt))

    # 2. soil moisture: fertilizer band and irrigation trigger
    lo, hi = t3["soil_moisture_band"]
    trig = t3["irrigation_trigger"]
    sm = ctx.soil_moisture
    if sm < trig:
        st, txt = "bad", f"Dry: below the irrigation trigger {trig}%" + ("" if ctx.irrigation_available else " (this block has no irrigation)")
    elif sm < lo:
        st, txt = "warn", f"Too dry for fertilizer (band {lo}–{hi}%): N would volatilise"
    elif sm > hi:
        st, txt = "warn", f"Too wet for fertilizer (band {lo}–{hi}%): high runoff risk"
    else:
        st, txt = "good", f"Inside the fertilizer band {lo}–{hi}%"
    factors.append(_factor("soil_moisture", "Soil moisture", f"{sm:.1f} %", st, txt + "."))

    # 3. pH
    ph = t3.get("ph_mean_7d")
    if ph is not None:
        trig_ph = rules[("dolomite_trigger_ph", "dolomite")]
        st = "bad" if ph < trig_ph else "warn" if ph < 4.5 or ph > 5.5 else "good"
        txt = (f"7-day average. Dolomite is applied below {trig_ph:g}; the target range is 4.5–5.5. "
               + ("Below the trigger: correct the pH." if st == "bad" else "No correction needed."))
        factors.append(_factor("ph", "Soil pH", f"{ph:.2f}", st, txt))

    # 4. rain
    r24 = float(ctx.runoff_row.fc_rain_next_24h_mm)
    r4d = sum(d["rain_mm"] for d in plan)
    st = "bad" if r24 > 10 else "warn" if r24 > 5 else "good"
    factors.append(_factor("rain", "Rain forecast", f"{r24:.0f} mm next 24 h", st,
                           f"{r4d:.0f} mm over the next {len(plan)} days; {float(ctx.runoff_row.rain_prev_3d_mm):.0f} mm "
                           f"fell in the last 3 days. Fertilizer needs ≤ 5 mm and ≤ 30% chance in the 12 h after."))

    # 5. runoff risk at the best hour (runoff model on the forecast)
    scan = t3["fertilizer_scan"]
    if scan:
        best = min(scan, key=lambda r: r["runoff_loss_pct"])
        dose = t3["fertilizer_scan_dose"]
        st = "bad" if best["runoff_loss_pct"] > RUNOFF_HIGH_PCT + 10 else "warn" if best["runoff_loss_pct"] > RUNOFF_HIGH_PCT else "good"
        factors.append(_factor("runoff", "Fertilizer runoff risk", f"{best['runoff_loss_pct']:.0f} % at best",
                               st, f"Lowest predicted loss in the next 4 days is at {best['time'][5:16]} "
                                   f"({'the planned' if dose['planned'] else 'a typical'} {dose['kg_per_ha']:g} kg/ha {dose['product']}). "
                                   f"Above {RUNOFF_HIGH_PCT}% counts as high risk."))

    # 6. fertilizer rules
    gap = rules[("min_days_between_fertilizer", "all")]
    ds = ctx.days_since_fert
    ceiling = info["lim"].annual_n[ctx.agro_zone]
    if ds != ds:   # NaN: none on record
        st, val, txt = "warn", "none on record", "No fertilizer date entered: the block is treated as never fertilized."
    else:
        st = "bad" if ds < gap else "good"
        val = f"{ds:.0f} days ago"
        txt = (f"At least {gap:.0f} days are needed between applications" + (" — not yet allowed." if ds < gap else " — allowed."))
    txt += f" N applied this year: {ctx.n_this_year:.0f} of {ceiling:.0f} kg N/ha allowed."
    factors.append(_factor("fert_rules", "Last fertilizer", val, st, txt))

    # 7. blight
    if float(ctx.runoff_row.elevation_m) > 600:
        b = t3["blight_risk"]
        factors.append(_factor("blight", "Blister-blight risk", f"{b:.2f}", "bad" if b > 0.35 else "warn" if b > 0.2 else "good",
                               "From the last weeks' rain, cloud and humidity; fungicide is sprayed above 0.35."))

    # 8. irrigation water: the estate reservoir (dataset constraint), only for blocks with irrigation
    if ctx.irrigation_available:
        cap = info["lim"].water_l_month
        mm = cap / (ctx.area_ha * 1e4)
        factors.append(_factor("water", "Estate irrigation water", f"{cap / 1e6:.1f} million L reservoir",
                               "good" if mm >= 25 else "warn" if mm >= 5 else "bad",
                               f"Enough for {mm:.0f} mm on this {ctx.area_ha:g} ha block (one irrigation is up to 25 mm)."))

    # headline
    main = actions[0]
    a = main["action"]
    yc = t2.get("predicted_yield_change_pct", 0)
    if a == "Apply fertilizer":
        head = (f"Apply {main['amount']:g} kg/ha {main.get('product', '')} on {main['window']}. Predicted +{yc}% green leaf "
                f"next round (+{t2['horizon_gain_kg_ha']:.0f} kg/ha over {t2['horizon_days']} days), "
                f"with {main['expected_runoff_loss_pct']}% of the N lost at that time.")
    elif a == "Delay fertilizer":
        nxt = next((d for d in plan if d.get("fertilizer", {}).get("ok")), None)
        head = (f"Fertilizer would pay (predicted +{yc}% green leaf next round), but wait: "
                + "; ".join(main.get("blocked_by", [])) + ". "
                + (f"First safe time: {nxt['date']} {nxt['fertilizer']['hour']}." if nxt else
                   "No safe time in the next 4 days; re-checked every hour as the forecast changes."))
    elif a == "No action":
        why = []
        if t2.get("best_ae_kg_leaf_per_kg_n") is not None:
            why.append(f"fertilizer would add only {t2['best_ae_kg_leaf_per_kg_n']:.1f} kg green leaf per kg N "
                       f"(at least {min_ae:g} needed)")
        elif t2.get("n_max_allowed", 0) == 0:
            why.append("fertilizer is not allowed now (" + "; ".join(l for l in t2.get("limits", []) if "fertilizer" in l or "N " in l or "pruned" in l) + ")")
        if ph is not None:
            why.append(f"soil pH {ph:.2f} needs no correction")
        if sm >= trig or not ctx.irrigation_available:
            why.append("no irrigation needed" if sm >= trig else "soil is dry but the block has no irrigation")
        head = "No action needed now: " + "; ".join(why) + "."
    else:
        head = f"{a}: {main['reason']}"
    if t3.get("suppressed"):
        head += " Not repeated: " + "; ".join(t3["suppressed"]) + "."
    if len(actions) > 1:
        head += " Also: " + ", ".join(x["action"] + (f" ({x['window']})" if x.get("window") else "") for x in actions[1:]) + "."

    return dict(headline=head, factors=factors,
                yield_forecast=dict(rounds=t2.get("horizon_rounds", []), round_days=t2["round_days"],
                                    gain_kg_ha=t2.get("horizon_gain_kg_ha", 0), gain_pct=t2.get("horizon_gain_pct", 0)))
