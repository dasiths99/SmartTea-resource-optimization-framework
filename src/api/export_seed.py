"""Exports the seed data the Spring Boot backend loads into MongoDB on first start.

    backend/src/main/resources/seed/estates.json   5 estates (real locations, used for the Open-Meteo forecast)
    backend/src/main/resources/seed/blocks.json    50 blocks (static features) + typical sensor values per month
                                                   (2025 means; the dashboard's "fill sample values" button)
Usage:
    python -m src.api.export_seed
"""
import json

import pandas as pd

from src.api.live import BlockStore, SENSORS

OUT = "backend/src/main/resources/seed"


def main():
    store = BlockStore()
    s = pd.read_csv("data/processed/hybrid/03_sensor_readings_daily.csv", parse_dates=["date"])
    s = s[s.date.dt.year == 2025].assign(month=lambda d: d.date.dt.month)
    typical = s.groupby(["block_id", "month"])[list(SENSORS)].mean().round(2)
    names = pd.read_csv("data/processed/hybrid/01_block_master.csv").set_index("block_id").estate_name
    blocks = []
    for b in store.block_list():
        t = typical.loc[b["block_id"]]
        b["estate_name"] = names[b["block_id"]]
        b["irrigation_available"] = bool(b["irrigation_available"])
        b["typical_readings"] = {str(m): t.loc[m].to_dict() for m in t.index}
        blocks.append(b)
    estates = store.estate_list()
    for e in estates:
        e["estate_name"] = names[names.index.str.startswith(e["estate_id"])].iloc[0]
    json.dump(estates, open(f"{OUT}/estates.json", "w"), indent=1)
    json.dump(blocks, open(f"{OUT}/blocks.json", "w"), indent=1, default=float)
    print(f"wrote {len(estates)} estates, {len(blocks)} blocks to {OUT}")


if __name__ == "__main__":
    main()
