import { lazy, Suspense, useState } from 'react'
import type { FormEvent } from 'react'
import { api, downloadUrl } from './api'
import type { CaseDetail, UploadInfo } from './api'
import DatasetAssignmentPanel from './DatasetAssignmentPanel'
const DocumentViewer = lazy(() => import('./DocumentViewer'))

export default function CaseOverview({ detail, tab, navigate, onUpdated }: {
  detail: CaseDetail; tab: string; navigate: (route: string) => void; onUpdated: (detail: CaseDetail) => void
}) {
  const [preview, setPreview] = useState<UploadInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')
  const documents = detail.uploads.filter(file => file.content_type === 'application/pdf')
  const images = detail.uploads.filter(file => ['image/jpeg', 'image/png'].includes(file.content_type))
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const files = new FormData(form).getAll('files').filter((item): item is File => item instanceof File && !!item.name)
    if (!files.length) { setError('Choose at least one non-empty file.'); return }
    if (files.some(file => file.size === 0)) { setError('Attachments must not be empty.'); return }
    if (files.some(file => file.size > 20 * 1024 * 1024)) { setError('Files must be 20 MiB or smaller.'); return }
    setBusy(true); setError('')
    try {
      for (const [index, file] of files.entries()) { setProgress(`Uploading ${index + 1} of ${files.length}…`); await api.upload(detail.id, file) }
      form.reset()
    } catch (err) { setError((err as Error).message) }
    finally {
      try { onUpdated(await api.viewCase(detail.id)) } catch (err) { setError((err as Error).message) }
      setBusy(false); setProgress('')
    }
  }
  return <>
    <div className="overview-grid">
      <div>
        {tab !== 'records' && <section><div className="panel-title"><h2>Case summary</h2><span className="badge">Recorded details</span></div>
          <h3>Clinical history & notes</h3><p className="notes">{detail.notes || 'No clinical notes recorded.'}</p>
          <dl className="metadata"><div><dt>Patient</dt><dd>{detail.patient_name}</dd></div><div><dt>Species</dt><dd>{detail.species}</dd></div>
            <div><dt>Case ID</dt><dd>CASE-{String(detail.id).padStart(4, '0')}</dd></div><div><dt>Created</dt><dd>{new Date(detail.created_at).toLocaleString()}</dd></div></dl>
        </section>}
        <section><div className="panel-title"><h2>Clinical records</h2><span className="badge">{documents.length} PDFs</span></div>
          {documents.length === 0 ? <p className="empty">No PDF records attached.</p> : <ul className="record-list">{documents.map(file => <li key={file.id}>
            <div><strong>{file.filename}</strong><small>{Math.ceil(file.size_bytes / 1024)} KiB · PDF</small></div>
            <button className="secondary" onClick={() => setPreview(file)}>View</button><a href={downloadUrl(file.download_url)}>Download</a></li>)}</ul>}
        </section>
        {tab !== 'records' && <section><div className="panel-title"><h2>Cytology images</h2><span className="badge blue">{images.length} images</span></div>
          {images.length === 0 ? <p className="empty">No cytology images attached. Upload a JPG or PNG to start manual review.</p> : <div className="image-grid">{images.map(file => <article key={file.id} className="image-card">
            <img src={downloadUrl(file.preview_url)} alt={file.filename} loading="lazy" />
            <strong>{file.filename}</strong><small>{Math.ceil(file.size_bytes / 1024)} KiB · {file.content_type === 'image/png' ? 'PNG' : 'JPG'}</small>
            <div className="inline-actions"><button onClick={() => navigate(`cases/${detail.id}/cytology/${file.id}`)}>Annotate</button>
              <button className="secondary" onClick={() => setPreview(file)}>View</button><a href={downloadUrl(file.download_url)}>Download</a></div></article>)}</div>}
        </section>}
      </div>
      <aside><section><h2>Workspaces</h2><button className="workspace-link" onClick={() => navigate(`cases/${detail.id}/records`)}>Clinical record viewer <span>→</span></button>
        <button className="workspace-link secondary" onClick={() => navigate(`cases/${detail.id}/cytology`)}>Manual cytology workspace <span>→</span></button></section>
        <DatasetAssignmentPanel key={detail.id} caseId={detail.id} />
        <section><h2>Add attachments</h2><form onSubmit={upload}><label>PDF, JPG or PNG · max 20 MiB<input name="files" type="file" multiple required accept=".pdf,.jpg,.jpeg,.png" disabled={busy} /></label>
          <button disabled={busy}>{busy ? progress : 'Upload attachments'}</button></form>{error && <p role="alert" className="error">{error}</p>}</section>
        <section className="workflow-note"><h3>One case, connected records</h3><p>Clinical documents and image annotations stay linked to case #{detail.id}. Cell categories and review states are entered manually.</p></section>
      </aside>
    </div>
    {preview && <Suspense fallback={<p role="status">Loading document viewer…</p>}><DocumentViewer key={preview.id} file={preview} onClose={() => setPreview(null)} /></Suspense>}
  </>
}
