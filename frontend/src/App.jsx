import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import StatusBar from './components/StatusBar'
import BlockInfo from './components/BlockInfo'
import RecommendationCard from './components/RecommendationCard'
import ForecastChart from './components/ForecastChart'
import ReadingForm from './components/ReadingForm'
import History from './components/History'
import DemoScenarios from './components/DemoScenarios'
import Explanation from './components/Explanation'
import BestTimePlanner from './components/BestTimePlanner'

export default function App() {
  const [status, setStatus] = useState(null)
  const [estates, setEstates] = useState([])
  const [estateId, setEstateId] = useState('E03')
  const [blocks, setBlocks] = useState([])
  const [blockId, setBlockId] = useState('E03-B07')
  const [rec, setRec] = useState(null)
  const [readings, setReadings] = useState([])
  const [history, setHistory] = useState([])
  const [done, setDone] = useState([])           // actions the user marked as done on this block
  const [forecast, setForecast] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('recommendation')
  const [prefill, setPrefill] = useState(null)   // a demo scenario waiting in the reading form

  const block = blocks.find((b) => b.block_id === blockId)

  const loadStatus = () => api.status().then(setStatus).catch((e) => setError(e.message))
  useEffect(() => {
    loadStatus()
    api.estates().then(setEstates).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    api.blocks(estateId).then((bs) => {
      setBlocks(bs)
      if (!bs.some((b) => b.block_id === blockId)) setBlockId(bs[0]?.block_id)
    })
    setForecast(null)
    api.forecast(estateId).then((f) => setForecast(f.data)).catch((e) => setError(e.message))
  }, [estateId])

  const loadBlock = useCallback(() => {
    if (!blockId) return
    api.latest(blockId).then(setRec).catch(() => setRec(null))
    api.readings(blockId).then(setReadings).catch(() => setReadings([]))
    api.history(blockId).then(setHistory).catch(() => setHistory([]))
    api.actionsDone(blockId).then(setDone).catch(() => setDone([]))
  }, [blockId])
  useEffect(() => {
    setError('')
    loadBlock()
  }, [loadBlock])

  async function submitReading(reading, whatIf) {
    setBusy(true)
    setError('')
    try {
      const out = await api.addReading(reading, whatIf)
      setPrefill(null)
      if (out.recommendation_error) setError(`Reading saved, but: ${out.recommendation_error}`)
      loadBlock()
      loadStatus()
      setTab('recommendation')
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function rerun(minAe, whatIf) {
    setBusy(true)
    setError('')
    try {
      setRec(await api.rerun(blockId, minAe, whatIf))
      api.history(blockId).then(setHistory)
      loadStatus()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  // "Mark as done": record the action, then re-run on the same weather so the advice reflects it
  async function markDone(action) {
    setBusy(true)
    setError('')
    try {
      await api.markDone(blockId, action)
      setDone(await api.actionsDone(blockId))
      setRec(await api.rerun(blockId, null, rec?.result?.what_if))
      api.history(blockId).then(setHistory)
      loadStatus()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function undoDone(id) {
    setBusy(true)
    try {
      await api.undoDone(id)
      setDone(await api.actionsDone(blockId))
      setRec(await api.rerun(blockId, null, rec?.result?.what_if))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  // History tab: delete one item (id) or the whole list (id = null) of recommendations or readings
  async function deleteHistory(kind, id) {
    const what = kind === 'recommendation' ? 'recommendation' : 'sensor reading'
    const ask = id ? `Delete this ${what}?` : `Delete ALL ${what}s of block ${blockId}?`
    if (!window.confirm(`${ask} This cannot be undone.`)) return
    setBusy(true)
    setError('')
    try {
      if (kind === 'recommendation') {
        await (id ? api.deleteRecommendation(id) : api.clearRecommendations(blockId))
      } else {
        await (id ? api.deleteReading(id) : api.clearReadings(blockId))
      }
      loadBlock()
      loadStatus()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  // a demo scenario was loaded: its block is already cleared; open the reading form with the values filled in
  function demoLoad(s) {
    setEstateId(s.block_id.slice(0, 3))
    setBlockId(s.block_id)
    setRec(null)
    setReadings([])
    setHistory([])
    setDone([])
    setPrefill({ ...s, loadedAt: Date.now() })
    loadStatus()
    setTab('reading')
  }

  const tabs = [
    ['demo', 'Demo scenarios'],
    ['recommendation', 'Recommendation'],
    ['reading', 'Enter reading (IoT)'],
    ['forecast', 'Weather forecast'],
    ['history', 'History'],
  ]

  return (
    <div className="min-h-screen">
      <header className="bg-tea-900 text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-4">
          <div>
            <h1 className="text-xl font-semibold">SmartTea-LK · Resource Optimization</h1>
            <p className="text-sm text-tea-100">
              Component 04: what to do next, how much, and when (fertilizer · irrigation · fungicide · dolomite)
            </p>
          </div>
          <StatusBar status={status} />
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl gap-5 px-4 py-5 lg:grid-cols-[260px_1fr]">
        <aside className="space-y-4">
          <div className="card">
            <div className="card-title">Estate</div>
            <select className="input" value={estateId} onChange={(e) => setEstateId(e.target.value)}>
              {estates.map((e) => (
                <option key={e.estate_id} value={e.estate_id}>
                  {e.estate_id} · {e.region} ({e.agro_zone})
                </option>
              ))}
            </select>
            <div className="card-title mt-4">Block</div>
            <div className="grid grid-cols-2 gap-1.5">
              {blocks.map((b) => (
                <button
                  key={b.block_id}
                  onClick={() => setBlockId(b.block_id)}
                  className={`rounded-md border px-2 py-1.5 text-sm ${
                    b.block_id === blockId
                      ? 'border-tea-600 bg-tea-600 text-white'
                      : 'border-stone-200 bg-white hover:bg-tea-50'
                  }`}
                >
                  {b.block_id}
                </button>
              ))}
            </div>
          </div>
          {block && <BlockInfo block={block} />}
        </aside>

        <section className="min-w-0 space-y-4">
          <nav className="flex flex-wrap gap-1 border-b border-stone-200">
            {tabs.map(([key, label]) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
                  tab === key ? 'border-tea-600 text-tea-700' : 'border-transparent text-stone-500 hover:text-stone-800'
                }`}
              >
                {label}
              </button>
            ))}
          </nav>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
          )}

          {tab === 'demo' && <DemoScenarios onLoad={demoLoad} busy={busy} setBusy={setBusy} setError={setError} />}
          {tab === 'recommendation' && (
            <>
              <RecommendationCard rec={rec} busy={busy} onRerun={rerun} onMarkDone={markDone} onEnter={() => setTab('reading')} />
              {rec && <Explanation explanation={rec.result.explanation} />}
              {rec && <BestTimePlanner tier3={rec.result.tier3} actions={rec.result.actions} whatIf={rec.result.what_if} />}
            </>
          )}
          {tab === 'reading' && block && (
            <ReadingForm block={block} lastReading={readings[0]} prefill={prefill} busy={busy} onSubmit={submitReading} />
          )}
          {tab === 'forecast' && (
            <ForecastChart forecast={forecast} scan={rec?.result?.tier3?.fertilizer_scan} region={block?.region} />
          )}
          {tab === 'history' && (
            <History readings={readings} history={history} done={done} onUndo={undoDone} onDelete={deleteHistory} busy={busy} />
          )}
        </section>
      </main>
    </div>
  )
}
