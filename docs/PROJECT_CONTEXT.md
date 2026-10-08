# SmartTea-LK Component 04: Project Context & Decision History

This is a summary of the planning conversation with Claude (Cowork, Oct 7–8 2026) that produced the datasets in this folder. Read `CLAUDE.md` first; this file holds the reasoning behind it.

---

## 1. Original framework (from the user's PDF)
"AI-Based Tea Plantation Resource Optimization and Intervention Planning" (Component 04, updated framework).

- **Problem:** static, rule-of-thumb schedules for fertilizer, agrochemicals and irrigation ignore local microclimate. A monsoon washes fertilizer away; a dry spell makes treatments ineffective.
- **Research question:** apply the minimum physical resources for maximum yield, and decide *when* to deploy them so the weather doesn't negate their impact.
- **Financial and labour tracking were removed completely.** The scope is pure agronomic efficiency.
- **Three tiers:**
  1. AI weather prediction + ML surrogate (e.g. XGBoost) predicting the yield change (ΔY) for a given resource allocation under forecast weather.
  2. NSGA-II: maximize yield, minimize water + fertilizer volume, within operational constraints (max safe dose, available water).
  3. Predictive "Action Window" scheduling over a 72–96 h forecast, e.g. fertilizer when soil moisture is moderate and no rain is forecast for the next 12 h.
- **Dataset schema in the PDF:**
  - Plantation Condition & Weather: soil_moisture_pct, soil_ph, predicted_rainfall_mm, predicted_temp_c, current_yield_kg.
  - Intervention Records: type, amount, datetime, weather at execution, yield before → after.
  - Resource Usage: allocated vs used.
  - Operational Constraints: water capacity, max fertilizer, min absorption time.
- **Example output in the PDF:** 15.5 kg fertilizer (max 20 kg), window Oct 08 06:00, +9.2% yield, 98.5% absorption index.

## 2. Early review points (raised by Claude, still relevant)
- **Where timing is decided:** Tier 2 optimizes amounts without timing and Tier 3 picks the time afterwards, but yield depends on timing. Either add timing as an NSGA-II variable, or have Tier 3 re-score yield for the chosen window.
- **Choosing one plan:** NSGA-II returns a Pareto front, so a selection rule is needed.
- **The "absorption rate index" needs a definition and a way to measure it.**
- **Forecast uncertainty:** use rain-probability thresholds and safety margins.
- **The 15.5 kg / 20 kg example is unrealistic per hectare.** Real tea fertilizer is roughly 150–350 kg/ha of mixture per application, applied 3–4 times a year.
- **Most mature Sri Lankan tea is rain-fed.** Irrigation mainly applies to young tea and nurseries, so frame the water objective as "use rain and soil moisture well".
- **Agrochemicals need a pre-harvest interval** (MRL / export residue) as a scheduling constraint.

## 3. User's system decisions
- **Inputs:** soil condition, soil moisture, light level and fertilizer used, which would come from IoT. Live weather comes from an API.
- **The IoT system is NOT built now.** The models are built from datasets; IoT inputs are entered **manually on the backend**.
- **The system must update live** and predict "what to do next" for the best tea growth.
- **Development is moving to VS Code + Claude Code** (this folder).

## 4. Model choice (agreed)
- **Yield/growth surrogate: XGBoost.**
  - The data is tabular and medium-sized.
  - It is fast enough for NSGA-II to call it thousands of times.
  - It explains its predictions through SHAP and handles missing values.
  - Compare it against Ridge, Random Forest, LightGBM and MLP, and report RMSE/MAE/R².
- **Runoff/efficiency: XGBoost.**
- **Weather: use the Open-Meteo forecast directly.** An optional local-correction model (XGBoost/LSTM on API error) can add an "AI weather" contribution.
- **NSGA-II is the optimizer** (pymoo), not an ML model.
- **Pitfall:** trees can't extrapolate. Keep the optimizer bounds inside the training range and use monotonic constraints where the science is clear.

## 5. Data size rationale
- **Rule of thumb for XGBoost:** at least ~1,000 rows, ideally 5,000–10,000; about 2,500 or more for ~25 features.
- **Chosen size:** 50 blocks × 5 years, daily, giving about 9,000 plucking-round rows for yield and about 850 fertilizer applications for runoff. The runoff table is the bottleneck; use `--blocks-per-estate 16` for more rows.
- **Splits:** train 2021–2023/24, validate 2024, test 2025. Use TimeSeriesSplit + Optuna, and a learning curve to show the size is enough.
- **Caution:** more synthetic rows ≠ more information.

## 6. Synthetic generator (v1): process model summary
`generate_smarttea_data.py` simulates each block day by day.

**Soil water**
- Bucket model with a 400 mm root zone: infiltration (slope-dependent), FAO ET₀ × 0.9 × stress factor, drainage above field capacity.

**Growth per day**
`scale × age × cultivar × EWMA(f_temp·f_water·f_light·f_N·f_K·f_P·f_pH) × f_prune × (1 − blight loss) × noise`
- **Temperature:** optimum 18–26 °C.
- **Water:** stress below WP + 0.45·(FC − WP).
- **Nitrogen:** Mitscherlich curve, `0.5 + 0.5·(1 − e^(−N/30))`.
- **pH:** optimum 4.5–5.5.
- **Pruning:** no harvest for 60 days, a peak in year 2, then a slow decline.
- **Calibration:** two passes per zone, to mean annual green leaf of up ≈ 7,000, mid ≈ 6,000 and low ≈ 9,500 kg/ha.

**Fertilizer loss (runoff + volatilisation)**
- Base formula: `0.04 + 0.62·(1 − e^(−rain_eff/40))·(0.7 + slope/40)`.
- Effective rain: `rain_eff = r12 + 0.5·(r48 − r12) + 0.2·(r72 − r48)`.
- Extra loss when the soil is saturated, when it is dry (worse for urea), and for midday heat. Clipped to 0.02–0.9.
- The recorded `runoff_loss_est_pct` is the true loss plus noise.

**Nutrients and pH**
- The N pool gains from fertilizer × (1 − loss) and from mineralization.
- It loses through uptake proportional to growth, through leaching driven by rain, and through immobilization.
- N fertilizer acidifies the soil; dolomite raises pH over 90 days.

**Blister blight (above 600 m)**
- Risk comes from 5-day wet days × low sunshine.
- Fungicide protects for 10 days, unless more than 8 mm of rain falls within 4 h of spraying.

**Historical management**
- A static fertilizer calendar (up/mid: Mar, Jun, Oct; low: Feb, May, Aug, Nov) with jitter, avoiding downpour days.
- Irrigation on irrigable blocks when soil moisture is low and no rain is coming.
- Dolomite when the 30-day pH falls below 4.45.
- Fungicide when blight risk is high.

**Hybrid mode (`--real-data`)**
- Replaces weather, rain timing and soil with real data.
- Adds forecast columns.
- Soil-moisture thresholds are relative to each block's FC/WP.

## 7. Honest evaluation of the fully synthetic data (v1)
**Good**
- Linked tables that match the PDF schema.
- Built-in cause and effect.
- Calibrated yields; a median +11% yield change after fertilizer, close to the PDF's +9.2%.
- Noise and missing values.
- Reproducible.
- The models learn, with the expected ranking (XGB 0.93 > RF 0.85 > Ridge 0.60).

**Weak**
- **Circular:** the models learn the generator's equations, so R² reflects the formulas, not agronomy.
- Parameters are not TRI-validated.
- Unseen-block R² is only 0.80, and the model memorises blocks (`aspect` looked important despite having no effect).
- The runoff target isn't measurable in reality.
- Small tables: runoff 850, irrigation 212, dolomite 33.
- Training used perfect knowledge of rain vs live forecasts.
- Simplified, independent weather.
- Irrigation decisions used perfect foresight.

## 8. Public data search (what exists)
**No public dataset has block-level tea sensors + fertilizer timing + yield for Sri Lanka.**

Useful sources:
- Open-Meteo Historical & Previous Runs APIs
- NASA POWER
- ISRIC SoilGrids
- Forbes & Walker monthly production by elevation
- Papers useful for calibration or related work:
  - the Uva Medium rainfall vs yield study, 2003–2012 (optimum 2,500–3,000 mm/yr, at least 50 mm per month)
  - Pakistan NTHRI hybrid tea-yield study (MDPI Plants 2022; data not public)
  - Explainable AI for Ceylon tea yield (ScienceDirect 2025)
  - TRI digital library

**Not suitable:** the Kaggle "Crop Recommendation" dataset, which classifies crop type and doesn't include tea.

**Best route to real validation:** ask TRI or a plantation company for one estate's fertilizer and yield records.

## 9. Real data download (Oct 8 2026)
- The cloud sandbox couldn't reach these APIs, so the data was fetched through the user's in-app browser and processed.
- **Contents of `SmartTea_LK_C04_real_data`:**
  - hourly ERA5 weather + soil moisture/temperature (219,120 rows)
  - daily aggregates
  - forecast vs actual from 2024-01-19
  - NASA POWER daily
  - SoilGrids for all 50 block coordinates
  - national production 2021–2025 (from 47 PDFs; totals: 299.5 / 249.9 / 254.0 / 260.8 / 262.8 M kg)
  - a monthly weather × production table
- **Findings:**
  - ERA5 rainfall is plausible: Hatton and Ratnapura ~3,600–4,800 mm, Kandy ~1,550–2,050 mm, Nuwara Eliya ~2,350–3,150 mm.
  - Deniyaya rainfall looks low.
  - ERA5 sunshine duration is too high in the hills, so the generator derives sunshine from radiation instead.
  - The national monthly production vs weather correlation is weak (0.1–0.3).

## 10. Hybrid data (current) and what it improved
- **Real:** weather, hourly rain timing after actions, issued forecasts (real from 2024, sampled from the real error distribution before that), SoilGrids soil, field capacity/wilting point via Saxton-Rawls, block temperature lapse rate.
- **Effects:**
  - Unseen-block yield R² fell from 0.80 to 0.66 (more realistic).
  - Runoff with forecast-only features: R² 0.62 vs 0.94 with hindsight. This is the headline finding.
  - Simulated soil moisture matches ERA5-Land (r 0.85–0.91).
  - Seasonal shape vs national: high 0.73, low 0.68, medium ≈ 0 (unresolved).
  - Wetter, cloudier real weather produced more fungicide sprays (1,771) and irrigation events (611).
  - pH from SoilGrids (~5.2) means dolomite is almost never needed (1 event).
- **Real clay soils have a high wilting point** (~25%), so all soil-moisture rules became relative to each block's FC/WP.

## 11. Open questions / to-do
- [ ] Get real estate records (TRI or a plantation company) for final validation.
- [ ] Check fertilizer rates, N limits, loss coefficients, fungicide pre-harvest interval and blight parameters against TRI.
- [ ] Resolve or explain the medium-grown seasonality gap (more mid-country locations? growth-model drought response?).
- [ ] Decide how one plan is chosen from the NSGA-II Pareto front.
- [ ] Decide whether timing is optimized jointly in NSGA-II or by Tier 3 re-scoring.
- [ ] Define the absorption/efficiency index formally.
- [ ] Optional: train a local weather-correction model on the forecast-vs-actual data.
