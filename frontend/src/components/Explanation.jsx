import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const DOT = { good: 'bg-tea-600', warn: 'bg-amber-500', bad: 'bg-red-600' }
const WORD = { good: 'OK', warn: 'Watch', bad: 'Problem' }

/** Why the system decided this: a plain-language headline, each factor rated, and the predicted yield. */
export default function Explanation({ explanation: e }) {
  if (!e) return null
  const yf = e.yield_forecast
  const rows = yf.rounds.map((r) => ({ day: `day ${r.day}`, 'No action': r.no_action, 'With the plan': r.with_plan }))
  const changed = yf.rounds.some((r) => r.with_plan !== r.no_action)

  return (
    <div className="card">
      <div className="card-title">What the AI predicts and why</div>
      <p className="rounded-lg bg-tea-50 px-4 py-3 text-base text-tea-900">{e.headline}</p>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-2 text-sm font-medium text-stone-700">The factors behind the decision</div>
          <ul className="space-y-2">
            {e.factors.map((f) => (
              <li key={f.key} className="rounded-lg border border-stone-200 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-sm font-medium text-stone-800">
                    <span className={`h-2.5 w-2.5 rounded-full ${DOT[f.status]}`} />
                    {f.label}
                  </span>
                  <span className="text-sm font-semibold text-stone-900">
                    {f.value} <span className="text-xs font-normal text-stone-400">· {WORD[f.status]}</span>
                  </span>
                </div>
                <p className="mt-1 text-sm text-stone-600">{f.text}</p>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <div className="mb-2 text-sm font-medium text-stone-700">
            Predicted green leaf, next {rows.length} plucking rounds (kg/ha/day)
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} domain={['auto', 'auto']} />
                <Tooltip />
                <Legend />
                <Line dataKey="No action" stroke="#78716c" strokeDasharray="5 4" dot={false} />
                <Line dataKey="With the plan" stroke="#2f7d45" strokeWidth={2} dot />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-sm text-stone-600">
            {changed
              ? `The plan adds about ${Math.round(yf.gain_kg_ha)} kg green leaf per ha over the period (+${yf.gain_pct}%).`
              : 'No fertilizer is planned, so both lines are the same: the yield the block is expected to give anyway.'}{' '}
            Predicted by the CatBoost yield model (explains 91 % of yield variation on 2025, 80 % on unseen blocks);
            later rounds reuse today's conditions, so read the difference between the lines, not the exact values.
          </p>
        </div>
      </div>
    </div>
  )
}
