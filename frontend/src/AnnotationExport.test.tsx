import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AnnotationExport from './AnnotationExport'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('Case annotation export', () => {
  it('downloads the selected case ZIP and waits for the response', async () => {
    let resolve!: (response: Response) => void
    const fetch = vi.fn<typeof globalThis.fetch>(() => new Promise<Response>(done => { resolve = done }))
    vi.stubGlobal('fetch', fetch)
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:zip'), revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe('vetinsight-case-7-coco.zip')
      expect(this.href).toBe('blob:zip')
    })
    render(<AnnotationExport caseId={7} disabled={false} />)
    fireEvent.click(screen.getByRole('button', { name: 'Download case COCO ZIP' }))
    expect(screen.getByRole('button', { name: 'Preparing export…' })).toHaveProperty('disabled', true)
    expect(fetch.mock.calls[0][0]).toContain('/cases/7/exports/coco')
    resolve(new Response('zip', { headers: { 'Content-Type': 'application/zip' } }))
    await screen.findByRole('status')
    expect(click).toHaveBeenCalledOnce()
    expect(screen.getByRole('button')).toHaveProperty('disabled', false)
  })

  it('prevents exporting drafts and displays backend errors', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'No exportable images.' }), { status: 422 }))
    vi.stubGlobal('fetch', fetch)
    const view = render(<AnnotationExport caseId={1} disabled />)
    fireEvent.click(screen.getByRole('button'))
    expect(fetch).not.toHaveBeenCalled()
    view.rerender(<AnnotationExport caseId={1} disabled={false} />)
    fireEvent.click(screen.getByRole('button'))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'No exportable images.')
    await waitFor(() => expect(screen.getByRole('button')).toHaveProperty('disabled', false))
  })
})
