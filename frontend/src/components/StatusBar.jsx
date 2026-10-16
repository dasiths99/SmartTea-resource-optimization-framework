function Pill({ ok, children }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
        ok ? 'bg-tea-100 text-tea-900' : 'bg-red-100 text-red-800'
      }`}
    >
      <span className={`h-2 w-2 rounded-full ${ok ? 'bg-tea-600' : 'bg-red-600'}`} />
      {children}
    </span>
  )
}

/** Live status of the three back-end parts: MongoDB, the ML service and its two models. */
export default function StatusBar({ status }) {
  if (!status) return <Pill ok={false}>Backend not reachable</Pill>
  const db = status.database
  const ml = status.ml_service
  const mlOk = ml?.status === 'ok'
  const y = ml?.models?.yield
  const r = ml?.models?.runoff
  return (
    <div className="flex flex-wrap gap-2">
      <Pill ok>
        MongoDB · {db.blocks} blocks · {db.readings} readings · {db.recommendations} recs
      </Pill>
      <Pill ok={mlOk}>ML service {mlOk ? 'online' : 'down'}</Pill>
      {mlOk && (
        <>
          <Pill ok>
            Yield {y.model}: R² {y.scores.test_r2.toFixed(2)} (unseen {y.scores.unseen_future_r2.toFixed(2)})
          </Pill>
          <Pill ok>
            Runoff {r.model}: R² {r.scores.test_r2.toFixed(2)} (unseen {r.scores.unseen_future_r2.toFixed(2)})
          </Pill>
        </>
      )}
    </div>
  )
}
