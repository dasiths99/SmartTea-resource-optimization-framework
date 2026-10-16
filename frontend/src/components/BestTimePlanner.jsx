const ROWS = [
  ['fertilizer', 'Fertilizer', 'needs ≤ 5 mm rain and ≤ 30 % chance in the 12 h after, soil moisture in band'],
  ['spray', 'Fungicide spray', 'needs 4 h without rain and wind ≤ 4 m/s'],
  ['dolomite', 'Dolomite', 'needs under 20 mm rain in the next 24 h'],
  ['irrigation', 'Irrigation', 'only useful when no rain is due in the next 12 h'],
]

const dayName = (d) => new Date(`${d}T00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

/** Tier 3 "best time" planner: for each forecast day, the best hour for each kind of field work, or why not. */
export default function BestTimePlanner({ tier3, actions = [], whatIf }) {
  const days = tier3?.day_plan
  if (!days?.length) return null
  const dose = tier3.fertilizer_scan_dose
  // which activities the recommendation actually calls for now; the others only show when the weather would allow them
  const names = actions.map((a) => a.action)
  const needed = {
    fertilizer: names.some((n) => n.includes('fertilizer')),
    spray: names.some((n) => n.startsWith('Spray')),
    dolomite: names.some((n) => n.includes('dolomite')),
    irrigation: names.some((n) => /rrigat/.test(n)),
  }

  return (
    <div className="card overflow-x-auto">
      <div className="card-title">Best time to work: next {days.length} days</div>
      <p className="mb-3 text-sm text-stone-500">
        From the {whatIf ? <b>what-if</b> : 'live Open-Meteo'} hourly forecast, working hours 06:00–16:00. Green = the
        best hour that day; red = not suitable, with the reason. Grey rows are not needed now: the times show when the
        weather would allow them.
        {dose && !dose.planned && ` Fertilizer timing shown for a typical ${dose.kg_per_ha} kg/ha ${dose.product} (none is planned now).`}
      </p>
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="text-left text-stone-500">
            <th className="py-2 pr-2 font-medium">Activity</th>
            {days.map((d) => (
              <th key={d.date} className="px-2 py-2 font-medium">
                <div className="text-stone-800">{dayName(d.date)}</div>
                <div className="text-xs font-normal">
                  {d.rain_mm} mm · {d.max_rain_prob}% · wind {d.max_wind_ms} m/s
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([key, label, rule]) => (
            <tr key={key} className="border-t border-stone-100 align-top">
              <td className="py-2 pr-2">
                <div className="font-medium text-stone-800">{label}</div>
                <span
                  className={`mt-0.5 inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                    needed[key] ? 'bg-tea-100 text-tea-900' : 'bg-stone-100 text-stone-500'
                  }`}
                >
                  {needed[key] ? 'needed now' : 'not needed now'}
                </span>
                <div className="text-xs text-stone-400">{rule}</div>
              </td>
              {days.map((d) => {
                const c = d[key]
                if (!c) return <td key={d.date} className="px-2 py-2 text-stone-400">—</td>
                return (
                  <td key={d.date} className="px-2 py-2">
                    <div
                      className={`rounded-md px-2 py-1.5 ${
                        !needed[key] ? 'bg-stone-50 text-stone-500' : c.ok ? 'bg-tea-50 text-tea-900' : 'bg-red-50 text-red-800'
                      }`}
                    >
                      <div className="font-semibold">{c.ok ? `✓ ${c.hour}` : '✗ not suitable'}</div>
                      <div className="text-xs">{c.why}</div>
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
