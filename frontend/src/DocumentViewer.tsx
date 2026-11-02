import { useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { api, downloadUrl } from './api'
import { sessionFetch } from './session'
import type { DocumentText, UploadInfo } from './api'

GlobalWorkerOptions.workerSrc = workerUrl

function PdfPage({ pdf, page, zoom }: { pdf: PDFDocumentProxy; page: number; zoom: number }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [state, setState] = useState('Loading page…')
  useEffect(() => {
    let active = true
    let render: RenderTask | undefined
    async function draw() {
      try {
        const documentPage = await pdf.getPage(page)
        if (!active || !canvas.current) return
        const viewport = documentPage.getViewport({ scale: zoom })
        const ratio = Math.min(window.devicePixelRatio || 1, 2)
        const target = canvas.current
        target.width = Math.ceil(viewport.width * ratio)
        target.height = Math.ceil(viewport.height * ratio)
        target.style.width = `${viewport.width}px`
        target.style.height = `${viewport.height}px`
        render = documentPage.render({ canvas: target, viewport, transform: [ratio, 0, 0, ratio, 0, 0] })
        await render.promise
        if (active) setState('')
      } catch (err) {
        if (active) setState(`Unable to render this page. Preview may be unsupported. ${(err as Error).message}`)
      }
    }
    void draw()
    return () => { active = false; render?.cancel() }
  }, [pdf, page, zoom])
  return <>{state && <p role="status">{state}</p>}
    <canvas ref={canvas} aria-label={`PDF page ${page}; extracted text is available beside the document`} hidden={!!state} /></>
}

export default function DocumentViewer({ file, onClose }: { file: UploadInfo; onClose: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null)
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [imageUrl, setImageUrl] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [text, setText] = useState<DocumentText | null>(null)
  const [textError, setTextError] = useState('')
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(1)
  const isPdf = file.content_type === 'application/pdf'
  const isImage = ['image/jpeg', 'image/png'].includes(file.content_type)

  useEffect(() => {
    heading.current?.focus()
    const controller = new AbortController()
    let active = true
    let objectUrl = ''
    let task: ReturnType<typeof getDocument> | undefined
    if (!isPdf && !isImage) return () => controller.abort()
    async function load() {
      try {
        const response = await sessionFetch(downloadUrl(file.preview_url), { signal: controller.signal })
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          throw new Error(response.status === 404 ? 'File missing. The uploaded file could not be found.' : body?.detail || `Preview failed (${response.status}).`)
        }
        if (response.headers.get('content-type')?.split(';')[0] !== file.content_type) {
          throw new Error('Unsupported preview: the delivered file type does not match this document.')
        }
        if (isPdf) {
          const data = new Uint8Array(await response.arrayBuffer())
          if (!active) return
          // Render pixels only: document scripts, attachments and links are never executed.
          task = getDocument({ data })
          const loaded = await task.promise
          if (active) { setPdf(loaded); setLoading(false) }
        } else {
          const blob = await response.blob()
          if (!active) return
          objectUrl = URL.createObjectURL(blob)
          setImageUrl(objectUrl)
        }
      } catch (err) {
        if (active) {
          setError((err as Error).name === 'PasswordException'
            ? 'Unsupported preview: this PDF requires a password. Use Download.'
            : `Preview unavailable. ${(err as Error).message} You can try Download.`)
          setLoading(false)
        }
      }
    }
    void load()
    if (isPdf) {
      api.documentText(file.text_url, controller.signal).then(result => { if (active) setText(result) })
        .catch(err => { if (active) setTextError(err.message) })
    }
    return () => {
      active = false
      controller.abort()
      void task?.destroy()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [file, isPdf, isImage])

  return <section className="document-viewer" aria-labelledby="document-heading">
    <div className="viewer-heading"><h2 id="document-heading" ref={heading} tabIndex={-1}>{file.filename}</h2>
      <a href={downloadUrl(file.download_url)}>Download</a><button onClick={onClose}>Close viewer</button></div>
    {!isPdf && !isImage ? <p role="status">Unsupported preview for this file type. Use Download.</p> : <>
      <div className="viewer-controls" aria-label="Document controls">
        {isPdf && <><button disabled={!pdf || page === 1} onClick={() => setPage(page - 1)}>Previous page</button>
          <span>Page {page} of {pdf?.numPages ?? '…'}</span>
          <button disabled={!pdf || page === pdf.numPages} onClick={() => setPage(page + 1)}>Next page</button></>}
        <button aria-label="Zoom out" disabled={zoom <= 0.5 || loading || !!error} onClick={() => setZoom(value => Math.max(0.5, value - 0.25))}>−</button>
        <span aria-live="polite">{Math.round(zoom * 100)}%</span>
        <button aria-label="Zoom in" disabled={zoom >= 2 || loading || !!error} onClick={() => setZoom(value => Math.min(2, value + 0.25))}>+</button>
      </div>
      <div className={isPdf ? 'document-columns' : ''}>
        <div className="document-surface" aria-busy={loading}>
          {loading && <p role="status">Loading document…</p>}
          {error && <p role="alert">{error}</p>}
          {pdf && <PdfPage key={`${page}-${zoom}`} pdf={pdf} page={page} zoom={zoom} />}
          {imageUrl && <img src={imageUrl} alt={file.filename} style={{ width: `${zoom * 100}%`, maxWidth: 'none' }}
            onLoad={() => setLoading(false)} onError={() => { setLoading(false); setError('Unsupported image preview: the image cannot be decoded. Use Download.') }} hidden={!!error} />}
        </div>
        {isPdf && <aside className="document-text" aria-labelledby="text-heading"><h3 id="text-heading">Document text</h3>
          <p>Embedded text extracted locally, by page. Case details are unchanged.</p>
          {textError ? <p role="alert">Text extraction unavailable: {textError}</p> : !text ? <p role="status">Extracting document text…</p> : <>
            {text.status === 'ocr_required' && <p role="status">OCR required — no embedded text was found.</p>}
            {text.status === 'partial' && <p>Some pages have no embedded text. OCR required for those pages.</p>}
            {text.pages.map(item => <div key={item.page_number} className="text-page" aria-current={item.page_number === page ? 'page' : undefined}>
              <h4>Page {item.page_number}</h4>{item.status === 'ocr_required' ? <p>OCR required — no embedded text on this page.</p> : <pre>{item.text}</pre>}
            </div>)}
          </>}
        </aside>}
      </div>
    </>}
  </section>
}
