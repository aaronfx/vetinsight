import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import DocumentViewer from './DocumentViewer'
import type { UploadInfo } from './api'

const mocks = vi.hoisted(() => ({
  getPage: vi.fn(),
  destroy: vi.fn(),
  text: vi.fn(),
  getDocument: vi.fn(),
}))
vi.mock('pdfjs-dist', () => ({ GlobalWorkerOptions: {}, getDocument: mocks.getDocument }))
vi.mock('./api', () => ({
  downloadUrl: (path: string) => `http://localhost:8000${path}`,
  api: { documentText: mocks.text },
}))

const file: UploadInfo = { id: 1, filename: 'fictional.pdf', content_type: 'application/pdf', size_bytes: 100,
  preview_url: '/cases/1/uploads/1/preview', download_url: '/cases/1/uploads/1', text_url: '/cases/1/uploads/1/text' }

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getPage.mockResolvedValue({ getViewport: ({ scale }: { scale: number }) => ({ width: 300 * scale, height: 400 * scale }),
    render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }) })
  mocks.getDocument.mockReturnValue({ promise: Promise.resolve({ numPages: 2, getPage: mocks.getPage }), destroy: mocks.destroy })
  mocks.text.mockResolvedValue({ status: 'extracted', page_count: 2, pages: [
    { page_number: 1, text: 'Fictional Cooper record', status: 'extracted' },
    { page_number: 2, text: 'Second page text', status: 'extracted' },
  ] })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new Uint8Array([1, 2, 3]), { headers: { 'Content-Type': 'application/pdf' } })))
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:local-image'), revokeObjectURL: vi.fn() })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Document viewer', () => {
  it('renders PDF pages, navigates, zooms and retains a separate download', async () => {
    render(<DocumentViewer file={file} onClose={vi.fn()} />)
    await screen.findByText('Page 1 of 2')
    expect((screen.getByRole('button', { name: 'Previous page' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByRole('link', { name: 'Download' }).getAttribute('href')).toBe('http://localhost:8000/cases/1/uploads/1')
    expect(screen.getByText('Fictional Cooper record')).toBeTruthy()
    expect(screen.getByText('Second page text')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
    await screen.findByText('Page 2 of 2')
    await waitFor(() => expect(mocks.getPage).toHaveBeenCalledWith(2))
    expect((screen.getByRole('button', { name: 'Next page' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(screen.getByText('125%')).toBeTruthy()
    await waitFor(() => expect(document.querySelector('canvas')?.style.width).toBe('375px'))
    fireEvent.click(screen.getByRole('button', { name: 'Previous page' }))
    await screen.findByText('Page 1 of 2')
  })

  it('shows loading and missing-file states', async () => {
    let resolveFetch!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { resolveFetch = resolve })))
    render(<DocumentViewer file={file} onClose={vi.fn()} />)
    expect(screen.getByText('Loading document…')).toBeTruthy()
    resolveFetch(new Response(JSON.stringify({ detail: 'missing' }), { status: 404 }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('File missing'))
  })

  it('shows OCR required per page rather than empty successful text', async () => {
    mocks.text.mockResolvedValue({ status: 'ocr_required', page_count: 2, pages: [
      { page_number: 1, text: '', status: 'ocr_required' }, { page_number: 2, text: '', status: 'ocr_required' },
    ] })
    render(<DocumentViewer file={file} onClose={vi.fn()} />)
    expect(await screen.findByText('OCR required — no embedded text was found.')).toBeTruthy()
    expect(screen.getAllByText('OCR required — no embedded text on this page.')).toHaveLength(2)
  })

  it('shows unsupported preview and text extraction errors independently', async () => {
    mocks.getDocument.mockReturnValue({ promise: Promise.reject(new Error('Damaged PDF')), destroy: mocks.destroy })
    mocks.text.mockRejectedValue(new Error('PDF may be damaged or unsupported.'))
    render(<DocumentViewer file={file} onClose={vi.fn()} />)
    await screen.findByText(/Preview unavailable.*Damaged PDF/)
    expect(await screen.findByText(/Text extraction unavailable/)).toBeTruthy()
  })

  it('rejects unsupported content types without attempting rendering', () => {
    render(<DocumentViewer file={{ ...file, content_type: 'text/html' }} onClose={vi.fn()} />)
    expect(screen.getByText('Unsupported preview for this file type. Use Download.')).toBeTruthy()
    expect(fetch).not.toHaveBeenCalled()
  })

  it.each(['image/png', 'image/jpeg'])('loads %s images and releases local blob URLs', async content_type => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('image', { headers: { 'Content-Type': content_type } })))
    const view = render(<DocumentViewer file={{ ...file, filename: 'scan', content_type }} onClose={vi.fn()} />)
    const image = await screen.findByRole('img', { name: 'scan' })
    fireEvent.load(image)
    expect(screen.queryByText('Loading document…')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(image.style.width).toBe('125%')
    expect(mocks.text).not.toHaveBeenCalled()
    view.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:local-image')
  })

  it('reports image decoding errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('broken image', { headers: { 'Content-Type': 'image/png' } })))
    render(<DocumentViewer file={{ ...file, filename: 'scan', content_type: 'image/png' }} onClose={vi.fn()} />)
    fireEvent.error(await screen.findByRole('img', { name: 'scan' }))
    expect(screen.getByRole('alert').textContent).toContain('image cannot be decoded')
  })
})
