"""Live pipeline (ML service) tests: reading + forecast -> Tier 1/2/3 recommendation. Needs the saved models
(python -m src.models.compare_models; python -m src.optimizer.soil_n). Uses a synthetic forecast, no network."""
import os

import pandas as pd
import pytest

from src.api.live import BlockStore, build_context, hourly

pytestmark = pytest.mark.skipif(not os.path.exists("artifacts/models/yield_catboost.joblib"), reason="models not trained")
NOW = pd.Timestamp("2026-10-15 08:00")


def forecast(rain_mm_h=0.0, prob=10):
    hrs = pd.date_range(NOW.normalize() - pd.Timedelta(days=31), periods=36 * 24, freq="h")
    days = pd.date_range(NOW.normalize() - pd.Timedelta(days=31), periods=36, freq="D")
    fut = hrs >= NOW
    return {"hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in hrs],
                       "precipitation": [rain_mm_h if f else 0.2 for f in fut],
                       "precipitation_probability": [prob] * len(hrs), "temperature_2m": [22.0] * len(hrs),
                       "relative_humidity_2m": [80] * len(hrs), "wind_speed_10m": [2.0] * len(hrs)},
            "daily": {"time": [d.strftime("%Y-%m-%d") for d in days], "precipitation_sum": [4.0] * 36,
                      "temperature_2m_mean": [22.0] * 36, "relative_humidity_2m_mean": [80] * 36,
                      "et0_fao_evapotranspiration": [3.0] * 36, "sunshine_duration": [18000.0] * 36,
                      "shortwave_radiation_sum": [16.0] * 36}}


def reading(**kw):
    r = dict(timestamp="2026-10-15T08:00:00", soil_moisture_pct=32.0, soil_ph=5.1, soil_n_ppm=5.0, soil_p_ppm=20.0,
             soil_k_ppm=120.0, soil_temp_c=21.0, light_lux=42000.0, sunshine_hours=5.0)
    return r | kw


@pytest.fixture(scope="module")
def env():
    from src.optimizer.optimize import Surrogates
    return BlockStore(), Surrogates()


def run(env, fc, rd, hist):
    from src.optimizer.optimize import SETTINGS, recommend
    from src.scheduler.action_window import schedule
    store, sur = env
    ctx, info = build_context(store, "E03-B07", [rd], fc, hist, now=NOW)
    t2 = recommend(ctx, sur, store.lim, SETTINGS)
    return t2, schedule(t2, ctx, info, hourly(fc), sur, store.lim)


OLD = [{"date": "2026-07-01", "product_code": "NPK_BAL", "amount_kg_per_ha": 240}]


def test_dry_forecast_gives_window(env):
    t2, (actions, t3) = run(env, forecast(0.0), reading(), OLD)
    assert actions[0]["action"] == "Apply fertilizer"
    assert actions[0]["window"] and 6 <= pd.Timestamp(actions[0]["window_start"]).hour <= 12
    assert 100 <= actions[0]["amount"] <= 400


def test_wet_forecast_delays(env):
    _, (actions, _) = run(env, forecast(2.0, 90), reading(), OLD)
    assert actions[0]["action"] == "Delay fertilizer"


def test_recent_fertilizer_blocks_n(env):
    t2, _ = run(env, forecast(0.0), reading(), [{"date": "2026-10-01", "product_code": "UREA", "amount_kg_per_ha": 200}])
    assert t2["n_kg_per_ha"] == 0 and any("min 45" in n for n in t2["limits"])


def test_no_fertilizer_history(env):
    t2, (actions, _) = run(env, forecast(0.0), reading(), [])
    assert actions and t2["action"]


def run_block(env, block, fc, rd, hist):
    from src.optimizer.optimize import SETTINGS, recommend
    from src.scheduler.action_window import schedule
    store, sur = env
    ctx, info = build_context(store, block, [rd], fc, hist, now=NOW)
    return schedule(recommend(ctx, sur, store.lim, SETTINGS), ctx, info, hourly(fc), sur, store.lim)[0]


def test_dry_soil_irrigates_or_skips(env):
    names = lambda acts: [a["action"] for a in acts]
    # E05-B09 is irrigated; 24 % is below its trigger (31.4 %)
    assert "Irrigate" in names(run_block(env, "E05-B09", forecast(0.0), reading(soil_moisture_pct=24.0), OLD))
    assert "Skip irrigation" in names(run_block(env, "E05-B09", forecast(2.0, 90), reading(soil_moisture_pct=24.0), OLD))
    # E03-B07 has no irrigation: never irrigated
    assert not {"Irrigate", "Skip irrigation"} & set(names(run_block(env, "E03-B07", forecast(0.0), reading(soil_moisture_pct=24.0), OLD)))


def test_irrigation_follows_dataset_rule_and_reservoir(env):
    dry = reading(soil_moisture_pct=24.0)
    irr = lambda acts: next(a for a in acts if "rrigat" in a["action"])
    big = irr(run_block(env, "E05-B09", forecast(0.0), dry, OLD))     # 17.8 ha: the 3 million L reservoir covers 16 mm
    small = irr(run_block(env, "E01-B01", forecast(0.0), dry, OLD))   # 5.8 ha: full 25 mm event
    assert big["action"] == small["action"] == "Irrigate"
    assert small["amount"] == 25 and big["amount"] == 16
    assert big["water_needed_l"] <= 3_000_000 and "reservoir" in big["reason"]
    # the dataset's rule: rain coming (>= 5 mm in 2 days) -> skip
    assert irr(run_block(env, "E05-B09", forecast(0.3, 90), dry, OLD))["action"] == "Skip irrigation"


def test_explanation_and_day_plan(env):
    from src.api.main import RecommendRequest, load, recommend_endpoint
    load()
    r = recommend_endpoint(RecommendRequest(block_id="E03-B07", readings=[reading()], forecast=forecast(0.0),
                                            fertilizer_history=OLD, now=str(NOW)))
    e = r["explanation"]
    assert e["headline"] and {f["key"] for f in e["factors"]} >= {"soil_n", "soil_moisture", "ph", "rain"}
    assert len(e["yield_forecast"]["rounds"]) >= 1
    assert r["tier3"]["day_plan"] and all("fertilizer" in d for d in r["tier3"]["day_plan"])


def test_what_if_dry_removes_future_rain():
    from src.api.main import apply_what_if
    fc = forecast(2.0, 90)
    dry = apply_what_if(fc, "dry", NOW)
    fut = [i for i, t in enumerate(dry["hourly"]["time"]) if t >= NOW.strftime("%Y-%m-%dT%H:%M")]
    assert all(dry["hourly"]["precipitation"][i] == 0 for i in fut)
    assert fc["hourly"]["precipitation"][fut[0]] == 2.0          # the original forecast is not changed


def via_service(block, fc, rd, done, hist=OLD):
    """The full ML endpoint, with the actions the user marked as done."""
    from src.api.main import ActionRecord, RecommendRequest, load, recommend_endpoint
    load()
    ago = lambda d: str((NOW - pd.Timedelta(days=d)).date())
    return recommend_endpoint(RecommendRequest(
        block_id=block, readings=[rd], forecast=fc, fertilizer_history=hist, now=str(NOW),
        action_history=[ActionRecord(type=t, date=ago(d), amount=a, unit=u, product=pr) for t, d, a, u, pr in done]))


def action_names(r):
    return [a["action"] for a in r["actions"]]


def test_marked_dolomite_is_not_repeated_for_730_days(env):
    low_ph = reading(soil_ph=4.2)
    assert any(n.startswith("Apply dolomite") for n in action_names(via_service("E03-B07", forecast(0.0), low_ph, [])))
    r = via_service("E03-B07", forecast(0.0), low_ph, [("dolomite", 100, 1250, "kg/ha", None)])
    assert not any(n.startswith("Apply dolomite") for n in action_names(r))
    assert any("dolomite was applied 100 days ago" in x for x in r["tier3"]["suppressed"])
    r = via_service("E03-B07", forecast(0.0), low_ph, [("dolomite", 800, 1250, "kg/ha", None)])
    assert any(n.startswith("Apply dolomite") for n in action_names(r))


def test_marked_spray_gap_and_pre_harvest_reminder(env):
    from src.api.main import apply_what_if
    wet = apply_what_if(forecast(0.0), "wet", NOW)                      # blight weather; E03-B07 is above 600 m
    assert any(n.startswith("Spray fungicide") for n in action_names(via_service("E03-B07", wet, reading(), [])))
    r = via_service("E03-B07", wet, reading(), [("fungicide", 3, 1200, "ml/ha", None)])
    assert not any(n.startswith("Spray") for n in action_names(r))
    assert any("sprayed 3 days ago" in x for x in r["tier3"]["suppressed"])
    assert any("do not pluck before 2026-10-19" in x for x in r["tier3"]["reminders"])
    r = via_service("E03-B07", wet, reading(), [("fungicide", 10, 1200, "ml/ha", None)])
    assert any(n.startswith("Spray fungicide") for n in action_names(r)) and not r["tier3"]["reminders"]


def test_marked_irrigation_gap(env):
    dry = reading(soil_moisture_pct=24.0)
    assert "Irrigate" in action_names(via_service("E05-B09", forecast(0.0), dry, []))
    r = via_service("E05-B09", forecast(0.0), dry, [("irrigation", 1, 15, "mm", None)])
    assert "Irrigate" not in action_names(r) and any("Irrigation was done 1 day ago" in x for x in r["tier3"]["suppressed"])
    assert "Irrigate" in action_names(via_service("E05-B09", forecast(0.0), dry, [("irrigation", 5, 15, "mm", None)]))


def test_marked_fertilizer_counts_for_the_45_day_rule(env):
    r = via_service("E03-B07", forecast(0.0), reading(), [("fertilizer", 10, 240, "kg/ha", "NPK_BAL")])
    assert r["tier2"]["n_kg_per_ha"] == 0 and any("min 45" in n for n in r["tier2"]["limits"])


def test_low_ph_triggers_dolomite(env):
    _, (actions, _) = run(env, forecast(0.0), reading(soil_ph=4.2), OLD)
    assert any(a["action"].startswith("Apply dolomite") for a in actions)
