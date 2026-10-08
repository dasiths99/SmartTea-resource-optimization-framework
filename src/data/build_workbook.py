"""Build one Excel workbook holding the complete research dataset (data/release/SmartTea_LK_C04_Dataset.xlsx).

Sheets: README, Data_Dictionary, Validation, then one sheet per table (real pack, hybrid tables, master
block-day table and the two model-ready tables). The two hourly tables (219k and 85k rows) are left out to
keep the file usable; their daily aggregates are included and the hourly CSVs stay in data/interim/real/.

Usage:
    python -m src.data.build_workbook
"""
import argparse
import datetime as dt
import os

import pandas as pd

D = "data"
# sheet name -> (csv path under data/, origin, grain, description)
SHEETS = {
    "Estates": ("interim/real/00_estate_locations.csv", "real", "estate", "5 real tea-growing locations and their weather grid cell"),
    "Blocks": ("processed/hybrid/01_block_master.csv", "simulated + real soil", "block", "50 blocks: static features, SoilGrids soil, field capacity / wilting point"),
    "Weather_Daily": ("processed/hybrid/02_weather_daily.csv", "real", "estate × day", "ERA5 daily weather used by the simulation"),
    "Sensor_Readings": ("processed/hybrid/03_sensor_readings_daily.csv", "simulated", "block × day", "Daily soil / light readings = the IoT / manual input form"),
    "Yield_Records": ("processed/hybrid/04_yield_plucking_records.csv", "simulated", "plucking round", "Green-leaf harvest per plucking round"),
    "Interventions": ("processed/hybrid/05_intervention_records.csv", "simulated + real rain", "field action", "Every fertilizer, irrigation, fungicide and dolomite action with rain before/after"),
    "Resource_Usage": ("processed/hybrid/06_resource_usage_monthly.csv", "simulated", "estate × month × resource", "Allocated vs used inputs (not used by the models)"),
    "Constraints": ("processed/hybrid/07_operational_constraints.csv", "rules", "rule", "Optimizer limits and Action-Window scheduler rules"),
    "Forecasts_Issued": ("processed/hybrid/08_daily_forecasts_issued.csv", "real from 2024-01-20", "estate × day", "Rain forecast for day 0-3 issued each morning"),
    "Forecast_vs_Actual": ("interim/real/04_forecast_vs_actual_daily_2024_2025.csv", "real", "estate × day", "Archived 1-4 day rain forecasts vs what fell (forecast skill)"),
    "Soil_SoilGrids": ("interim/real/06_soilgrids_block_soil_properties.csv", "real", "block", "SoilGrids properties at 3 depths with 5-95 % range"),
    "NASA_POWER_Check": ("interim/real/05_nasa_power_daily_2021_2025.csv", "real", "estate × day", "Independent coarse weather cross-check"),
    "National_Production": ("interim/real/07_sl_tea_production_monthly_by_elevation_2021_2025.csv", "real", "month × elevation", "Sri Lanka tea production by elevation (Forbes & Walker)"),
    "Monthly_Zone": ("interim/real/08_monthly_weather_vs_production_by_elevation.csv", "derived", "month × zone", "Zone weather joined with national production"),
    "Master_Block_Daily": ("model_ready/smarttea_master_block_daily.csv.gz", "joined", "block × day", "ALL sources joined: one row per block per day"),
    "Yield_Model_Ready": ("model_ready/yield_model_ready.csv", "feed-ready", "plucking round", "Yield model table: meta + target + numeric features + splits"),
    "Runoff_Model_Ready": ("model_ready/runoff_model_ready.csv", "feed-ready", "fertilizer application", "Runoff model table: meta + target + numeric features + splits"),
}
NOT_INCLUDED = [
    ("interim/real/01_weather_hourly_era5_2021_2025.csv", "219,120 hourly rows; daily version is in Weather_Daily"),
    ("interim/real/03_forecast_vs_actual_hourly_2024_2025.csv", "85,475 hourly rows; daily version is in Forecast_vs_Actual"),
    ("interim/real/06b_soilgrids_block_soil_long.csv", "same values as Soil_SoilGrids in long format"),
    ("raw/ (51 files)", "original downloads and PDFs; see data/raw/MANIFEST.csv"),
    ("archive/synthetic_v1/", "old fully synthetic version, comparison only"),
]
VALIDATION = [  # data/processed/hybrid/validation_report_2026-10-08.txt + leave-one-estate-out check (2026-10-08)
    ("Yield", "Time split (test year 2025)", "Ridge", 0.644, 3.29),
    ("Yield", "Time split (test year 2025)", "Random Forest", 0.897, 1.76),
    ("Yield", "Time split (test year 2025)", "XGBoost", 0.944, 1.31),
    ("Yield", "Unseen blocks (block-grouped 5-fold CV)", "XGBoost", 0.823, None),
    ("Yield", "Unseen estate (leave-one-estate-out)", "XGBoost", 0.119, None),
    ("Runoff", "Actual rain after (hindsight, upper bound)", "Ridge", 0.739, 6.39),
    ("Runoff", "Actual rain after (hindsight, upper bound)", "Random Forest", 0.927, 4.26),
    ("Runoff", "Actual rain after (hindsight, upper bound)", "XGBoost", 0.937, 4.05),
    ("Runoff", "Forecast rain only (live-realistic)", "Ridge", 0.475, 11.03),
    ("Runoff", "Forecast rain only (live-realistic)", "Random Forest", 0.614, 9.25),
    ("Runoff", "Forecast rain only (live-realistic)", "XGBoost", 0.633, 8.87),
]
DATE_COLS = {"date", "pluck_date", "issue_date", "last_pruning_date_before_2021"}
DATETIME_COLS = {"execution_datetime"}


def load(rel):
    df = pd.read_csv(os.path.join(D, rel), low_memory=False)
    for c in df.columns:
        if c in DATE_COLS:
            df[c] = pd.to_datetime(df[c])
        elif c in DATETIME_COLS:
            df[c] = pd.to_datetime(df[c])
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="data/release/SmartTea_LK_C04_Dataset.xlsx")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)

    tables = {name: load(spec[0]) for name, spec in SHEETS.items()}
    dic = pd.read_csv(os.path.join(D, "data_dictionary.csv"))
    sheet_of = {f"data/{spec[0]}": name for name, spec in SHEETS.items()}
    dic = dic[dic.table.isin(sheet_of)].copy()
    dic.insert(0, "sheet", dic.table.map(sheet_of))

    with pd.ExcelWriter(a.out, engine="xlsxwriter", datetime_format="yyyy-mm-dd hh:mm", date_format="yyyy-mm-dd",
                        engine_kwargs={"options": {"strings_to_urls": False}}) as xw:
        wb = xw.book
        wb.formats[0].set_font_name("Arial")
        wb.formats[0].set_font_size(10)
        F = lambda **k: wb.add_format({"font_name": "Arial", "font_size": 10, **k})
        hdr = F(bold=True, bg_color="#1C5CAB", font_color="#FFFFFF", text_wrap=True, valign="top", border=1, border_color="#C3C2B7")
        title, h2 = F(bold=True, font_size=16), F(bold=True, font_size=12, font_color="#1C5CAB")
        bold, wrap, note = F(bold=True), F(text_wrap=True, valign="top"), F(italic=True, font_color="#52514E", text_wrap=True)
        link, cellb = F(font_color="#1C5CAB", underline=1), F(bold=True, bg_color="#F0EFEC", border=1, border_color="#C3C2B7")
        cell, num3 = F(border=1, border_color="#C3C2B7", text_wrap=True, valign="top"), F(border=1, border_color="#C3C2B7", num_format="0.000")
        date_f = F(num_format="yyyy-mm-dd")

        # ---------- README ----------
        ws = wb.add_worksheet("README")
        ws.hide_gridlines(2)
        ws.set_column("A:A", 24); ws.set_column("B:B", 16); ws.set_column("C:C", 12); ws.set_column("D:D", 22)
        ws.set_column("E:E", 22); ws.set_column("F:F", 70)
        r = 0
        ws.write(r, 0, "SmartTea-LK Component 04: Research Dataset", title); r += 1
        ws.write(r, 0, "AI-Based Tea Plantation Resource Optimization and Intervention Planning · Dasith Sathpura · CSP 001", note); r += 1
        ws.write(r, 0, "Generated", bold); ws.write_datetime(r, 1, dt.datetime.now().replace(microsecond=0), date_f)
        ws.write(r, 3, "Built by src/data/build_workbook.py from the CSV files in data/ (the CSVs are the master copy).", note); r += 2
        ws.write(r, 0, "What this dataset is", h2); r += 1
        for line in [
            "5 real tea-growing locations (Nuwara Eliya, Hatton, Kandy, Ratnapura, Deniyaya) × 10 blocks = 50 blocks, daily, 2021-01-01 to 2025-12-31.",
            "HYBRID data. REAL: weather (ERA5), rain timing after each field action, issued rain forecasts (real from 2024-01-20), soil (SoilGrids), national production.",
            "SIMULATED (process model): management decisions, crop growth and yield, fertilizer runoff loss, sensor readings (real conditions + noise, ~1.5 % missing).",
            "Models trained on it learn the simulated rules on top of a real environment. Validation on real estate records is the main open step.",
        ]:
            ws.merge_range(r, 0, r, 5, line, wrap); ws.set_row(r, 28); r += 1
        r += 1
        ws.write(r, 0, "Sheets (click a name to open it)", h2); r += 1
        for j, h in enumerate(["Sheet", "Rows", "Columns", "One row per", "Origin", "Contents"]):
            ws.write(r, j, h, hdr)
        r += 1
        extra = [("Data_Dictionary", len(dic), dic.shape[1], "column", "documentation", "Meaning, unit, origin, missing % and range of every column"),
                 ("Validation", len(VALIDATION), 5, "test", "results", "Baseline model results on this dataset")]
        for name, rows, ncol, grain, origin, desc in extra + [(n, len(tables[n]), tables[n].shape[1], s[2], s[1], s[3]) for n, s in SHEETS.items()]:
            ws.write_url(r, 0, f"internal:'{name}'!A1", link, string=name)
            ws.write_number(r, 1, rows, F(border=1, border_color="#C3C2B7", num_format="#,##0"))
            ws.write_number(r, 2, ncol, F(border=1, border_color="#C3C2B7"))
            for j, v in enumerate([grain, origin, desc], start=3):
                ws.write(r, j, v, cell)
            r += 1
        ws.write(r, 0, "Row counts are the number of data rows in each sheet when the file was generated.", note); r += 2
        ws.write(r, 0, "Not included (kept as CSV in the project)", h2); r += 1
        for path, why in NOT_INCLUDED:
            ws.write(r, 0, f"data/{path}", bold); ws.merge_range(r, 1, r, 5, why, wrap); r += 1
        r += 1
        ws.write(r, 0, "How to use for modelling", h2); r += 1
        for line in [
            "Targets: yield = green_leaf_kg_per_ha_per_day (Yield_Model_Ready); runoff = runoff_loss_est_pct (Runoff_Model_Ready).",
            "Never split rows randomly. Use the 'split' column (train 2021-2023, val 2024, test 2025), 'cv_fold' (unseen blocks) or 'estate_id' (unseen locations).",
            "Runoff: columns starting 'hindsight__' are rain that actually fell after application; the live system cannot know them. Use them only as an upper bound.",
            "Link keys: block_id (e.g. E03-B07 = estate E03, block 7); estate_id + date for weather and forecasts.",
        ]:
            ws.merge_range(r, 0, r, 5, line, wrap); ws.set_row(r, 28); r += 1
        r += 1
        ws.write(r, 0, "Sources and licences", h2); r += 1
        for src, lic in [("ERA5 / ERA5-Land via Open-Meteo Historical and Previous Runs APIs", "CC BY 4.0 (Copernicus Climate Change Service, Open-Meteo)"),
                         ("ISRIC SoilGrids 2.0, 250 m (Poggio et al. 2021)", "CC BY 4.0"),
                         ("NASA POWER, NASA Langley Research Center", "NASA open data"),
                         ("Forbes & Walker Tea Brokers, monthly Sri Lanka Tea Production reports", "Public reports; cite the source")]:
            ws.write(r, 0, src, wrap); ws.merge_range(r, 1, r, 5, lic, wrap); ws.set_row(r, 28); r += 1
        ws.write(r, 0, "Full URLs, retrieval dates and SHA-256 checksums: data/raw/MANIFEST.csv", note)
        ws.activate()

        # ---------- Validation ----------
        vs = wb.add_worksheet("Validation")
        vs.write(0, 0, "Baseline results (XGBoost: 600 trees, depth 5, lr 0.03; default settings, not tuned)", h2)
        for j, h in enumerate(["Model task", "Test", "Model", "R²", "MAE"]):
            vs.write(2, j, h, hdr)
        for i, row in enumerate(VALIDATION, start=3):
            for j, v in enumerate(row):
                if v is None:
                    vs.write_blank(i, j, None, cell)
                elif j == 3:
                    vs.write_number(i, j, v, num3)
                else:
                    vs.write(i, j, v, cell)
        n = 3 + len(VALIDATION)
        for k, line in enumerate([
            "MAE units: yield kg/ha/day; runoff percentage points.",
            "Source: data/processed/hybrid/validation_report_2026-10-08.txt; leave-one-estate-out from the model-ready check on 2026-10-08.",
            "Unseen-block yield R² was first reported as 0.66; that run used drop-first one-hot encoding, which cost ~0.15 R².",
            "Key finding: with forecast rain instead of actual rain, runoff R² falls from 0.94 to 0.63. Forecast error limits the Action-Window scheduler.",
        ]):
            vs.merge_range(n + 1 + k, 0, n + 1 + k, 4, line, note)
        vs.set_column("A:A", 12); vs.set_column("B:B", 44); vs.set_column("C:C", 16); vs.set_column("D:E", 10)

        # ---------- Data dictionary + table sheets ----------
        def put(name, df, widths=None):
            df.to_excel(xw, sheet_name=name, index=False)
            sh = xw.sheets[name]
            for j, c in enumerate(df.columns):
                sh.write(0, j, c, hdr)
                if widths:
                    w = widths.get(c, 14)
                else:
                    sample = df[c].head(200).astype(str).str.len().max() if len(df) else 0
                    w = min(max(len(str(c)) * 0.9, sample if pd.notna(sample) else 8, 8) + 2, 42)
                if c in DATE_COLS:
                    w = max(w, 12)
                sh.set_column(j, j, w)
            sh.freeze_panes(1, 1 if name != "Data_Dictionary" else 2)
            sh.autofilter(0, 0, len(df), df.shape[1] - 1)
            sh.set_row(0, 30)

        put("Data_Dictionary", dic.drop(columns="table"),
            {"sheet": 20, "column": 34, "type": 8, "unit": 14, "origin": 11, "description": 80, "missing_pct": 11, "range_or_levels": 50})
        for name in SHEETS:
            put(name, tables[name])
            print(f"  {name:22s} {len(tables[name]):>7,} rows x {tables[name].shape[1]:>3} cols")
    print(f"written {a.out} ({os.path.getsize(a.out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
