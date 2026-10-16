import { useEffect, useState } from 'react'

const FIELDS = [
  ['soil_moisture_pct', 'Soil moisture', '% vol'],
  ['soil_ph', 'Soil pH', ''],
  ['soil_n_ppm', 'Soil N', 'ppm'],
  ['soil_p_ppm', 'Soil P', 'ppm'],
  ['soil_k_ppm', 'Soil K', 'ppm'],
  ['soil_temp_c', 'Soil temperature', '°C'],
  ['light_lux', 'Light', 'lux'],
  ['sunshine_hours', 'Sunshine', 'hours'],
]
const OPTIONAL = ['light_lux', 'sunshine_hours']
const PRODUCTS = [
  ['NPK_BAL', 'NPK balanced (21 % N)'],
  ['NPK_HN', 'NPK high-N (27 % N)'],
  ['UREA', 'Urea (46 % N)'],
]

// the same healthy baseline the demo scenarios use (a scenario changes only what it needs)
const DEMO_BASE = { soil_p_ppm: 20, soil_k_ppm: 120, soil_temp_c: 22, light_lux: 42000, sunshine_hours: 5 }
const WEATHER = [
  ['live', 'Live forecast'],
  ['dry', 'What-if: dry days ahead'],
  ['wet', 'What-if: wet, cloudy week'],
]
const daysAgo = (n) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 10)
}

const localNow = () => {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

/**
 * Manual entry form. It sends EXACTLY the JSON the future IoT device will POST to /api/readings,
 * so connecting real sensors later only changes where the data comes from.
 */
export default function ReadingForm({ block, lastReading, prefill, busy, onSubmit }) {
  const empty = Object.fromEntries(FIELDS.map(([k]) => [k, '']))
  const [values, setValues] = useState(empty)
  const [timestamp, setTimestamp] = useState(localNow())
  const [fert, setFert] = useState({ product_code: 'NPK_BAL', amount_kg_per_ha: '240', date: '' })
  const [weather, setWeather] = useState('live')
  const scenario = prefill && prefill.block_id === block.block_id ? prefill : null

  useEffect(() => {
    if (scenario) {   // a demo scenario: fill every field; the user reviews and presses Save
      setValues(
        Object.fromEntries(
          Object.entries({ ...DEMO_BASE, soil_moisture_pct: scenario.soil_moisture_pct, soil_ph: scenario.soil_ph, soil_n_ppm: scenario.soil_n_ppm }).map(
            ([k, v]) => [k, String(v)],
          ),
        ),
      )
      setFert({ product_code: 'NPK_BAL', amount_kg_per_ha: '240', date: daysAgo(scenario.last_fertilizer_days_ago) })
      setTimestamp(localNow())
      setWeather(scenario.what_if ?? 'live')
      return
    }
    setValues(empty)
    setWeather('live')
    const lf = lastReading?.last_fertilizer
    setFert(lf ? { ...lf, amount_kg_per_ha: String(lf.amount_kg_per_ha) } : { product_code: 'NPK_BAL', amount_kg_per_ha: '240', date: '' })
  }, [block.block_id, scenario?.loadedAt])

  function fillTypical() {
    const t = block.typical_readings[String(new Date().getMonth() + 1)]
    setValues(Object.fromEntries(FIELDS.map(([k]) => [k, t[k] == null ? values[k] : String(t[k])])))
  }
  function fillLast() {
    if (lastReading) setValues(Object.fromEntries(FIELDS.map(([k]) => [k, String(lastReading[k] ?? '')])))
  }

  const payload = {
    device_id: 'manual-entry',
    block_id: block.block_id,
    timestamp: timestamp.length === 16 ? `${timestamp}:00` : timestamp,
    ...Object.fromEntries(FIELDS.map(([k]) => [k, values[k] === '' ? null : Number(values[k])])),
    ...(fert.date
      ? { last_fertilizer: { product_code: fert.product_code, amount_kg_per_ha: Number(fert.amount_kg_per_ha), date: fert.date } }
      : {}),
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
      <form
        className="card"
        onSubmit={(e) => {
          e.preventDefault()
          onSubmit(payload, weather)
        }}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="card-title mb-0">New reading · {block.block_id}</div>
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" onClick={fillTypical}>
              Fill typical values (this month)
            </button>
            {lastReading && (
              <button type="button" className="btn-ghost" onClick={fillLast}>
                Copy last reading
              </button>
            )}
          </div>
        </div>
        {scenario ? (
          <div className="mt-3 rounded-lg border border-tea-600 bg-tea-50 px-3 py-2 text-sm text-tea-900">
            <b>Scenario loaded: {scenario.title}.</b> {scenario.shows}. The block's old readings were cleared and the
            values below are filled in. Check them, then press <b>Save reading and get recommendation</b>.
            <div className="mt-1 text-xs">
              Expected: <b>{scenario.expected}</b>
            </div>
          </div>
        ) : (
          <p className="mt-1 text-sm text-stone-500">
            No IoT hardware yet: values are entered by hand. The form sends the same JSON the sensor will send.
          </p>
        )}

        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          {FIELDS.map(([k, label, unit]) => (
            <label key={k} className="flex flex-col justify-end text-sm">
              <span className="text-stone-600">
                {label} {unit && <span className="text-stone-400">({unit})</span>}
              </span>
              <input
                className="input mt-1"
                type="number"
                step="any"
                required={!OPTIONAL.includes(k)}
                value={values[k]}
                onChange={(e) => setValues({ ...values, [k]: e.target.value })}
              />
            </label>
          ))}
          <label className="col-span-2 text-sm">
            <span className="text-stone-600">Reading time</span>
            <input className="input mt-1" type="datetime-local" value={timestamp} onChange={(e) => setTimestamp(e.target.value)} />
          </label>
        </div>

        <div className="mt-5 text-sm font-medium text-stone-700">Last fertilizer used</div>
        <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-3">
          <label className="text-sm">
            <span className="text-stone-600">Type</span>
            <select className="input mt-1" value={fert.product_code} onChange={(e) => setFert({ ...fert, product_code: e.target.value })}>
              {PRODUCTS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-stone-600">Amount (kg/ha)</span>
            <input
              className="input mt-1"
              type="number"
              value={fert.amount_kg_per_ha}
              onChange={(e) => setFert({ ...fert, amount_kg_per_ha: e.target.value })}
            />
          </label>
          <label className="text-sm">
            <span className="text-stone-600">Date (leave empty if none)</span>
            <input className="input mt-1" type="date" value={fert.date} onChange={(e) => setFert({ ...fert, date: e.target.value })} />
          </label>
        </div>

        <div className="mt-5 text-sm font-medium text-stone-700">Weather for the recommendation</div>
        <div className="mt-2 flex flex-wrap gap-2">
          <div className="flex overflow-hidden rounded-lg border border-stone-300 text-sm">
            {WEATHER.map(([k, label]) => (
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
        </div>
        <p className="mt-1 text-xs text-stone-400">
          Live = today's real Open-Meteo forecast. What-if = a clearly labelled simulated weather for demonstrations; it is
          sent as a URL option, so the reading JSON stays the IoT format.
        </p>

        <button className="btn mt-5" disabled={busy}>
          {busy ? 'Saving and running the AI pipeline…' : 'Save reading and get recommendation'}
        </button>
      </form>

      <div className="card">
        <div className="card-title">JSON sent to POST /api/readings</div>
        <pre className="overflow-x-auto rounded-lg bg-stone-900 p-3 text-xs text-tea-100">{JSON.stringify(payload, null, 2)}</pre>
        <p className="mt-2 text-xs text-stone-400">A real IoT device will POST this same JSON. Nothing else changes.</p>
      </div>
    </div>
  )
}
