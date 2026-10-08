"""SHAP explanations for the saved yield and runoff models.

For each model (all rows of its model-ready table, live features):
  importance_<task>.png   mean |SHAP| per feature, one-hot groups summed into one bar (top 15)
  beeswarm_<task>.png     per-row SHAP values coloured by feature value (top 12)
  dependence_<task>.png   SHAP vs value for the key agronomic features
  shap_importance_<task>.csv, agronomy_checks.csv
The agronomy check compares the sign of each key feature's effect with the expected science.

Usage:
    python -m src.models.explain_shap       # writes artifacts/reports/shap/
"""
import json
import os

import joblib
import matplotlib
import numpy as np
import pandas as pd
import shap

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap

from src.data.load import load_task

OUT = "artifacts/reports/shap"
MODELS = {"yield": "yield_catboost", "runoff": "runoff_xgboost"}
# chart style (reference palette from the dataviz skill)
INK, INK2, MUTED, GRID, AXIS, BLUE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#2a78d6"
SEQ = LinearSegmentedColormap.from_list("seq_blue", ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
LABELS = {
    "fc_rain_next_12h_mm": "Forecast rain, next 12 h (mm)", "fc_rain_next_24h_mm": "Forecast rain, next 24 h (mm)",
    "fc_rain_next_48h_mm": "Forecast rain, next 48 h (mm)", "fc_rain_next_72h_mm": "Forecast rain, next 72 h (mm)",
    "slope_pct": "Slope (%)", "soil_moisture_at_exec": "Soil moisture at application (%)",
    "amount_per_ha": "Fertilizer amount (kg/ha)", "n_kg_per_ha": "Nitrogen applied (kg N/ha)",
    "rain_prev_3d_mm": "Rain in previous 3 days (mm)", "temp_at_exec_c": "Air temperature at application (°C)",
    "humidity_at_exec_pct": "Humidity at application (%)", "hour": "Hour of application",
    "field_capacity_pct": "Field capacity (%)", "elevation_m": "Elevation (m)", "month": "Month",
    "shade_tree_cover_pct": "Shade cover (%)", "product_code": "Fertilizer product", "agro_zone": "Elevation zone",
    "soil_type": "Soil type", "plucking_standard": "Plucking standard", "cultivar": "Cultivar",
    "days_since_pruning": "Days since pruning", "round_days": "Plucking round length (days)",
    "n_applied_60d_kg_ha": "N applied, last 60 days (kg/ha)", "n_applied_90d_kg_ha": "N applied, last 90 days (kg/ha)",
    "days_since_last_fertilizer": "Days since last fertilizer", "irrigation_mm_in_round": "Irrigation in round (mm)",
    "fungicide_sprays_14d": "Fungicide sprays, last 14 days", "dolomite_last_365d": "Dolomite in last year",
    "start_soil_moisture_pct_7d": "Soil moisture, week before (%)", "start_soil_n_ppm_7d": "Soil N, week before (ppm)",
    "start_soil_ph_7d": "Soil pH, week before", "start_soil_temp_c_7d": "Soil temperature, week before (°C)",
    "start_light_lux_7d": "Light, week before (lux)", "start_sunshine_hours_7d": "Sunshine, week before (h/day)",
    "start_rain_7d_mm": "Rain, week before (mm)", "start_rain_30d_mm": "Rain, 30 days before (mm)",
    "start_temp_mean_7d_c": "Air temperature, week before (°C)", "start_et0_7d_mm": "Evapotranspiration, week before (mm)",
    "fc_rain_next4d_mm": "Rain forecast, next 4 days (mm)", "clim_rain_round_mm": "Normal rain for the round (mm)",
    "clim_temp_mean_c": "Normal temperature for the month (°C)", "clim_solar_mj_m2_day": "Normal radiation for the month",
    "clim_et0_round_mm": "Normal evapotranspiration for the round (mm)", "bush_age_yrs": "Bush age (years)",
    "sg_ph_h2o": "SoilGrids pH", "sg_total_n_g_kg": "SoilGrids total N (g/kg)", "temp_offset_c": "Block temperature offset (°C)",
    "irrigation_available": "Irrigation available", "area_ha": "Block area (ha)", "wilting_point_pct": "Wilting point (%)",
    "pruning_cycle_yrs": "Pruning cycle (years)", "weather_grid_elevation_m": "Weather grid elevation (m)",
    "temp_prev_day_c": "Air temperature, previous day (°C)", "humidity_prev_day_pct": "Humidity, previous day (%)",
}
# expected direction of effect (+1 more value -> higher prediction, -1 -> lower), from agronomy / the framework
EXPECT = {
    "runoff": {"fc_rain_next_12h_mm": +1, "fc_rain_next_24h_mm": +1, "slope_pct": +1, "amount_per_ha": 0},
    "yield": {"n_applied_60d_kg_ha": +1, "start_soil_moisture_pct_7d": +1, "start_soil_n_ppm_7d": +1,
              "fungicide_sprays_14d": +1},
}
DEPENDENCE = {
    "runoff": ["fc_rain_next_12h_mm", "fc_rain_next_72h_mm", "slope_pct", "soil_moisture_at_exec"],
    "yield": ["n_applied_60d_kg_ha", "start_soil_moisture_pct_7d", "days_since_pruning", "clim_temp_mean_c"],
}


def style():
    for f in ["segoeui.ttf", "segoeuib.ttf"]:
        p = f"C:/Windows/Fonts/{f}"
        if os.path.exists(p):
            font_manager.fontManager.addfont(p)
    plt.rcParams.update({
        "font.family": "Segoe UI", "font.size": 8.5, "text.color": INK, "axes.labelcolor": INK2, "axes.edgecolor": AXIS,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
        "axes.spines.right": False, "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.axisbelow": True, "savefig.dpi": 220, "savefig.bbox": "tight"})


def label(c):
    return LABELS.get(c, c.replace("_", " "))


def grouped(sv, cols):
    """Sum SHAP of one-hot columns (name__level) into their parent feature."""
    groups = pd.Index([c.split("__")[0] for c in cols])
    return pd.DataFrame(sv, columns=cols).T.groupby(groups, sort=False).sum().T


def explain(task):
    meta = json.load(open(f"artifacts/models/{MODELS[task]}.json"))
    model = joblib.load(f"artifacts/models/{MODELS[task]}.joblib")
    X, y, m = load_task(task, "live")
    assert list(X.columns) == meta["features"]
    sv = shap.TreeExplainer(model).shap_values(X.to_numpy(np.float32))
    g = grouped(sv, list(X.columns))
    imp = g.abs().mean().sort_values(ascending=False)
    imp_df = pd.DataFrame({"feature": imp.index, "label": [label(c) for c in imp.index],
                           "mean_abs_shap": imp.values, "share_pct": imp.values / imp.sum() * 100})
    imp_df.round(4).to_csv(f"{OUT}/shap_importance_{task}.csv", index=False)
    unit = "kg/ha/day" if task == "yield" else "percentage points"

    # importance bar
    top = imp_df.head(15).iloc[::-1]
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    bars = ax.barh(top.label, top.mean_abs_shap, color=BLUE, height=0.6)
    for b, v, s in zip(bars, top.mean_abs_shap, top.share_pct):
        ax.text(v, b.get_y() + b.get_height() / 2, f"  {v:.2f} ({s:.0f}%)", va="center", fontsize=7.5, color=INK2)
    ax.set_xlabel(f"Mean |SHAP| ({unit})"); ax.grid(axis="y", visible=False)
    ax.set_xlim(0, top.mean_abs_shap.max() * 1.3)
    ax.set_title(f"{task.capitalize()} model ({meta['model']}): what drives the prediction")
    fig.savefig(f"{OUT}/importance_{task}.png"); plt.close(fig)

    # beeswarm (non-grouped numeric features only, so the colour = feature value is meaningful)
    num = [c for c in imp.index if c in X.columns][:12]
    idx = [list(X.columns).index(c) for c in num]
    expl = shap.Explanation(values=sv[:, idx], data=X[num].to_numpy(), feature_names=[label(c) for c in num])
    plt.figure()
    shap.plots.beeswarm(expl, max_display=12, color=SEQ, show=False, plot_size=(6.6, 4.6), s=6, alpha=0.6)
    ax = plt.gca(); ax.set_xlabel(f"SHAP value: effect on predicted {task} ({unit})", color=INK2)
    ax.set_title(f"{task.capitalize()}: how each feature's value moves the prediction", loc="left")
    plt.savefig(f"{OUT}/beeswarm_{task}.png"); plt.close("all")

    # dependence
    fig, axs = plt.subplots(2, 2, figsize=(6.6, 5.0))
    for ax, c in zip(axs.flat, DEPENDENCE[task]):
        j = list(X.columns).index(c)
        ax.scatter(X[c], sv[:, j], s=5, color=BLUE, alpha=0.35, lw=0)
        ax.axhline(0, color=AXIS, lw=0.8)
        ax.set_xlabel(label(c)); ax.set_ylabel("SHAP")
    fig.suptitle(f"{task.capitalize()}: effect of key features (each dot = one row)", x=0.02, ha="left",
                 fontsize=9.5, fontweight="bold")
    fig.tight_layout(); fig.savefig(f"{OUT}/dependence_{task}.png"); plt.close(fig)

    # agronomy direction check: Spearman correlation between feature value and its SHAP value
    rows = []
    for c, exp in EXPECT[task].items():
        j = list(X.columns).index(c)
        rho = pd.Series(X[c].to_numpy()).corr(pd.Series(sv[:, j]), method="spearman")
        got = 0 if abs(rho) < 0.1 else int(np.sign(rho))
        ok = (exp == 0) or (got == exp)
        rows.append(dict(task=task, feature=c, expected=exp, spearman_value_vs_shap=round(rho, 3),
                         observed=got, agrees=ok))
    print(f"\n{task} ({meta['model']}) top 8 drivers:")
    print(imp_df.head(8)[["label", "mean_abs_shap", "share_pct"]].round(2).to_string(index=False))
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    style()
    checks = pd.DataFrame(explain("yield") + explain("runoff"))
    checks.to_csv(f"{OUT}/agronomy_checks.csv", index=False)
    print("\nAgronomy direction check (expected +1 = higher value -> higher prediction; 0 = no expectation):")
    print(checks.to_string(index=False))


if __name__ == "__main__":
    main()
