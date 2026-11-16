import { useEffect, useState } from 'react'
import { downloadUrl } from './api'
import { sessionFetch } from './session'

interface Item { value: string | null; quote: string | null; found_in_record: boolean | null; value_in_quote: boolean | null }
interface Lab {
  analyte: string; name_as_written: string; value: number | null; qualifier: string | null; unit: string | null
  range_low: number | null; range_high: number | null; range_unit: string | null; quote: string | null
  found_in_record: boolean; flag: 'low' | 'normal' | 'high' | 'not_judged'; reason: string; caution: string | null
}
interface Run {
  id: string; status: string; error: string; created_at: string; model: string
  result: { fields?: Record<string, Item>; medications?: Item[]; lab_results?: Lab[]; limitation?: string
    summary?: { fields_found: number; not_found_in_record: number; labs_outside_range: number; labs_not_judged: number } }
}
interface Status { available: boolean; reason: string; model: string; limitation: string }

const LABELS: Record<string, string> = {
  patient_name: 'Patient name', species: 'Species', breed: 'Breed', sex: 'Sex', age: 'Age', weight: 'Weight',
  visit_date: 'Visit date', presenting_complaint: 'Presenting complaint', diagnosis_as_written: 'Diagnosis as written in the record',
}
const FLAGS = { low: 'LOW', high: 'HIGH', normal: 'Within printed range', not_judged: 'Not judged' } as const

async function json<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await sessionFetch(downloadUrl(path), options)
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail || 'Extraction request failed.')
  return body
}

function Checks({ item }: { item: Item }) {
  return <>
    <span className="badge">Needs Review</span>
    {item.found_in_record === false && <span className="badge warn">Passage not found in the record</span>}
    {item.found_in_record !== false && item.value_in_quote === false && <span className="badge warn">Value differs from its passage</span>}
  </>
}

export default function ExtractionPanel({ basePath }: { basePath: string }) {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<Status | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [acknowledged, setAcknowledged] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const path = `${basePath}/extraction`
  const active = runs.some(run => ['queued', 'running'].includes(run.status))
  const run = runs[0]

  useEffect(() => {
    if (!open) return
    let alive = true
    async function refresh() {
      try {
        const [availability, history] = await Promise.all([json<Status>('/extraction/status'), json<Run[]>(path)])
        if (alive) { setStatus(availability); setRuns(history) }
      } catch (err) { if (alive) setError((err as Error).message) }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 2500)
    return () => { alive = false; window.clearInterval(timer) }
  }, [open, path])

  async function start() {
    setBusy(true); setError(''); setMessage('')
    try {
      const next = await json<Run>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: crypto.randomUUID(), acknowledge_experimental: true }) })
      setRuns(items => [next, ...items.filter(item => item.id !== next.id)])
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setMessage('Copied. Paste it where you need it; no case field was changed.') }
    catch { setMessage('Copy was blocked by the browser. Select the value and copy it manually.') }
  }

  if (!open) return <button className="secondary" aria-expanded="false" onClick={() => setOpen(true)}>Extract fields (experimental)</button>

  const result = run?.status === 'completed' ? run.result : null
  const fields = Object.entries(result?.fields || {}).filter(([, item]) => item.value !== null)
  return <section className="extraction-panel" aria-label="Extract fields from this record">
    <div className="panel-title"><h4>Extract fields (experimental)</h4><button className="secondary" aria-expanded="true" onClick={() => setOpen(false)}>Hide</button></div>
    <p>{status ? status.limitation : 'Checking availability…'}</p>
    {status && <p><small>Model: {status.model}</small></p>}
    {status && !status.available && <p role="status">Unavailable: {status.reason}</p>}
    <label><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} /> I understand this is experimental and every value must be checked against the record.</label>
    <button disabled={busy || active || !acknowledged || !status?.available} onClick={() => void start()}>{busy || active ? 'Extracting…' : 'Extract fields'}</button>
    {error && <p role="alert" className="error">{error}</p>}
    {run && run.status === 'failed' && <p role="alert" className="error">Extraction failed: {run.error}</p>}
    {message && <p role="status">{message}</p>}
    {result && <>
      <p role="status">{result.summary?.fields_found ?? 0} fields found · {result.summary?.labs_outside_range ?? 0} lab values outside their printed range · {result.summary?.not_found_in_record ?? 0} passages not found in the record.</p>
      {fields.length === 0 ? <p>No case fields were found in this record.</p> : <table className="extraction-table"><thead><tr><th>Field</th><th>Value</th><th>Passage from the record</th><th></th></tr></thead><tbody>
        {fields.map(([name, item]) => <tr key={name}><th scope="row">{LABELS[name] || name}</th><td>{item.value}</td>
          <td><q>{item.quote}</q></td><td><Checks item={item} />{item.value && <button className="secondary" onClick={() => void copy(item.value as string)}>Copy</button>}</td></tr>)}
      </tbody></table>}
      {!!result.medications?.length && <><h5>Medications named in the record</h5><ul>{result.medications.map((item, index) =>
        <li key={index}>{item.value} <q>{item.quote}</q> <Checks item={item} /></li>)}</ul></>}
      {!!result.lab_results?.length && <><h5>Lab results</h5>
        <p><small>Flags compare each value only with the reference range printed in this record, using fixed rules. They are not interpretations.</small></p>
        <table className="extraction-table"><thead><tr><th>Test</th><th>Result</th><th>Printed range</th><th>Flag</th><th>Passage</th></tr></thead><tbody>
          {result.lab_results.map((lab, index) => <tr key={index}><th scope="row">{lab.name_as_written || lab.analyte}</th>
            <td>{lab.qualifier || ''}{lab.value ?? '—'} {lab.unit || ''}</td>
            <td>{lab.range_low ?? '—'} – {lab.range_high ?? '—'} {lab.range_unit || ''}</td>
            <td><strong className={`flag-${lab.flag}`}>{FLAGS[lab.flag]}</strong><br /><small>{lab.reason}</small>{lab.caution && <><br /><small>Sample note: {lab.caution}</small></>}</td>
            <td><q>{lab.quote}</q>{!lab.found_in_record && <span className="badge warn">Not found in the record</span>}</td></tr>)}
        </tbody></table></>}
      <small>Model {run?.model}. Suggestions only; no case field was changed.</small>
    </>}
  </section>
}
