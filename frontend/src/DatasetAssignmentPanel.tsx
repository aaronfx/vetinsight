import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { DatasetAssignment, DatasetSplit } from './api'

const labels: Record<DatasetSplit, string> = { unassigned: 'Unassigned', train: 'Training', validation: 'Validation', test: 'Test' }

export default function DatasetAssignmentPanel({ caseId, disabled = false }: { caseId: number; disabled?: boolean }) {
  const [saved, setSaved] = useState<DatasetAssignment | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [conflict, setConflict] = useState(false)
  const [reload, setReload] = useState(0)
  const saving = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void api.datasetAssignment(caseId, controller.signal).then(value => {
      if (!controller.signal.aborted) { setSaved(value); setConflict(false); setError('') }
    }).catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
    return () => { controller.abort(); saving.current?.abort() }
  }, [caseId, reload])

  async function assign(split: DatasetSplit) {
    if (!saved || busy || conflict || disabled) return
    const controller = new AbortController()
    saving.current = controller
    setBusy(true); setError(''); setMessage('')
    try {
      const result = await api.saveDatasetAssignment(caseId, { split, revision: saved.revision }, controller.signal)
      if (!controller.signal.aborted) { setSaved(result); setMessage(`Saved case split: ${labels[result.split]}.`) }
    } catch (err) {
      if (!controller.signal.aborted) {
        setError((err as Error).message)
        // Retain the confirmed assignment until the user reloads a conflicting change.
        setConflict((err as Error).message.includes('another session'))
      }
    } finally { if (!controller.signal.aborted) setBusy(false) }
  }

  return <section className="dataset-assignment">
    <h2>Dataset split</h2>
    <p>Assign this whole case to one split. All current and future images in this case inherit it. Changes save immediately.</p>
    <label>Case dataset split<select value={saved?.split ?? 'unassigned'} disabled={!saved || busy || disabled || conflict}
      onChange={event => void assign(event.target.value as DatasetSplit)}>
      {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select></label>
    <p role="status">{busy ? 'Saving case split…' : message || (saved ? `Saved split: ${labels[saved.split]} · revision ${saved.revision}` : error ? 'Assignment unavailable.' : 'Loading case split…')}</p>
    {disabled && <p>Save or reload your annotations before changing the case split.</p>}
    {saved?.updated_at && <small>Last saved {new Date(saved.updated_at).toLocaleString()}</small>}
    {error && <p className="error" role="alert">{error}</p>}
    {(error || conflict) && <button className="secondary" disabled={busy} onClick={() => { setSaved(null); setError(''); setMessage(''); setReload(value => value + 1) }}>Reload saved split</button>}
    <p className="canvas-help">Training fits a model; validation guides development; test measures the final model. This does not train a model. Synthetic test images are for interface checks. Related patients or duplicate images in other cases still need to be grouped together.</p>
  </section>
}
