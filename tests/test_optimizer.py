"""Tier 2 optimizer: the hard rules must never be broken.   Run: python -m pytest tests -q"""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.optimizer.context import History
from src.optimizer.limits import load_limits
from src.optimizer.optimize import SETTINGS, Surrogates, decision_bounds, recommend, window_mean


@pytest.fixture(scope="module")
def env():
    hist, sur, lim = History(), Surrogates(), load_limits()
    rows = hist.rounds[hist.rounds.year == 2025].sample(12, random_state=1)
    ctxs = [hist.context(r, hist.fert[hist.fert.block_id == r.block_id]) for _, r in rows.iterrows()]
    return hist, sur, lim, ctxs


def test_limits_match_constraints_table(env):
    _, _, lim, _ = env
    assert (lim.min_app_kg, lim.max_app_kg, lim.min_gap_days) == (100, 400, 45)
    assert lim.annual_n == {"up": 330, "mid": 300, "low": 300}
    assert lim.n_frac == {"NPK_BAL": 0.21, "NPK_HN": 0.27, "UREA": 0.46}


def test_every_n_in_bounds_has_a_valid_product(env):
    _, _, lim, _ = env
    lo, hi = lim.n_bounds()
    for n in np.linspace(lo, hi, 50):
        opts = lim.products_for(n)
        assert opts, n
        assert all(lim.min_app_kg <= kg <= lim.max_app_kg for kg in opts.values())


def test_no_fertilizer_inside_min_gap_or_after_pruning(env):
    _, sur, lim, ctxs = env
    c = ctxs[0]
    assert decision_bounds(replace(c, days_since_fert=10.0), lim)["n_hi"] == 0
    assert decision_bounds(replace(c, days_since_fert=200.0, days_since_pruning=5), lim)["n_hi"] == 0
    assert recommend(replace(c, days_since_fert=10.0, irrigation_available=False), sur, lim)["n_kg_per_ha"] == 0


def test_annual_ceiling_respected(env):
    _, sur, lim, ctxs = env
    c = replace(ctxs[0], days_since_fert=200.0, days_since_pruning=400, n_prior_60d=0.0, n_prior_90d=0.0)
    ceiling = lim.annual_n[c.agro_zone]
    near = replace(c, n_this_year=ceiling - 50)
    rec = recommend(near, sur, lim)
    assert rec["n_kg_per_ha"] <= 50 + 1e-6
    assert decision_bounds(replace(c, n_this_year=ceiling - 10), lim)["n_hi"] == 0   # below the minimum dose


def test_irrigation_only_when_allowed(env):
    _, _, lim, ctxs = env
    c = ctxs[0]
    trigger = c.wilting_point + lim.irr_trigger * (c.field_capacity - c.wilting_point)
    assert decision_bounds(replace(c, irrigation_available=False, soil_moisture=trigger - 3), lim)["irr_hi"] == 0
    assert decision_bounds(replace(c, irrigation_available=True, soil_moisture=trigger + 1), lim)["irr_hi"] == 0
    b = decision_bounds(replace(c, irrigation_available=True, soil_moisture=trigger - 3), lim)
    assert 0 < b["irr_hi"] <= lim.max_irr_event_mm
    assert decision_bounds(replace(c, irrigation_available=True, soil_moisture=trigger - 3), lim, water_l=0)["irr_hi"] == 0


def test_recommendations_inside_all_limits(env):
    _, sur, lim, ctxs = env
    for c in ctxs:
        rec = recommend(c, sur, lim)
        b = decision_bounds(c, lim)
        assert rec["n_kg_per_ha"] <= b["n_hi"] + 1e-6
        assert rec["irrigation_mm"] <= b["irr_hi"] + 1e-6
        if rec["n_kg_per_ha"] > 0:
            assert lim.min_app_kg <= rec["amount_kg_per_ha"] <= lim.max_app_kg
            assert c.n_this_year + rec["n_kg_per_ha"] <= lim.annual_n[c.agro_zone] + 1e-6
            assert rec["horizon_gain_kg_ha"] > SETTINGS["min_ae"] * rec["n_kg_per_ha"]   # efficiency rule
            assert rec["product"] in lim.n_frac and 0 <= rec["expected_runoff_loss_pct"] <= 100
        else:
            assert rec["action"] in ("No action", "Irrigate")


def test_recommendation_is_deterministic(env):
    _, sur, lim, ctxs = env
    assert recommend(ctxs[1], sur, lim) == recommend(ctxs[1], sur, lim)


def test_soil_n_window_mean():
    # an application made now has no effect on the week before the current round, then fades with tau
    assert window_mean([0], 0, 45)[0] == 0
    a, b = window_mean([0], 14, 45)[0], window_mean([0], 60, 45)[0]
    assert 0 < b < a < 1


def test_low_threshold_fertilizes_and_high_threshold_does_not(env):
    _, sur, lim, ctxs = env
    c = replace(ctxs[2], days_since_fert=120.0, days_since_pruning=400, n_prior_60d=0.0, n_prior_90d=0.0,
                n_this_year=0.0, prior_events=None)
    assert recommend(c, sur, lim, settings=dict(SETTINGS, min_ae=1000))["n_kg_per_ha"] == 0
    assert recommend(c, sur, lim, settings=dict(SETTINGS, min_ae=-1000))["n_kg_per_ha"] > 0
