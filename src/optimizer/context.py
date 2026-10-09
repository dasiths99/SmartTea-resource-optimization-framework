"""Block state at decision time: what the optimizer knows when a plucking round starts.

A context is built from a round of data/model_ready/yield_model_ready.csv (its live features describe the coming
round) plus the block's fertilizer history BEFORE the decision date. The history is passed in, so a closed-loop
evaluation can feed the optimizer's own earlier decisions back in. In the live service (roadmap step 5) the same
fields will come from the latest IoT/manual reading and the Open-Meteo forecast.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.data.load import MODEL_READY, load_spec

HYBRID = "data/processed/hybrid"
DEFAULT_HOUR = 8   # planned application hour for the Tier 2 runoff estimate; Tier 3 picks the real window


@dataclass
class BlockContext:
    block_id: str
    decision_date: pd.Timestamp
    round_days: int
    agro_zone: str
    yield_row: pd.Series        # live yield features for the coming round (decision columns get overwritten)
    runoff_row: pd.Series       # live runoff features at the decision time (amount, N, product get overwritten)
    n_prior_60d: float          # N already applied inside the round's 60-day window, before the decision
    n_prior_90d: float
    n_this_year: float          # N applied this calendar year before the decision
    days_since_fert: float      # at the decision date (NaN = none on record)
    days_since_pruning: int     # at the decision date
    soil_moisture: float        # % vol, latest reading
    field_capacity: float
    wilting_point: float
    irrigation_available: bool
    area_ha: float
    prior_events: pd.DataFrame = None   # applications in the last 365 days: date, n_kg_per_ha, n_eff (after runoff)


def forecast_windows(d0, d1, d2, d3, hour):
    """Rain (mm) expected in the next 12/24/48/72 h from daily forecast totals (same rule as the training data)."""
    rem = (24 - hour) / 24
    return {"fc_rain_next_12h_mm": d0 * min(12, 24 - hour) / 24 + d1 * max(0, hour - 12) / 24,
            "fc_rain_next_24h_mm": d0 * rem + d1 * hour / 24,
            "fc_rain_next_48h_mm": d0 * rem + d1 + d2 * hour / 24,
            "fc_rain_next_72h_mm": d0 * rem + d1 + d2 + d3 * hour / 24}


class History:
    """Loads the tables once; builds contexts for any round."""

    def __init__(self):
        spec = load_spec()
        self.yield_features = spec["yield"]["feature_sets"]["live"]
        self.runoff_features = spec["runoff"]["feature_sets"]["live"]
        self.rounds = pd.read_csv(f"{MODEL_READY}/yield_model_ready.csv", parse_dates=["pluck_date"])
        cols = ["block_id", "date", "soil_moisture_pct", "wx_rainfall_mm", "wx_temp_mean_c", "wx_humidity_pct",
                "fc_rain_day0_mm", "fc_rain_day1_mm", "fc_rain_day2_mm", "fc_rain_day3_mm"]
        d = pd.read_csv(f"{MODEL_READY}/smarttea_master_block_daily.csv.gz", usecols=cols, parse_dates=["date"])
        d["soil_moisture_pct"] = d.groupby("block_id").soil_moisture_pct.ffill()   # ~1.5% missing readings
        self.daily = d.set_index(["block_id", "date"]).sort_index()
        self.blocks = pd.read_csv(f"{HYBRID}/01_block_master.csv").set_index("block_id")
        ev = pd.read_csv(f"{HYBRID}/05_intervention_records.csv", parse_dates=["execution_datetime"])
        f = ev[ev.intervention_type == "fertilizer"]
        self.fert = pd.DataFrame({"block_id": f.block_id, "date": f.execution_datetime.dt.normalize(),
                                  "n_kg_per_ha": f.n_kg_per_ha, "amount_per_ha": f.amount_per_ha,
                                  "product_code": f.product_code,
                                  "n_eff": f.n_kg_per_ha * (1 - f.runoff_loss_est_pct / 100)}).reset_index(drop=True)

    def context(self, row, fert_events, hour=DEFAULT_HOUR):
        """row: one yield_model_ready row. fert_events: this block's applications (date, n_kg_per_ha, n_eff)."""
        b, end, k = row.block_id, pd.Timestamp(row.pluck_date), int(row.round_days)
        dd = end - pd.Timedelta(days=k)                                   # decision = round start
        prior = fert_events[fert_events.date < dd]
        last = prior.date.max()
        blk = self.blocks.loc[b]
        day = self.daily.loc[(b, dd)]
        prev = self.daily.loc[(b, dd - pd.Timedelta(days=1))]
        rain3 = self.daily.loc[(b, slice(dd - pd.Timedelta(days=3), dd - pd.Timedelta(days=1))), "wx_rainfall_mm"].sum()
        fc = [0.0 if pd.isna(day[f"fc_rain_day{i}_mm"]) else float(day[f"fc_rain_day{i}_mm"]) for i in range(4)]
        r = pd.Series(0.0, index=self.runoff_features)
        r.update(pd.Series({"month": dd.month, "hour": hour, "elevation_m": blk.elevation_m, "slope_pct": blk.slope_pct,
                            "field_capacity_pct": blk.field_capacity_pct, "shade_tree_cover_pct": blk.shade_tree_cover_pct,
                            "soil_moisture_at_exec": day.soil_moisture_pct,
                            "temp_prev_day_c": prev.wx_temp_mean_c + blk.temp_offset_c,
                            "humidity_prev_day_pct": prev.wx_humidity_pct, "rain_prev_3d_mm": rain3,
                            f"agro_zone__{blk.agro_zone}": 1.0, f"soil_type__{blk.soil_type}": 1.0,
                            **forecast_windows(*fc, hour)}))
        return BlockContext(
            block_id=b, decision_date=dd, round_days=k, agro_zone=blk.agro_zone,
            yield_row=row[self.yield_features].astype(float), runoff_row=r,
            n_prior_60d=prior[prior.date >= end - pd.Timedelta(days=60)].n_kg_per_ha.sum(),
            n_prior_90d=prior[prior.date >= end - pd.Timedelta(days=90)].n_kg_per_ha.sum(),
            n_this_year=prior[prior.date.dt.year == dd.year].n_kg_per_ha.sum(),
            days_since_fert=(dd - last).days if pd.notna(last) else np.nan,
            days_since_pruning=int(row.days_since_pruning) - k,
            soil_moisture=float(day.soil_moisture_pct), field_capacity=float(blk.field_capacity_pct),
            wilting_point=float(blk.wilting_point_pct), irrigation_available=bool(blk.irrigation_available),
            area_ha=float(blk.area_ha),
            prior_events=prior[prior.date >= dd - pd.Timedelta(days=365)][["date", "n_kg_per_ha", "n_eff"]])
