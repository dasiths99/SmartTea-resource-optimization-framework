import { useEffect, useState } from 'react'
import { api } from '../api'

const WEATHER = {
  null: ['Live forecast', 'bg-sky-100 text-sky-800'],
  dry: ['What-if: dry days ahead', 'bg-amber-100 text-amber-800'],
  wet: ['What-if: wet, cloudy week', 'bg-violet-100 text-violet-800'],
}

/**
 * Scenarios for the viva. "Load into the form" clears the scenario block's old readings and opens the
 * Enter reading tab with the scenario's values filled in; the user then saves the reading to get the recommendation.
 */
export default function DemoScenarios({ onLoad, busy, setBusy, setError }) {
  const [list, setList] = useState([])
  const [running, setRunning] = useState('')

  useEffect(() => {
    api.demoScenarios().then(setList).catch((e) => setError(e.message))
  }, [])

  async function run(s) {
    setBusy(true)
    setRunning(s.key)
    setError('')
    try {
      await api.clearBlock(s.block_id)   // start the scenario from a clean block
      onLoad(s)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
      setRunning('')
    }
  }

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-title">Demo scenarios</div>
        <p className="text-sm text-stone-600">
          <b>Load into the form</b> clears the block's earlier readings and opens <b>Enter reading (IoT)</b> with the
          scenario's values filled in. Check them, then press <b>Save reading and get recommendation</b> to run the AI
          (Tier 1 → Tier 2 → Tier 3). Blue = today's real Open-Meteo forecast. Amber / violet = a clearly labelled
          what-if weather, to show results that today's weather does not produce.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {list.map((s) => {
          const [label, cls] = WEATHER[s.what_if ?? null]
          return (
            <div key={s.key} className="card flex flex-col">
              <div className="flex items-start justify-between gap-2">
                <div className="font-semibold text-stone-800">{s.title}</div>
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{label}</span>
              </div>
              <p className="mt-1 text-sm text-stone-500">{s.shows}</p>
              <div className="mt-3 rounded-lg bg-stone-50 p-2 text-xs text-stone-600">
                <b>{s.block_id}</b> · moisture {s.soil_moisture_pct} % · pH {s.soil_ph} · N {s.soil_n_ppm} ppm · last
                fertilizer {s.last_fertilizer_days_ago} days ago
              </div>
              <p className="mt-2 text-sm">
                <span className="text-stone-500">Expected: </span>
                <span className="font-medium text-stone-800">{s.expected}</span>
              </p>
              <button className="btn mt-auto self-start" style={{ marginTop: 12 }} disabled={busy} onClick={() => run(s)}>
                {running === s.key ? 'Loading…' : 'Load into the form'}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
