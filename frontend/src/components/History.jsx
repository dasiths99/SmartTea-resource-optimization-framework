const fmt = (t) => (t ? new Date(t).toLocaleString() : '—')

const DONE_LABEL = { fertilizer: 'Fertilizer', irrigation: 'Irrigation', dolomite: 'Dolomite', fungicide: 'Fungicide' }

// card title with a "Delete all" button on the right (shown only when the list has rows)
function Header({ title, count, onClearAll, busy }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <div className="text-sm font-semibold uppercase tracking-wide text-stone-500">{title}</div>
      {count > 0 && (
        <button className="btn-danger" disabled={busy} onClick={onClearAll}>
          Delete all ({count})
        </button>
      )}
    </div>
  )
}

export default function History({ readings, history, done = [], onUndo, onDelete, busy }) {
  return (
    <div className="space-y-4">
      <div className="card overflow-x-auto">
        <div className="card-title">Actions marked as done</div>
        {done.length === 0 ? (
          <p className="text-sm text-stone-500">
            None yet. Press <b>Mark as done</b> on a recommendation after the work is carried out; the system then
            follows the minimum gaps between repeats.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-stone-500">
              <tr>
                <th className="py-1">Date</th>
                <th>Action</th>
                <th>Amount</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {done.map((d) => (
                <tr key={d.id} className="border-t border-stone-100">
                  <td className="py-1.5 whitespace-nowrap">{d.date}</td>
                  <td className="font-medium">{DONE_LABEL[d.type] ?? d.type}</td>
                  <td>
                    {d.amount ? `${d.amount} ${d.unit ?? ''}` : '—'} {d.product ? `(${d.product})` : ''}
                  </td>
                  <td className="text-right">
                    <button className="btn-ghost" disabled={busy} onClick={() => onUndo(d.id)}>
                      Undo
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card overflow-x-auto">
        <Header
          title="Recommendations (latest first)"
          count={history.length}
          busy={busy}
          onClearAll={() => onDelete('recommendation', null)}
        />
        {history.length === 0 ? (
          <p className="text-sm text-stone-500">None yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-stone-500">
              <tr>
                <th className="py-1">Time</th>
                <th>Trigger</th>
                <th>Action</th>
                <th>Amount</th>
                <th>Window</th>
                <th>Yield Δ</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id} className="border-t border-stone-100 align-top">
                  <td className="py-1.5 whitespace-nowrap">{fmt(h.created_at)}</td>
                  <td>{h.trigger.replace('_', ' ')}</td>
                  <td className="font-medium">{h.result.actions.map((a) => a.action).join(' + ')}</td>
                  <td>{h.result.amount_kg_per_ha ? `${h.result.amount_kg_per_ha} kg/ha` : '—'}</td>
                  <td className="whitespace-nowrap">{h.result.window || '—'}</td>
                  <td>{h.result.predicted_yield_change_pct} %</td>
                  <td className="text-right">
                    <button className="btn-danger" disabled={busy} onClick={() => onDelete('recommendation', h.id)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card overflow-x-auto">
        <Header
          title="Sensor readings (latest first)"
          count={readings.length}
          busy={busy}
          onClearAll={() => onDelete('reading', null)}
        />
        {readings.length === 0 ? (
          <p className="text-sm text-stone-500">None yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-stone-500">
              <tr>
                <th className="py-1">Time</th>
                <th>Moisture %</th>
                <th>pH</th>
                <th>N</th>
                <th>P</th>
                <th>K</th>
                <th>Soil °C</th>
                <th>Lux</th>
                <th>Sun h</th>
                <th>Last fertilizer</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {readings.map((r) => (
                <tr key={r.id} className="border-t border-stone-100">
                  <td className="py-1.5 whitespace-nowrap">{fmt(r.timestamp)}</td>
                  <td>{r.soil_moisture_pct}</td>
                  <td>{r.soil_ph}</td>
                  <td>{r.soil_n_ppm}</td>
                  <td>{r.soil_p_ppm}</td>
                  <td>{r.soil_k_ppm}</td>
                  <td>{r.soil_temp_c}</td>
                  <td>{r.light_lux ?? '—'}</td>
                  <td>{r.sunshine_hours ?? '—'}</td>
                  <td className="whitespace-nowrap">
                    {r.last_fertilizer
                      ? `${r.last_fertilizer.product_code} ${r.last_fertilizer.amount_kg_per_ha} kg/ha, ${r.last_fertilizer.date}`
                      : '—'}
                  </td>
                  <td className="text-right">
                    <button className="btn-danger" disabled={busy} onClick={() => onDelete('reading', r.id)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
