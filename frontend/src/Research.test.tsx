import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import Research from './Research'

afterEach(cleanup)

describe('Recorded research workspace', () => {
  it('reports audited metrics and threshold failures with demonstration labeling', () => {
    render(<Research />)
    expect(screen.getByText('0.094443')).toBeTruthy()
    expect(screen.getByText('At score 0.5, both models missed all 138 test mitoses.')).toBeTruthy()
    expect(screen.getByText('Demonstration data from the public MIDOG++ dataset.')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Download experiment summary' }).getAttribute('href')).toBe('/assets/research/experiment-summary.json')
  })

  it('filters real saved candidates and resets image loading on selection', () => {
    render(<Research />)
    fireEvent.load(screen.getByAltText(/MIDOG\+\+ canine histology/))
    expect(screen.getByRole('img', { name: /0 recorded model candidates/ })).toBeTruthy()
    fireEvent.change(screen.getByRole('slider'), { target: { value: '0' } })
    expect(screen.queryByRole('img', { name: /0 recorded model candidates/ })).toBeNull()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Show source annotations' }))
    expect(screen.getByRole('img', { name: /^0 source boxes/ })).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Demonstration tile'), { target: { value: '3' } })
    expect(screen.getByRole('status').textContent).toContain('Loading demonstration image')
    fireEvent.error(screen.getByAltText(/MIDOG\+\+ canine histology/))
    expect(screen.getByRole('alert').textContent).toContain('could not be loaded')
  })
})
