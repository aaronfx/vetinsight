import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DatasetAssignmentPanel from './DatasetAssignmentPanel'

const mocks = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn() }))
vi.mock('./api', () => ({ api: { datasetAssignment: mocks.get, saveDatasetAssignment: mocks.save } }))
const initial = { case_id: 3, split: 'unassigned', revision: 0, updated_at: null }
beforeEach(() => { vi.resetAllMocks(); mocks.get.mockResolvedValue(initial) })
afterEach(cleanup)

describe('Case dataset split', () => {
  it('saves case-scoped changes immediately and restores the saved assignment on reopening', async () => {
    const updated = { ...initial, split: 'train', revision: 1, updated_at: '2026-10-07T00:00:00Z' }
    mocks.save.mockResolvedValue(updated)
    const view = render(<DatasetAssignmentPanel caseId={3} />)
    await waitFor(() => expect(screen.getByLabelText('Case dataset split')).toHaveProperty('disabled', false))
    fireEvent.change(screen.getByLabelText('Case dataset split'), { target: { value: 'train' } })
    await screen.findByText('Saved case split: Training.')
    expect(mocks.save).toHaveBeenCalledWith(3, { split: 'train', revision: 0 }, expect.any(AbortSignal))
    view.unmount(); mocks.get.mockResolvedValue(updated)
    render(<DatasetAssignmentPanel caseId={3} />)
    await waitFor(() => expect(screen.getByLabelText('Case dataset split')).toHaveProperty('value', 'train'))
  })

  it('retains the confirmed split after failed saves and reloads a conflict explicitly', async () => {
    mocks.get.mockResolvedValue({ ...initial, split: 'validation', revision: 2 })
    mocks.save.mockRejectedValue(new Error('Dataset assignment changed in another session. Reload the saved assignment before changing it.'))
    render(<DatasetAssignmentPanel caseId={3} />)
    await waitFor(() => expect(screen.getByLabelText('Case dataset split')).toHaveProperty('value', 'validation'))
    fireEvent.change(screen.getByLabelText('Case dataset split'), { target: { value: 'test' } })
    await screen.findByRole('alert')
    expect(screen.getByLabelText('Case dataset split')).toHaveProperty('value', 'validation')
    expect(screen.getByLabelText('Case dataset split')).toHaveProperty('disabled', true)
    mocks.get.mockResolvedValue({ ...initial, split: 'train', revision: 3 })
    fireEvent.click(screen.getByRole('button', { name: 'Reload saved split' }))
    await waitFor(() => expect(screen.getByLabelText('Case dataset split')).toHaveProperty('value', 'train'))
    expect(screen.getByLabelText('Case dataset split')).toHaveProperty('disabled', false)
  })

  it('disables changes when annotations are unsaved and permits retry after loading fails', async () => {
    mocks.get.mockRejectedValueOnce(new Error('Cannot reach the backend.'))
    render(<DatasetAssignmentPanel caseId={3} disabled />)
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: 'Reload saved split' }))
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2))
    expect(screen.getByLabelText('Case dataset split')).toHaveProperty('disabled', true)
    expect(screen.getByText('Save or reload your annotations before changing the case split.')).toBeTruthy()
  })
})
