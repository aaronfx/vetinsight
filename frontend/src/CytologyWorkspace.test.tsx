import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CytologyWorkspace from './CytologyWorkspace'
import type { AnnotationSet, CaseDetail } from './api'

const mocks = vi.hoisted(() => ({ annotations: vi.fn(), save: vi.fn() }))
vi.mock('./api', () => ({ api: { annotations: mocks.annotations, saveAnnotations: mocks.save,
  datasetAssignment: () => Promise.resolve({ case_id: 1, split: 'unassigned', revision: 0, updated_at: null }) }, downloadUrl: (value: string) => value }))
const detail: CaseDetail = { id: 1, patient_name: 'Coordinate test', species: 'Test', notes: '', created_at: '', upload_count: 1, image_count: 1,
  uploads: [{ id: 4, filename: 'geometry.png', content_type: 'image/png', size_bytes: 100, download_url: '/download', preview_url: '/preview', text_url: '/text' }] }
let saved: AnnotationSet
let resize: ResizeObserverCallback
class TestPointerEvent extends MouseEvent {
  pointerId: number
  constructor(type: string, options: PointerEventInit) { super(type, options); this.pointerId = options.pointerId ?? 1 }
}

beforeEach(() => {
  vi.clearAllMocks()
  saved = { case_id: 1, upload_id: 4, image_width: 1000, image_height: 500, revision: 0, review_status: 'Needs Review', annotations: [], updated_at: null }
  mocks.annotations.mockImplementation(() => Promise.resolve(saved))
  mocks.save.mockImplementation((_caseId, _uploadId, payload) => { saved = { ...saved, ...payload, revision: saved.revision + 1, updated_at: '2026-10-06T12:00:00Z' }; return Promise.resolve(saved) })
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: ResizeObserverCallback) { resize = callback }
    observe() {} disconnect() {}
  })
  vi.stubGlobal('PointerEvent', TestPointerEvent)
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response('image', { headers: { 'Content-Type': 'image/png' } }))))
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:test-image'), revokeObjectURL: vi.fn() })
  HTMLElement.prototype.setPointerCapture = vi.fn()
  HTMLElement.prototype.releasePointerCapture = vi.fn()
  HTMLElement.prototype.hasPointerCapture = vi.fn(() => true)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

async function mount() {
  const onDirty = vi.fn()
  const view = render(<CytologyWorkspace detail={detail} onDirty={onDirty} onSaved={vi.fn()} onUpload={vi.fn()} onSelectImage={vi.fn()} />)
  const image = await screen.findByAltText('Cytology image geometry.png')
  Object.defineProperties(image, { naturalWidth: { value: 1000 }, naturalHeight: { value: 500 } })
  fireEvent.load(image)
  const plane = screen.getByTestId('image-plane')
  vi.spyOn(plane, 'getBoundingClientRect').mockImplementation(() => {
    const left = 30 + parseFloat(plane.style.left), top = 60 + parseFloat(plane.style.top)
    const width = parseFloat(plane.style.width), height = parseFloat(plane.style.height)
    return { x: left, y: top, left, top, width, height, right: left + width, bottom: top + height, toJSON: () => ({}) }
  })
  return { ...view, onDirty, plane, viewport: screen.getByTestId('annotation-viewport') }
}
function draw(view: { plane: HTMLElement; viewport: HTMLElement }) {
  const bounds = view.plane.getBoundingClientRect()
  fireEvent.pointerDown(view.viewport, { clientX: bounds.left + bounds.width * .1, clientY: bounds.top + bounds.height * .2, button: 0, pointerId: 1 })
  fireEvent.pointerMove(view.viewport, { clientX: bounds.left + bounds.width * .4, clientY: bounds.top + bounds.height * .6, pointerId: 1 })
  fireEvent.pointerUp(view.viewport, { clientX: bounds.left + bounds.width * .4, clientY: bounds.top + bounds.height * .6, pointerId: 1 })
}

describe('Manual cytology review', () => {
  it('draws original-image coordinates, preserves them across zoom/pan/resize, and reloads saved annotations', async () => {
    const view = await mount()
    draw(view)
    expect(screen.getByLabelText('Cell category')).toHaveProperty('value', 'Unclassified')
    expect(screen.getByLabelText('Annotation review status')).toHaveProperty('value', 'Needs Review')
    const rect = () => view.plane.querySelector('rect')!
    const before = ['x', 'y', 'width', 'height'].map(key => rect().getAttribute(key))
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    fireEvent.click(screen.getByRole('button', { name: 'Pan image' }))
    fireEvent.pointerDown(view.viewport, { clientX: 300, clientY: 250, button: 0, pointerId: 2 })
    fireEvent.pointerMove(view.viewport, { clientX: 340, clientY: 230, pointerId: 2 })
    fireEvent.pointerUp(view.viewport, { clientX: 340, clientY: 230, pointerId: 2 })
    act(() => resize([{ contentRect: { width: 360, height: 420 } } as ResizeObserverEntry], {} as ResizeObserver))
    expect(['x', 'y', 'width', 'height'].map(key => rect().getAttribute(key))).toEqual(before)
    fireEvent.change(screen.getByLabelText('Cell category'), { target: { value: 'Reviewer category' } })
    fireEvent.change(screen.getByLabelText('Annotation review status'), { target: { value: 'Reviewed' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save annotations' }))
    await screen.findByText('Annotations saved.')
    expect(saved.annotations[0].category).toBe('Reviewer category')
    expect(saved.annotations[0].x).toBeCloseTo(.1); expect(saved.annotations[0].y).toBeCloseTo(.2)
    expect(saved.annotations[0].width).toBeCloseTo(.3); expect(saved.annotations[0].height).toBeCloseTo(.4)
    view.unmount()
    const reopened = await mount()
    expect(reopened.plane.querySelectorAll('rect')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: /#1 · Reviewer category/ }))
    expect(screen.getByLabelText('Cell category')).toHaveProperty('value', 'Reviewer category')
    expect(screen.getByText('100.0 / 100.0')).toBeTruthy()
  })

  it('retains unsaved edits when saving fails and allows explicit reload', async () => {
    const view = await mount()
    draw(view)
    mocks.save.mockRejectedValue(new Error('Annotations changed in another session. Reload saved annotations.'))
    fireEvent.click(screen.getByRole('button', { name: 'Save annotations' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('another session'))
    expect(screen.getByText('Unsaved changes')).toBeTruthy()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'Reload saved' }))
    await waitFor(() => expect(mocks.annotations).toHaveBeenCalledTimes(2))
    expect(view.plane.isConnected).toBe(false)
    expect(screen.getByText('No annotations yet.')).toBeTruthy()
  })

  it('requires an attached image and displays loading errors without invented regions', async () => {
    const empty = render(<CytologyWorkspace detail={{ ...detail, uploads: [] }} onDirty={vi.fn()} onSaved={vi.fn()} onUpload={vi.fn()} onSelectImage={vi.fn()} />)
    expect(screen.getByText('No cytology images yet')).toBeTruthy()
    empty.unmount()
    mocks.annotations.mockRejectedValue(new Error('Image file is missing from storage.'))
    render(<CytologyWorkspace detail={detail} onDirty={vi.fn()} onSaved={vi.fn()} onUpload={vi.fn()} onSelectImage={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Image file is missing from storage.')
    expect(screen.getByText('No annotations yet.')).toBeTruthy()
  })
})
