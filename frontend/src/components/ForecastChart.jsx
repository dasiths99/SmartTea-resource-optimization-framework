import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

/** Next 96 h of the live Open-Meteo forecast (hourly rain + rain probability), plus the last 7 days of rain. */
export default function ForecastChart({ forecast, scan, region }) {
  if (!forecast) return <div className="card text-stone-500">Loading forecast…</div>
  const h = forecast.hourly
  const now = new Date()
  const safe = new Set((scan || []).filter((s) => s.ok).map((s) => s.time.slice(0, 13).replace(' ', 'T')))
  const rows = h.time
    .map((t, i) => ({
      t,
      label: t.slice(5, 13).replace('T', ' ') + 'h',
      rain: h.precipitation[i],
      prob: h.precipitation_probability[i],
      wind: h.wind_speed_10m[i],
      safe: safe.has(t.slice(0, 13)) ? 1 : 0,
    }))
    .filter((r) => new Date(r.t) >= new Date(now.getTime() - 3600e3))
    .slice(0, 96)

  const d = forecast.daily
  const today = new Date(now.getTime() - now.getTimezoneOffset() * 60e3).toISOString().slice(0, 10)
  const idx = d.time.indexOf(today)
  const days = d.time.map((t, i) => ({ t, rain: d.precipitation_sum[i], temp: d.temperature_2m_mean[i] }))
  const past = idx > 0 ? days.slice(Math.max(0, idx - 7), idx) : []
  const next = idx >= 0 ? days.slice(idx) : []

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-title">Hourly forecast · {region} · next 96 h</div>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" />
              <XAxis dataKey="label" interval={11} tick={{ fontSize: 11 }} />
              <YAxis yAxisId="mm" tick={{ fontSize: 11 }} label={{ value: 'mm', angle: -90, position: 'insideLeft' }} />
              <YAxis yAxisId="pct" orientation="right" domain={[0, 100]} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Bar yAxisId="mm" dataKey="rain" name="Rain (mm/h)" fill="#0284c7" />
              <Line yAxisId="pct" dataKey="prob" name="Rain probability (%)" stroke="#d97706" dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-xs text-stone-400">
          Source: Open-Meteo forecast API (free, no key), refreshed hourly by the backend. Fertilizer needs ≤ 5 mm and ≤ 30 %
          rain probability in the 12 h after application.
          {scan?.length ? ` Safe fertilizer hours found: ${safe.size} of ${scan.length}.` : ''}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {[['Last 7 days (observed)', past], ['Today and next days (forecast)', next]].map(([title, list]) => (
          <div key={title} className="card">
            <div className="card-title">{title}</div>
            <table className="w-full text-sm">
              <thead className="text-left text-stone-500">
                <tr>
                  <th className="py-1">Date</th>
                  <th>Rain</th>
                  <th>Mean temp</th>
                </tr>
              </thead>
              <tbody>
                {list.map((x) => (
                  <tr key={x.t} className="border-t border-stone-100">
                    <td className="py-1">{x.t}</td>
                    <td>{x.rain} mm</td>
                    <td>{x.temp} °C</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  )
}
