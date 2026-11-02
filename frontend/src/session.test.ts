import { afterEach, expect, it, vi } from 'vitest'
import { sessionFetch } from './session'
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
it('includes cookies and the required security header for mutations', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('{}'))
  vi.stubGlobal('fetch', fetch)
  await sessionFetch('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
  const options = fetch.mock.calls[0][1]
  expect(options.credentials).toBe('include')
  expect(options.headers.get('X-VetInsight-Request')).toBe('1')
  expect(options.headers.get('Content-Type')).toBe('application/json')
})
it('ends the UI session when a protected download receives 401', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })))
  const expired = vi.fn(); window.addEventListener('vetinsight:unauthorized', expired)
  try { await sessionFetch('/cases/1/uploads/1/preview'); expect(expired).toHaveBeenCalledOnce() }
  finally { window.removeEventListener('vetinsight:unauthorized', expired) }
})
