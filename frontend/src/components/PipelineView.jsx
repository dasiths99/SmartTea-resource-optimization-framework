/** Shows how the three tiers produced the recommendation (for explaining the system to the panel). */
function Tier({ n, title, subtitle, children }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white p-4">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-tea-600 text-sm font-bold text-white">
          {n}
        </span>
        <div>
          <div className="font-semibold text-stone-800">{title}</div>
          <div className="text-xs text-stone-400">{subtitle}</div>
        </div>
      </div>
      <dl className="mt-3 space-y-1.5 text-sm">{children}</dl>
    </div>
  )
}

function Row({ k, v }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-stone-500">{k}</dt>
      <dd className="text-right font-medium text-stone-800">{v ?? '—'}</dd>
    </div>
  )
}

export default function PipelineView({ result: r }) {
  const t2 = r.tier2
  const t3 = r.tier3
  const inp = r.inputs_used
  const scan = t3.fertilizer_scan || []
  const okHours = scan.filter((s) => s.ok).length
  const byProduct = t2.runoff_by_product_pct
    ? Object.entries(t2.runoff_by_product_pct).map(([p, v]) => `${p} ${v}%`).join(' · ')
    : null

  return (
    <div className="card">
      <div className="card-title">How the AI pipeline decided</div>
      <div className="grid gap-3 lg:grid-cols-3">
        <Tier n="1" title="Prediction" subtitle="CatBoost yield · XGBoost runoff · Open-Meteo">
          <Row k="Yield if no action" v={`${t2.baseline_yield_kg_ha_day} kg/ha/day`} />
          <Row k="Yield with plan" v={`${t2.predicted_yield_kg_ha_day} kg/ha/day`} />
          <Row k="Forecast rain next 24 h" v={`${inp.forecast_rain_next_24h_mm} mm`} />
          <Row k="Rain last 3 days" v={`${inp.rain_prev_3d_mm} mm`} />
          {byProduct && <Row k="Runoff loss by product" v={byProduct} />}
        </Tier>
        <Tier n="2" title="NSGA-II optimizer" subtitle="max yield · min N · min water, within the rules">
          <Row k="Plan" v={t2.action} />
          <Row k="N dose" v={`${t2.n_kg_per_ha} kg N/ha (max ${t2.n_max_allowed})`} />
          {t2.product && <Row k="Product / amount" v={`${t2.product} · ${t2.amount_kg_per_ha} kg/ha`} />}
          <Row k="Gain over horizon" v={`${t2.horizon_gain_kg_ha} kg leaf/ha (${t2.horizon_days} d)`} />
          {t2.agronomic_efficiency_kg_leaf_per_kg_n && (
            <Row k="Leaf per kg N" v={`${t2.agronomic_efficiency_kg_leaf_per_kg_n} kg (threshold 3.5)`} />
          )}
          <Row k="Irrigation" v={`${t2.irrigation_mm} mm (max ${t2.irrigation_max_allowed_mm})`} />
        </Tier>
        <Tier n="3" title="Action Window" subtitle="best hour in next 96 h, 06:00–16:00">
          <Row k="Hours checked" v={scan.length ? `${scan.length} (${okHours} safe)` : 'not needed'} />
          <Row k="Soil-moisture band" v={`${t3.soil_moisture_band[0]}–${t3.soil_moisture_band[1]} %`} />
          <Row k="Soil moisture now" v={`${inp.sensor_7d_mean.soil_moisture_pct} %`} />
          <Row k="7-day mean pH" v={t3.ph_mean_7d} />
          <Row k="Blister-blight risk" v={`${t3.blight_risk} (spray > 0.35)`} />
        </Tier>
      </div>

      {t2.limits?.length > 0 && (
        <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          <b>Rules that applied:</b> {t2.limits.join('; ')}
        </div>
      )}

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-lg bg-stone-50 p-3 text-sm">
          <div className="mb-1 font-medium text-stone-700">Inputs used</div>
          <ul className="space-y-0.5 text-stone-600">
            {Object.entries(inp.sensor_7d_mean).map(([k, v]) => (
              <li key={k}>
                {k}: <b>{v}</b>
              </li>
            ))}
            <li>days since fertilizer: <b>{inp.days_since_fertilizer ?? 'none on record'}</b></li>
            <li>N applied this year: <b>{inp.n_this_year_kg_ha} kg/ha</b></li>
          </ul>
        </div>
        <div className="rounded-lg bg-stone-50 p-3 text-sm">
          <div className="mb-1 font-medium text-stone-700">Assumptions &amp; warnings</div>
          <ul className="list-disc space-y-0.5 pl-5 text-stone-600">
            {[...(r.assumptions || []), ...(r.warnings || [])].map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
