export async function sessionFetch(input: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers)
  if (!['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase())) headers.set('X-VetInsight-Request', '1')
  const response = await fetch(input, { ...options, headers, credentials: 'include' })
  if (response.status === 401) window.dispatchEvent(new Event('vetinsight:unauthorized'))
  return response
}
