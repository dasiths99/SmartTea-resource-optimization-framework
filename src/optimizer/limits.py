"""Hard limits for the optimizer = 07_operational_constraints.csv intersected with the models' training ranges.

Tree models cannot extrapolate, so a decision is only allowed where BOTH the agronomic rule and the training data
allow it (data/model_ready/feature_spec.json, rule 5).
"""
from dataclasses import dataclass, field

import pandas as pd

from src.data.load import load_spec

HYBRID = "data/processed/hybrid"


@dataclass
class Limits:
    min_app_kg: float                 # mixture kg/ha per application (below this: not worth a field visit)
    max_app_kg: float
    annual_n: dict                    # kg N/ha per calendar year, by agro_zone
    min_gap_days: int                 # between fertilizer applications
    no_fert_after_pruning_days: int
    irr_trigger: float                # irrigate only below WP + trigger * (FC - WP)
    max_irr_event_mm: float
    water_l_month: float              # estate reservoir, litres per month
    n_frac: dict                      # kg N per kg mixture, by product
    n60_max: float                    # training ranges (yield model)
    n90_max: float
    irr_round_max: float
    n_app_range: tuple                # training range of N per application (runoff model)
    amount_range: tuple               # training range of mixture kg/ha per application (runoff model)
    sources: dict = field(default_factory=dict)

    def n_bounds(self):
        """Smallest and largest N per application that some product can deliver inside all limits."""
        lo = max(min(self.min_app_kg * f for f in self.n_frac.values()), self.n_app_range[0])
        hi = min(max(min(self.max_app_kg, self.amount_range[1]) * f for f in self.n_frac.values()), self.n_app_range[1])
        return lo, hi

    def products_for(self, n):
        """Products that deliver n kg N/ha with a mixture amount inside the rule and the training range."""
        lo, hi = max(self.min_app_kg, self.amount_range[0]), min(self.max_app_kg, self.amount_range[1])
        return {p: n / f for p, f in self.n_frac.items() if lo <= n / f <= hi}


def load_limits(hybrid=HYBRID):
    c = pd.read_csv(f"{hybrid}/07_operational_constraints.csv")
    val = lambda name, applies="all": float(c[(c.constraint_name == name) & (c.applies_to == applies)].value.iloc[0])
    ev = pd.read_csv(f"{hybrid}/05_intervention_records.csv")
    f = ev[ev.intervention_type == "fertilizer"]
    n_frac = (f.n_kg_per_ha / f.amount_per_ha).groupby(f.product_code).median().round(3).to_dict()
    yr, rr = load_spec()["yield"]["training_ranges"], load_spec()["runoff"]["training_ranges"]
    return Limits(
        min_app_kg=val("min_fertilizer_kg_per_ha_per_app"), max_app_kg=val("max_fertilizer_kg_per_ha_per_app"),
        annual_n={z: val("max_annual_n_kg_per_ha", z) for z in ("up", "mid", "low")},
        min_gap_days=int(val("min_days_between_fertilizer")),
        no_fert_after_pruning_days=int(val("no_fertilizer_after_pruning_days", "fertilizer")),
        irr_trigger=val("irrigation_trigger_soil_moisture", "irrigation"),
        max_irr_event_mm=val("max_irrigation_mm_per_event", "irrigation"),
        water_l_month=val("available_water_capacity_l_per_month", "estate"),
        n_frac=n_frac,
        n60_max=yr["n_applied_60d_kg_ha"][1], n90_max=yr["n_applied_90d_kg_ha"][1],
        irr_round_max=yr["irrigation_mm_in_round"][1],
        n_app_range=tuple(rr["n_kg_per_ha"]), amount_range=tuple(rr["amount_per_ha"]),
        sources={"rules": f"{hybrid}/07_operational_constraints.csv", "ranges": "data/model_ready/feature_spec.json"},
    )
