import { useEffect, useRef, useState } from 'react'
import { downloadUrl } from './api'
import { sessionFetch } from './session'

export default function AnnotationExport({ caseId, disabled }: { caseId: number; disabled: boolean }) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [caseId])

  async function download() {
    controller.current?.abort()
    const active = new AbortController()
    controller.current = active
    setBusy(true); setError(''); setMessage('')
    try {
      const response = await sessionFetch(downloadUrl(`/cases/${caseId}/exports/coco`), { signal: active.signal })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(typeof body?.detail === 'string' ? body.detail : `Export failed (${response.status}).`)
      }
      const blob = await response.blob()
      if (active.signal.aborted) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = `vetinsight-case-${caseId}-coco.zip`
      document.body.append(link); link.click(); link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setMessage('Export prepared; download requested. Check manifest.json for included and skipped images.')
    } catch (err) {
      if (!active.signal.aborted) setError(err instanceof Error ? err.message : 'Export failed. Check the backend connection.')
    } finally { if (!active.signal.aborted) setBusy(false) }
  }

  return <section className="annotation-export">
    <div><h2>Export reviewed annotations</h2><p>Export this case as a COCO ZIP with image copies, pixel boxes and a source manifest. Only saved, fully Reviewed images with classified boxes are included. Empty images, Unclassified and Needs Review categories are excluded.</p>
      {disabled && <p>Save or reload your changes before exporting.</p>}</div>
    <button className="secondary" disabled={disabled || busy} onClick={() => void download()}>{busy ? 'Preparing export…' : 'Download case COCO ZIP'}</button>
    {message && <p role="status">{message}</p>}{error && <p role="alert" className="error">{error}</p>}
  </section>
}
