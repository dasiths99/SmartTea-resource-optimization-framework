"""Internal ML service (FastAPI). Stateless: Spring Boot sends the block, its readings and the forecast; this returns
the recommendation JSON. It never touches MongoDB.

    Tier 1  saved yield (CatBoost) + runoff (XGBoost) models        artifacts/models/
    Tier 2  NSGA-II optimizer: N dose, product, irrigation           src/optimizer/optimize.py
    Tier 3  Action Window: best hour in the next 96 h + rule actions src/scheduler/action_window.py

Run (from the project root):
    uvicorn src.api.main:app --port 8000
"""
import copy
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.api.explain import explain, soil_n_levels
from src.api.live import BlockStore, build_context, hourly
from src.optimizer.optimize import SETTINGS, Surrogates, recommend
from src.scheduler.action_window import load_rules, schedule

app = FastAPI(title="SmartTea-LK C04 ML service", version="0.1")
STATE = {}


@app.on_event("startup")
def load():
    STATE["store"] = BlockStore()
    STATE["sur"] = Surrogates()
    STATE["rules"] = load_rules()
    STATE["n_levels"] = soil_n_levels(STATE["store"])


class FertilizerEvent(BaseModel):
    date: str
    product_code: str
    amount_kg_per_ha: float


class ActionRecord(BaseModel):
    type: str                                 # fertilizer | irrigation | dolomite | fungicide (marked as done by the user)
    date: str                                 # YYYY-MM-DD
    amount: Optional[float] = None
    unit: Optional[str] = None
    product: Optional[str] = None


class RecommendRequest(BaseModel):
    block_id: str
    readings: list[dict]                      # IoT-compatible readings, any order (the latest is used for "now")
    forecast: dict                            # raw Open-Meteo forecast JSON (hourly + daily, past_days >= 7)
    fertilizer_history: list[FertilizerEvent] = []
    action_history: list[ActionRecord] = []   # actions the user marked as done (all types)
    now: Optional[str] = None                 # decision time (default: current local time)
    min_ae: Optional[float] = None            # override the pick-rule threshold (kg leaf per kg N)
    what_if: Optional[str] = None             # demo only: "dry" = no rain in the next days, "wet" = wet, cloudy past week


def apply_what_if(forecast, kind, now):
    """Clearly labelled demo scenarios on top of the real forecast (the result carries `what_if`)."""
    f = copy.deepcopy(forecast)
    hrs, days = f["hourly"], f["daily"]
    today = now.strftime("%Y-%m-%d")
    if kind == "dry":            # the next days dry and settled
        for i, t in enumerate(hrs["time"]):
            if t >= now.strftime("%Y-%m-%dT%H:%M"):
                hrs["precipitation"][i], hrs["precipitation_probability"][i] = 0.0, 5
        for i, t in enumerate(days["time"]):
            if t >= today:
                days["precipitation_sum"][i] = 0.0
    elif kind == "wet":          # the past 7 days wet and cloudy (blister-blight weather)
        past = [i for i, t in enumerate(days["time"]) if t < today][-7:]
        for i in past:
            days["precipitation_sum"][i] = 15.0
            days["shortwave_radiation_sum"][i] = 8.0
            days["relative_humidity_2m_mean"][i] = 95
    else:
        raise ValueError(f"unknown what_if '{kind}' (use 'dry' or 'wet')")
    return f


@app.get("/ml/health")
def health():
    sur = STATE["sur"]
    return {"status": "ok", "models": {t: {"model": m.get("model"), "scores": m.get("scores")} for t, m in sur.meta.items()},
            "settings": SETTINGS}


@app.get("/ml/blocks")
def blocks():
    return STATE["store"].block_list()


@app.get("/ml/estates")
def estates():
    return STATE["store"].estate_list()


@app.post("/ml/recommend")
def recommend_endpoint(req: RecommendRequest):
    store, sur = STATE["store"], STATE["sur"]
    try:
        forecast = req.forecast
        if req.what_if:
            forecast = apply_what_if(forecast, req.what_if, pd.Timestamp(req.now or datetime.now()).floor("h"))
        fert = [e.model_dump() for e in req.fertilizer_history]
        seen = {f["date"] for f in fert}
        for a in req.action_history:      # a fertilizer marked as done counts as a past application (45-day rule, N this year)
            if a.type == "fertilizer" and a.amount and a.date not in seen:
                fert.append(dict(date=a.date, product_code=a.product or "NPK_BAL", amount_kg_per_ha=a.amount))
        ctx, info = build_context(store, req.block_id, req.readings, forecast, fert, req.now)
        info["actions_done"] = [a.model_dump() for a in req.action_history]
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    if req.what_if:
        info["notes"].insert(0, "WHAT-IF DEMO: " + ("the forecast rain for the coming days was set to 0 (simulated dry weather)"
                                                    if req.what_if == "dry" else
                                                    "the past 7 days were set to wet and cloudy (simulated blight weather)"))
    settings = dict(SETTINGS, min_ae=req.min_ae) if req.min_ae else SETTINGS
    t2 = recommend(ctx, sur, store.lim, settings)   # Tier 1 + Tier 2
    actions, t3 = schedule(t2, ctx, info, hourly(forecast), sur, store.lim, STATE["rules"])   # Tier 3
    expl = explain(ctx, info, t2, actions, t3, STATE["rules"], settings, STATE["n_levels"])
    main = actions[0]
    return {
        # the recommendation in the framework's output format
        "block_id": req.block_id,
        "action": main["action"],
        "amount_kg_per_ha": main["amount"] if main.get("unit") == "kg/ha" else None,
        "window": main.get("window"),
        "reason": main["reason"],
        "predicted_yield_change_pct": t2.get("predicted_yield_change_pct"),
        "efficiency_score": main.get("efficiency_score"),
        # details for the dashboard
        "generated_at": str(info["now"]),
        "what_if": req.what_if,
        "actions": actions,
        "explanation": expl,
        "tier2": {k: v for k, v in t2.items() if k != "reason"} | {"reason": t2["reason"]},
        "tier3": t3,
        "inputs_used": {"sensor_7d_mean": {k: round(v, 2) for k, v in info["sensor_7d"].items()},
                        "round_days": ctx.round_days, "days_since_pruning": ctx.days_since_pruning,
                        "days_since_fertilizer": None if ctx.days_since_fert != ctx.days_since_fert else int(ctx.days_since_fert),
                        "n_this_year_kg_ha": round(float(ctx.n_this_year), 1),
                        "forecast_rain_next_24h_mm": round(float(ctx.runoff_row.fc_rain_next_24h_mm), 1),
                        "rain_prev_3d_mm": round(float(ctx.runoff_row.rain_prev_3d_mm), 1)},
        "warnings": info["notes"],
        "assumptions": info["assumptions"],
    }
