import { useEffect, useState } from 'react'
import { downloadUrl } from './api'
import type { Annotation } from './api'
import { sessionFetch } from './session'

interface Nucleus { cx: number; cy: number; x: number; y: number; width: number; height: number; nc_ratio: number | null }
interface Candidate extends Pick<Annotation, 'id' | 'x' | 'y' | 'width' | 'height' | 'category'> { score: number; nucleus?: Nucleus }
interface Run {
  id: string; task: string; status: string; error: string; created_at: string
  result: { candidates?: Candidate[]; limitation?: string; nucleus_note?: string; model_id?: string; image_width: number; image_height: number }
}
function nucleusText(item: Candidate) {
  if (!item.nucleus) return 'no nucleus marked'
  return item.nucleus.nc_ratio === null ? 'nucleus marked · N:C unavailable' : `nucleus marked · N:C ${item.nucleus.nc_ratio.toFixed(2)}`
}
type Availability = Record<string, { available: boolean; limitation: string }>

async function json<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await sessionFetch(downloadUrl(path), options)
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail || 'Analysis request failed.')
  return body
}

export default function AnalysisPanel({ caseId, uploadId, imageUrl, disabled, onImport }: {
  caseId: number; uploadId: number; imageUrl: string; disabled: boolean
  onImport: (items: Annotation[]) => void
}) {
  const [models, setModels] = useState<Availability | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [task, setTask] = useState('cytology')
  const [acknowledged, setAcknowledged] = useState(false)
  const [threshold, setThreshold] = useState(0.5)
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const path = `/cases/${caseId}/uploads/${uploadId}/analysis`
  const active = runs.some(run => ['queued', 'running'].includes(run.status))
  useEffect(() => {
    let alive = true
    async function refresh() {
      try {
        const [availability, history] = await Promise.all([json<Availability>('/analysis/models'), json<Run[]>(path)])
        if (alive) { setModels(availability); setRuns(history) }
      } catch (err) { if (alive) setError((err as Error).message) }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 3000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [path])
  const run = runs.find(item => item.id === selected) || runs[0]
  const candidates = (run?.result.candidates || []).filter(item => item.score >= threshold)
  async function start() {
    setBusy(true); setError(''); setMessage('')
    try {
      const next = await json<Run>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task, request_id: crypto.randomUUID(), acknowledge_experimental: true }) })
      setRuns(items => [next, ...items.filter(item => item.id !== next.id)]); setSelected(next.id)
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }
  function adopt(item: Candidate) {
    onImport([{ ...item, id: crypto.randomUUID(), review_status: 'Needs Review',
      notes: `Model suggestion from run ${run.id}, candidate ${item.id}, score ${item.score.toFixed(6)}. ${nucleusText(item)}. Requires human review.` }])
    setMessage('Suggestion added to manual regions. Review, correct and save annotations below.')
  }
  return <section className="analysis-panel">
    <h2>Automatic image analysis</h2>
    <p>Choose the specimen type. Model suggestions require your review before you save them as annotations.</p>
    <label>Analysis type<select value={task} onChange={event => { setTask(event.target.value); setAcknowledged(false) }}>
      <option value="cytology">Cytology · experimental cell detector and Bethesda-class labeller</option>
      <option value="histology">Histology · experimental mitosis detector</option>
    </select></label>
    <p>{models ? models[task].limitation : 'Checking model availability…'}</p>
    <p>{task === 'cytology'
      ? 'Supports JPG/PNG fields up to 16 megapixels. Native image scale, stain and preparation matter. Labels are suggestions for review, never diagnoses. A low candidate count does not establish absence of disease.'
      : 'Supports JPG/PNG regions up to 25 tiles of 448 × 448 pixels. Native image scale matters. A low candidate count does not establish absence of disease.'}</p>
    <label><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} /> I understand this is experimental and requires qualified review.</label>
    <button disabled={disabled || busy || active || !acknowledged || !models?.[task].available} onClick={() => void start()}>{busy || active ? 'Analysis running…' : 'Run analysis'}</button>
    {error && <p role="alert" className="error">{error}</p>}
    {!!runs.length && <label>Saved analysis run<select value={run?.id || ''} onChange={event => setSelected(event.target.value)}>{runs.map(item => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString()} · {item.status}</option>)}</select></label>}
    {run && <p role="status">{run.status}{run.error ? ` · ${run.error}` : ''}</p>}
    {run?.status === 'completed' && <>
      <p>{run.result.model_id} · {run.result.limitation}</p>
      {run.result.nucleus_note && <p>{run.result.nucleus_note}</p>}
      <label>Candidate score threshold · {threshold.toFixed(2)}<input type="range" min="0.01" max="1" step="0.01" value={threshold} onChange={event => setThreshold(Number(event.target.value))} /></label>
      <p>{candidates.length} candidates visible. Purple boxes are automatic suggestions. Scores are uncalibrated.</p>
      <div className="research-image"><img src={imageUrl} alt={`Image with automatic ${run.task} suggestions`} />
        <svg viewBox={`0 0 ${run.result.image_width} ${run.result.image_height}`} aria-label="Automatic model suggestions">{candidates.map(item => <g key={item.id}>
          <rect className="research-prediction" x={item.x * run.result.image_width} y={item.y * run.result.image_height} width={item.width * run.result.image_width} height={item.height * run.result.image_height} />
          {item.nucleus && <ellipse className="research-nucleus" cx={item.nucleus.cx * run.result.image_width} cy={item.nucleus.cy * run.result.image_height}
            rx={item.nucleus.width * run.result.image_width / 2} ry={item.nucleus.height * run.result.image_height / 2} />}
          {run.task === 'cytology' && <text className="research-prediction-label" x={item.x * run.result.image_width + 3} y={Math.max(item.y * run.result.image_height - 4, run.result.image_width / 50)} fontSize={run.result.image_width / 50}>{item.category} {item.score.toFixed(2)}</text>}
        </g>)}</svg>
      </div>
      <p>Inspect each candidate, then add those you want to review. Omitted candidates remain in the saved analysis run.</p>
      <div className="analysis-candidates">{candidates.map((item, index) => <div key={item.id}><span>#{index + 1} {item.category} · score {item.score.toFixed(3)}{run.task === 'cytology' ? ` · ${nucleusText(item)}` : ''} · X {Math.round(item.x * run.result.image_width)}, Y {Math.round(item.y * run.result.image_height)}</span><button disabled={disabled} onClick={() => adopt(item)}>Add to manual review</button></div>)}</div>
    </>}
    {message && <p role="status">{message}</p>}
  </section>
}
