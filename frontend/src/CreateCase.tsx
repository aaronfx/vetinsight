import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from './api'

export default function CreateCase({ onCreated, navigate }: { onCreated: (id: number, warning?: string) => void; navigate: (route: string) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const files = data.getAll('files').filter((item): item is File => item instanceof File && !!item.name)
    if (files.some(file => file.size === 0)) { setError('Attachments must not be empty.'); return }
    if (files.some(file => file.size > 20 * 1024 * 1024)) { setError('Each attachment must be 20 MiB or smaller.'); return }
    setBusy(true); setError(''); setProgress('Creating case…')
    let id: number | undefined
    try {
      const created = await api.createCase({ patient_name: String(data.get('patient_name')), species: String(data.get('species')), notes: String(data.get('notes')) })
      id = created.id
      for (const [index, file] of files.entries()) {
        setProgress(`Uploading attachment ${index + 1} of ${files.length}…`)
        await api.upload(id, file)
      }
      onCreated(id)
    } catch (err) {
      if (id !== undefined) onCreated(id, `Case created. An attachment could not be uploaded: ${(err as Error).message} Retry from this case.`)
      else setError((err as Error).message)
    } finally { setBusy(false); setProgress('') }
  }
  return <form className="create-form" onSubmit={submit}>
    {error && <p className="error" role="alert">{error}</p>}
    <fieldset disabled={busy}><section><div className="panel-title"><h2>Patient & case information</h2><span className="badge">Manual entry</span></div>
      <p className="muted">Record the details you know. Document uploads do not populate patient fields.</p>
      <div className="form-grid"><label>Patient name <span aria-hidden="true">*</span><input name="patient_name" required maxLength={120} placeholder="Enter patient name" /></label>
        <label>Species <span aria-hidden="true">*</span><input name="species" required maxLength={80} placeholder="e.g. Canine" list="species-options" /></label></div>
      <datalist id="species-options"><option>Canine</option><option>Feline</option><option>Equine</option><option>Avian</option></datalist>
      <label>Clinical history & notes<textarea name="notes" maxLength={10000} rows={6} placeholder="Enter the history and observations recorded for this case" /></label>
    </section>
    <section><h2>Attach clinical records & cytology images</h2><p className="muted">PDF, JPG or PNG · up to 20 MiB per file. You can also attach files after creating the case.</p>
      <label className="upload-drop">Choose attachments<input name="files" type="file" multiple accept=".pdf,.jpg,.jpeg,.png" /></label></section></fieldset>
    <div className="action-bar"><p role="status">{progress || 'Case information and attachments will be saved to local storage.'}</p>
      <button type="button" disabled={busy} className="secondary" onClick={() => navigate('dashboard')}>Cancel</button><button disabled={busy}>Create case</button></div>
  </form>
}
