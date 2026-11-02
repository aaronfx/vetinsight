import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { api, downloadUrl } from './api'
import { sessionFetch } from './session'
import type { Annotation, AnnotationSet, CaseDetail, ReviewStatus, UploadInfo } from './api'
import { boundingBox, fitScale, imagePoint } from './geometry'
import type { Point } from './geometry'
import AnnotationExport from './AnnotationExport'
import DatasetAssignmentPanel from './DatasetAssignmentPanel'

const categories = ['Unclassified', 'Needs Review', 'Neutrophil', 'Lymphocyte', 'Eosinophil', 'Macrophage', 'Mast cell', 'Epithelial cell', 'Erythrocyte', 'Debris', 'Other']
const statuses: ReviewStatus[] = ['Needs Review', 'In Progress', 'Reviewed']

export default function CytologyWorkspace({ detail, initialImageId, onDirty, onSaved, onUpload, onSelectImage }: {
  detail: CaseDetail; initialImageId?: number; onDirty: (dirty: boolean) => void; onSaved: () => void;
  onUpload: () => void; onSelectImage: (id: number) => void
}) {
  const images = detail.uploads.filter(file => ['image/jpeg', 'image/png'].includes(file.content_type))
  const file = initialImageId ? images.find(item => item.id === initialImageId) : images[0]
  if (!images.length) return <section className="empty"><h2>No cytology images yet</h2><p>Attach a JPG or PNG to this case to begin manual annotation.</p><button onClick={onUpload}>Add an image to this case</button></section>
  return <><section className="cytology-intro"><div><span className="badge blue">Manual annotation</span><p>Draw image regions and record your observations. No automatic cell detections are generated.</p></div>
    <label>Case image<select value={file?.id || ''} onChange={event => onSelectImage(Number(event.target.value))}>
      {!file && <option value="">Select an image</option>}{images.map(item => <option key={item.id} value={item.id}>{item.filename}</option>)}</select></label></section>
    {file ? <ImageReview key={file.id} caseId={detail.id} file={file} onDirty={onDirty} onSaved={onSaved} /> : <p role="alert" className="error">This image is not linked to this case. Select an attached image.</p>}
  </>
}

function ImageReview({ caseId, file, onDirty, onSaved }: { caseId: number; file: UploadInfo; onDirty: (dirty: boolean) => void; onSaved: () => void }) {
  const [data, setData] = useState<AnnotationSet | null>(null)
  const [imageUrl, setImageUrl] = useState('')
  const [imageReady, setImageReady] = useState(false)
  const [annotations, setAnnotations] = useState<Annotation[]>([])
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus>('Needs Review')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saveMessage, setSaveMessage] = useState('')
  const [reload, setReload] = useState(0)
  const [tool, setTool] = useState<'pan' | 'draw' | 'select'>('draw')
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState<Point>({ x: 0, y: 0 })
  const [viewportSize, setViewportSize] = useState({ width: 600, height: 480 })
  const [draft, setDraft] = useState<ReturnType<typeof boundingBox> | null>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const plane = useRef<HTMLDivElement>(null)
  const gesture = useRef<{ pointerId: number; kind: 'pan' | 'draw'; start: Point; imageStart: Point; pan: Point } | null>(null)
  const selected = annotations.find(item => item.id === selectedId)
  const scale = data ? fitScale(viewportSize.width, viewportSize.height, data.image_width, data.image_height) * zoom : 1

  useEffect(() => { onDirty(dirty); return () => onDirty(false) }, [dirty, onDirty])
  useEffect(() => {
    const controller = new AbortController()
    let objectUrl = ''
    async function load() {
      try {
        const [saved, response] = await Promise.all([api.annotations(caseId, file.id, controller.signal), sessionFetch(downloadUrl(file.preview_url), { signal: controller.signal })])
        if (!response.ok) throw new Error(response.status === 404 ? 'Image file is missing from storage.' : `Image preview failed (${response.status}).`)
        const blob = await response.blob()
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setData(saved); setAnnotations(saved.annotations); setReviewStatus(saved.review_status); setImageUrl(objectUrl)
      } catch (err) { if (!controller.signal.aborted) setError((err as Error).message) }
    }
    void load()
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [caseId, file.id, file.preview_url, reload])
  useEffect(() => {
    if (!viewport.current) return
    const observer = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      if (width > 0 && height > 0) setViewportSize({ width, height })
    })
    observer.observe(viewport.current)
    return () => observer.disconnect()
  }, [])

  function changed(next: Annotation[]) {
    setAnnotations(next); setDirty(true); setSaveMessage('')
    if (reviewStatus === 'Reviewed') setReviewStatus('In Progress')
  }
  function updateSelected(patch: Partial<Annotation>) {
    changed(annotations.map(item => item.id === selectedId ? { ...item, ...patch,
      review_status: patch.review_status ?? 'Needs Review' } : item))
  }
  function point(event: ReactPointerEvent): Point {
    return imagePoint({ x: event.clientX, y: event.clientY }, plane.current!.getBoundingClientRect())
  }
  function start(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !imageReady || !data || saving || !plane.current || gesture.current) return
    if (tool === 'select') { setSelectedId(null); return }
    const bounds = plane.current.getBoundingClientRect()
    if (tool === 'draw' && (event.clientX < bounds.left || event.clientY < bounds.top || event.clientX > bounds.right || event.clientY > bounds.bottom)) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    const imageStart = point(event)
    gesture.current = { pointerId: event.pointerId, kind: tool, start: { x: event.clientX, y: event.clientY }, imageStart, pan }
    if (tool === 'draw') setDraft(boundingBox(imageStart, imageStart))
  }
  function move(event: ReactPointerEvent<HTMLDivElement>) {
    const active = gesture.current
    if (!active || active.pointerId !== event.pointerId) return
    if (active.kind === 'pan') setPan({ x: active.pan.x + event.clientX - active.start.x, y: active.pan.y + event.clientY - active.start.y })
    else setDraft(boundingBox(active.imageStart, point(event)))
  }
  function end(event: ReactPointerEvent<HTMLDivElement>) {
    const active = gesture.current
    if (!active || active.pointerId !== event.pointerId) return
    if (active.kind === 'draw' && data) {
      const box = boundingBox(active.imageStart, point(event))
      if (box.width * data.image_width >= 2 && box.height * data.image_height >= 2) {
        const annotation: Annotation = { ...box, id: crypto.randomUUID(), category: 'Unclassified', review_status: 'Needs Review', notes: '' }
        changed([...annotations, annotation]); setSelectedId(annotation.id)
      }
    }
    gesture.current = null; setDraft(null)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }
  async function save() {
    if (!data) return
    if (annotations.some(item => !item.category.trim())) { setError('Enter a category for every annotation, or use Unclassified.'); return }
    setSaving(true); setError(''); setSaveMessage('')
    try {
      const saved = await api.saveAnnotations(caseId, file.id, { revision: data.revision, review_status: reviewStatus, annotations })
      setData(saved); setAnnotations(saved.annotations); setReviewStatus(saved.review_status); setDirty(false)
      setSaveMessage('Annotations saved.'); onSaved()
    } catch (err) { setError((err as Error).message) }
    finally { setSaving(false) }
  }
  function reloadSaved() {
    if (dirty && !window.confirm('Discard unsaved annotations and reload the saved review?')) return
    setDirty(false); setError(''); setData(null); setAnnotations([]); setImageUrl(''); setImageReady(false); setSelectedId(null); setSaveMessage(''); setReload(value => value + 1)
  }

  return <>
    <div className="cytology-grid">
      <section className="image-workspace"><div className="panel-title"><div><h2>{file.filename}</h2><small>{data ? `${data.image_width} × ${data.image_height} pixels` : 'Loading image metadata…'}</small></div><span className="badge">Manual only</span></div>
        <div className="image-toolbar"><div className="tool-group">{(['draw', 'pan', 'select'] as const).map(item => <button key={item} className={tool === item ? 'active' : 'secondary'} disabled={!imageReady || saving}
          aria-pressed={tool === item} onClick={() => { gesture.current = null; setDraft(null); setTool(item) }}>{item === 'draw' ? 'Draw box' : item === 'pan' ? 'Pan image' : 'Select box'}</button>)}</div>
          <div className="tool-group"><button className="secondary" aria-label="Zoom out" disabled={!imageReady || zoom <= 0.5} onClick={() => setZoom(value => Math.max(0.5, value - 0.25))}>−</button>
            <span aria-live="polite">{Math.round(zoom * 100)}% fit</span><button className="secondary" aria-label="Zoom in" disabled={!imageReady || zoom >= 5} onClick={() => setZoom(value => Math.min(5, value + 0.25))}>+</button>
            <button className="secondary" disabled={!imageReady} onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }) }}>Fit image</button></div></div>
        <div className={`annotation-viewport tool-${tool}`} ref={viewport} onPointerDown={start} onPointerMove={move} onPointerUp={end}
          onPointerCancel={() => { gesture.current = null; setDraft(null) }} aria-label="Cytology image annotation canvas" data-testid="annotation-viewport">
          {!imageReady && <p className="canvas-message" role="status">{error ? 'Image workspace unavailable. See the error below.' : 'Loading image…'}</p>}
          {data && imageUrl && <div ref={plane} className="image-plane" data-testid="image-plane" style={{ width: data.image_width * scale, height: data.image_height * scale,
            left: (viewportSize.width - data.image_width * scale) / 2 + pan.x, top: (viewportSize.height - data.image_height * scale) / 2 + pan.y, visibility: imageReady ? 'visible' : 'hidden' }}>
            <img src={imageUrl} alt={`Cytology image ${file.filename}`} draggable={false} onLoad={event => {
              if (event.currentTarget.naturalWidth !== data.image_width || event.currentTarget.naturalHeight !== data.image_height) setError('Image dimensions do not match the saved coordinate space. Annotation is disabled.')
              else setImageReady(true)
            }} onError={() => setError('This image cannot be displayed. Upload a valid JPG or PNG.')} />
            <svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-label="Manual bounding boxes">{annotations.map((item, index) => <g key={item.id}>
              <rect x={item.x} y={item.y} width={item.width} height={item.height} className={`annotation-box ${selectedId === item.id ? 'selected' : ''} ${item.review_status === 'Reviewed' ? 'reviewed' : ''}`}
                style={{ pointerEvents: tool === 'select' ? 'auto' : 'none' }} vectorEffect="non-scaling-stroke" role="button" tabIndex={0}
                aria-label={`Select annotation ${index + 1}: ${item.category}`} onPointerDown={event => { if (tool === 'select') { event.stopPropagation(); setSelectedId(item.id) } }}
                onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedId(item.id) } }} />
              <text x={item.x} y={Math.max(0.02, item.y - 0.008)} fontSize="0.018" fill="white" stroke="#003644" strokeWidth="0.001" paintOrder="stroke" pointerEvents="none">#{index + 1}</text>
            </g>)}{draft && <rect {...draft} vectorEffect="non-scaling-stroke" className="annotation-box draft" />}</svg>
          </div>}
        </div><p className="canvas-help">Draw: drag over the image to add a box. Pan: drag to move the image. Select: click a box or choose it from the list. Coordinates are stored relative to the original image.</p>
      </section>
      <aside className="cell-inspector"><section><div className="panel-title"><h2>Annotation inspector</h2><span className="badge blue">{annotations.length} regions</span></div>
        {selected && data ? <fieldset disabled={saving}><label>Cell category<input value={selected.category} maxLength={80} list="cell-categories" onChange={event => updateSelected({ category: event.target.value })} /></label>
          <small>Choose a suggestion or enter your own category.</small>
          <datalist id="cell-categories">{[...new Set([...categories, ...annotations.map(item => item.category)])].map(category => <option key={category}>{category}</option>)}</datalist>
          <label>Annotation review status<select value={selected.review_status} onChange={event => updateSelected({ review_status: event.target.value as ReviewStatus })}>{statuses.map(status => <option key={status}>{status}</option>)}</select></label>
          <label>Reviewer observation<textarea rows={4} maxLength={2000} value={selected.notes} onChange={event => updateSelected({ notes: event.target.value })} /></label>
          <dl className="coordinate-readout"><div><dt>X / Y (image px)</dt><dd>{(selected.x * data.image_width).toFixed(1)} / {(selected.y * data.image_height).toFixed(1)}</dd></div>
            <div><dt>Width / height (px)</dt><dd>{(selected.width * data.image_width).toFixed(1)} / {(selected.height * data.image_height).toFixed(1)}</dd></div></dl>
          <button className="danger secondary" onClick={() => { changed(annotations.filter(item => item.id !== selectedId)); setSelectedId(null) }}>Remove selected box</button></fieldset> : <p className="empty">Draw or select a box to edit its category and review status.</p>}
      </section><section><h2>Manual regions</h2>{annotations.length ? <ol className="annotation-list">{annotations.map((item, index) => <li key={item.id}><button className={selectedId === item.id ? 'active' : 'secondary'} onClick={() => setSelectedId(item.id)}>
        <strong>#{index + 1} · {item.category || 'Unclassified'}</strong><small>{item.review_status}</small></button></li>)}</ol> : <p>No annotations yet.</p>}
        <div className="category-summary">{[...new Set(annotations.map(item => item.category || 'Unclassified'))].map(category => <span className="badge" key={category}>{category}: {annotations.filter(item => (item.category || 'Unclassified') === category).length}</span>)}</div>
      </section></aside>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    <section className="annotation-save"><label>Image review status<select disabled={!data || saving} value={reviewStatus} onChange={event => { setReviewStatus(event.target.value as ReviewStatus); setDirty(true); setSaveMessage('') }}>
      {statuses.map(status => <option key={status} disabled={status === 'Reviewed' && annotations.some(item => item.review_status !== 'Reviewed')}>{status}</option>)}</select></label>
      <div><strong className={dirty ? 'unsaved' : ''} role="status">{dirty ? 'Unsaved changes' : saveMessage || (data?.revision ? `Saved revision ${data.revision}` : 'No saved annotations yet')}</strong>
        {data?.updated_at && <small>Last saved {new Date(data.updated_at).toLocaleString()}</small>}</div>
      <button className="secondary" disabled={saving} onClick={reloadSaved}>Reload saved</button>
      <button disabled={!data || !imageReady || saving || !dirty} onClick={save}>{saving ? 'Saving…' : 'Save annotations'}</button>
    </section>
    <DatasetAssignmentPanel key={caseId} caseId={caseId} disabled={dirty || saving || !data} />
    <AnnotationExport caseId={caseId} disabled={dirty || saving || !data} />
  </>
}
