// All calls go to the Spring Boot public API (proxied by Vite to http://localhost:8080).
async function call(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`)
  return body
}

export const api = {
  status: () => call('/status'),
  estates: () => call('/estates'),
  blocks: (estateId) => call(`/blocks?estateId=${estateId}`),
  readings: (blockId) => call(`/readings?blockId=${blockId}&limit=20`),
  // whatIf ('dry' | 'wet') is a query parameter only: the reading JSON itself is the IoT format and never changes
  addReading: (reading, whatIf) =>
    call(`/readings${whatIf && whatIf !== 'live' ? `?whatIf=${whatIf}` : ''}`, {
      method: 'POST',
      body: JSON.stringify(reading),
    }),
  actionsDone: (blockId) => call(`/blocks/${blockId}/actions-done`),
  markDone: (blockId, body) => call(`/blocks/${blockId}/actions-done`, { method: 'POST', body: JSON.stringify(body) }),
  undoDone: (id) => call(`/actions-done/${id}`, { method: 'DELETE' }),
  clearBlock: (blockId) => call(`/blocks/${blockId}/data`, { method: 'DELETE' }),
  latest: (blockId) => call(`/blocks/${blockId}/recommendation`),
  rerun: (blockId, minAe, whatIf) => {
    const q = new URLSearchParams()
    if (minAe) q.set('minAe', minAe)
    if (whatIf && whatIf !== 'live') q.set('whatIf', whatIf)
    return call(`/blocks/${blockId}/recommendation?${q}`, { method: 'POST' })
  },
  history: (blockId) => call(`/blocks/${blockId}/recommendations?limit=20`),
  forecast: (estateId) => call(`/forecast/${estateId}`),
  demoScenarios: () => call('/demo/scenarios'),
}
