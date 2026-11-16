import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ExtractionPanel from './ExtractionPanel'

vi.mock('./api', () => ({ downloadUrl: (value: string) => value }))
const fetchMock = vi.hoisted(() => vi.fn())
vi.mock('./session', () => ({ sessionFetch: fetchMock }))

const available = { available: true, reason: '', model: 'claude-haiku-5-5', limitation: 'Experimental limitation text.' }
const completed = {
  id: 'run-1', status: 'completed', error: '', created_at: '2026-11-08T10:00:00Z', model: 'claude-haiku-5-5',
  result: {
    summary: { fields_found: 2, not_found_in_record: 1, labs_outside_range: 1, labs_not_judged: 1 },
    fields: {
      species: { value: 'Dog', quote: 'Species: Dog', found_in_record: true, value_in_quote: true },
      age: { value: '9 years', quote: 'Age: 9 years', found_in_record: false, value_in_quote: true },
      breed: { value: null, quote: null, found_in_record: null, value_in_quote: null },
    },
    medications: [],
    lab_results: [
      { analyte: 'pcv', name_as_written: 'PCV', value: 22, qualifier: null, unit: '%', range_low: 37, range_high: 55, range_unit: null,
        quote: 'PCV 22 % (37 - 55)', found_in_record: true, flag: 'low', reason: 'Compared with the range printed in the record.', caution: null },
      { analyte: 'wbc', name_as_written: 'WBC', value: 12, qualifier: null, unit: 'x10^9/L', range_low: null, range_high: null, range_unit: null,
        quote: 'WBC 12.0 x10^9/L', found_in_record: true, flag: 'not_judged', reason: 'No reference range was printed in the record.', caution: null },
    ],
  },
}

function respond(routes: Record<string, unknown>) {
  fetchMock.mockImplementation((url: string, options?: RequestInit) => {
    const key = `${options?.method || 'GET'} ${url}`
    const body = routes[key]
    if (body === undefined) return Promise.resolve(Response.json({ detail: `unmocked ${key}` }, { status: 404 }))
    return Promise.resolve(Response.json(body, { status: options?.method === 'POST' ? 202 : 200 }))
  })
}

beforeEach(() => fetchMock.mockReset())
afterEach(() => cleanup())

describe('Extraction panel', () => {
  it('stays closed and makes no request until the button is pressed', () => {
    render(<ExtractionPanel basePath="/cases/1/uploads/1" />)
    expect(screen.getByRole('button', { name: 'Extract fields (experimental)' })).toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('explains when extraction is unavailable and keeps the run button disabled', async () => {
    respond({ 'GET /extraction/status': { ...available, available: false, reason: 'No Anthropic API key is configured on this server.' },
      'GET /cases/1/uploads/1/extraction': [] })
    render(<ExtractionPanel basePath="/cases/1/uploads/1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Extract fields (experimental)' }))
    expect(await screen.findByText(/No Anthropic API key is configured/)).toBeTruthy()
    fireEvent.click(screen.getByRole('checkbox'))
    expect((screen.getByRole('button', { name: 'Extract fields' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows values with their passages, marks unverified passages and flags labs from fixed rules', async () => {
    respond({ 'GET /extraction/status': available, 'GET /cases/1/uploads/1/extraction': [completed] })
    render(<ExtractionPanel basePath="/cases/1/uploads/1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Extract fields (experimental)' }))
    expect(await screen.findByText('Dog')).toBeTruthy()
    expect(screen.getByText('Passage not found in the record')).toBeTruthy()
    expect(screen.queryByText('Breed')).toBeNull()
    expect(screen.getByText('LOW')).toBeTruthy()
    expect(screen.getByText('Not judged')).toBeTruthy()
    expect(screen.getByText('No reference range was printed in the record.')).toBeTruthy()
    expect(screen.getByText(/no case field was changed/i)).toBeTruthy()
  })

  it('requires acknowledgement before it starts a run', async () => {
    respond({ 'GET /extraction/status': available, 'GET /cases/1/uploads/1/extraction': [], 'POST /cases/1/uploads/1/extraction': { ...completed, status: 'queued', result: {} } })
    render(<ExtractionPanel basePath="/cases/1/uploads/1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Extract fields (experimental)' }))
    await screen.findByText('Experimental limitation text.')
    const run = screen.getByRole('button', { name: 'Extract fields' }) as HTMLButtonElement
    expect(run.disabled).toBe(true)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(run.disabled).toBe(false)
  })

  it('shows a failed run with its safe message', async () => {
    respond({ 'GET /extraction/status': available, 'GET /cases/1/uploads/1/extraction': [{ ...completed, status: 'failed', error: 'The model service is busy. Try again in a minute.', result: {} }] })
    render(<ExtractionPanel basePath="/cases/1/uploads/1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Extract fields (experimental)' }))
    expect(await screen.findByText(/The model service is busy/)).toBeTruthy()
  })
})
