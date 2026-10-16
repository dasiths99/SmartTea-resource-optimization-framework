import { useState } from 'react'

const STYLE = {
  'Apply fertilizer': 'bg-tea-600 text-white',
  'Delay fertilizer': 'bg-amber-500 text-white',
  Irrigate: 'bg-sky-600 text-white',
  'Skip irrigation': 'bg-sky-300 text-sky-950',
  'No action': 'bg-stone-500 text-white',
}
// the actions the user can mark as done, and the type the system records for each
const DONE_TYPE = {
  'Apply fertilizer': 'fertilizer',
  Irrigate: 'irrigation',
  'Apply dolomite (pH correction)': 'dolomite',
  'Spray fungicide (blister blight)': 'fungicide',
}
const style = (a) => STYLE[a] || 'bg-violet-600 text-white'

function Stat({ label, value, hint }) {
  return (
    <div className="rounded-lg bg-stone-50 px-4 py-3">
      <div className="text-xs text-stone-500">{label}</div>
      <div className="text-lg font-semibold text-stone-900">{value ?? '—'}</div>
      {hint && <div className="text-xs text-stone-400">{hint}</div>}
    </div>
  )
}

export default function RecommendationCard({ rec, busy, onRerun, onMarkDone, onEnter }) {
  const [minAe, setMinAe] = useState('')
  const [weather, setWeather] = useState('live')
  const [showJson, setShowJson] = useState(false)

  if (!rec)
    return (
      <div className="card text-center">
        <p className="text-stone-600">No recommendation for this block yet.</p>
        <p className="mt-1 text-sm text-stone-400">Enter a sensor reading; the system recommends straight away.</p>
        <button className="btn mt-4" onClick={onEnter}>
          Enter a reading
        </button>
      </div>
    )

  const r = rec.result
  const t2 = r.tier2
  // the short output in the framework's format (what the IoT/mobile side would receive)
  const short = {
    block_id: r.block_id,
    action: r.action,
    amount_kg_per_ha: r.amount_kg_per_ha ?? null,
    window: r.window ?? null,
    reason: r.reason,
    predicted_yield_change_pct: r.predicted_yield_change_pct,
    efficiency_score: r.efficiency_score ?? null,
  }

  return (
    <div className="card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="card-title mb-1">Recommendation · {r.block_id}</div>
          <div className="text-xs text-stone-400">
            {new Date(rec.created_at).toLocaleString()} · trigger: {rec.trigger.replace('_', ' ')}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex overflow-hidden rounded-lg border border-stone-300 text-sm" title="Weather used for the re-run">
            {[
              ['live', 'Live forecast'],
              ['dry', 'What-if: dry'],
              ['wet', 'What-if: wet week'],
            ].map(([k, label]) => (
              <button
                key={k}
                type="button"
                onClick={() => setWeather(k)}
                className={`px-3 py-1.5 ${weather === k ? 'bg-tea-600 text-white' : 'bg-white text-stone-700 hover:bg-stone-100'}`}
              >
                {label}
              </button>
            ))}
          </div>
          <input
            className="input"
            style={{ width: 112 }}
            placeholder="min_ae 3.5"
            value={minAe}
            onChange={(e) => setMinAe(e.target.value)}
            title="Pick-rule threshold: kg green leaf each kg N must add (default 3.5)"
          />
          <button className="btn" disabled={busy} onClick={() => onRerun(minAe ? Number(minAe) : null, weather)}>
            {busy ? 'Running…' : 'Re-run now'}
          </button>
        </div>
      </div>

      {r.what_if && (
        <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <b>What-if demo:</b>{' '}
          {r.what_if === 'dry'
            ? 'the forecast rain for the coming days was set to 0 (simulated dry weather), not the live forecast.'
            : 'the past 7 days were set to wet and cloudy (simulated blight weather); the coming days use the live forecast.'}
        </div>
      )}

      <div className="mt-4 space-y-3">
        {r.actions.map((a, i) => (
          <div key={i} className="rounded-xl border border-stone-200 p-4">
            <div className="flex flex-wrap items-center gap-3">
              <span className={`rounded-lg px-3 py-1.5 text-base font-semibold ${style(a.action)}`}>{a.action}</span>
              {a.amount > 0 && (
                <span className="text-lg font-semibold text-stone-800">
                  {a.amount} {a.unit} {a.product && <span className="text-stone-500">({a.product})</span>}
                </span>
              )}
              {a.window && (
                <span className="rounded-md bg-tea-50 px-2 py-1 text-sm font-medium text-tea-700">🕒 {a.window}</span>
              )}
            </div>
            <p className="mt-2 text-sm text-stone-600">{a.reason}</p>
            {DONE_TYPE[a.action] && (
              <button
                className="btn-ghost mt-3"
                disabled={busy}
                title="Record that this was done today, so the system does not repeat it before the minimum gap"
                onClick={() => {
                  if (window.confirm(`Record "${a.action}" as done today on ${r.block_id}?`))
                    onMarkDone({ type: DONE_TYPE[a.action], amount: a.amount, unit: a.unit, product: a.product })
                }}
              >
                ✓ Mark as done
              </button>
            )}
          </div>
        ))}
        {r.actions[0]?.action !== 'No action' && r.tier3?.suppressed?.map((t, i) => (
          <div key={`s${i}`} className="rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm text-stone-600">
            <b>Not repeated:</b> {t}
          </div>
        ))}
        {r.tier3?.reminders?.map((t, i) => (
          <div key={`r${i}`} className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <b>Reminder:</b> {t}
          </div>
        ))}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label="Predicted yield change"
          value={r.predicted_yield_change_pct != null ? `${r.predicted_yield_change_pct > 0 ? '+' : ''}${r.predicted_yield_change_pct} %` : null}
          hint="next plucking round vs no action"
        />
        <Stat label="Efficiency score" value={r.efficiency_score} hint="1 − predicted runoff loss" />
        <Stat label="N planned" value={`${t2.n_kg_per_ha} kg N/ha`} hint={`max allowed ${t2.n_max_allowed}`} />
        <Stat
          label="Baseline yield"
          value={`${t2.baseline_yield_kg_ha_day} kg/ha/day`}
          hint={`round of ${t2.round_days} days`}
        />
      </div>

      <button className="btn-ghost mt-4" onClick={() => setShowJson(!showJson)}>
        {showJson ? 'Hide' : 'Show'} output JSON
      </button>
      {showJson && (
        <pre className="mt-2 overflow-x-auto rounded-lg bg-stone-900 p-3 text-xs text-tea-100">
          {JSON.stringify(short, null, 2)}
        </pre>
      )}
    </div>
  )
}
