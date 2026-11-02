import { sessionFetch } from './session'

export interface CaseSummary {
  id: number
  patient_name: string
  species: string
  notes: string
  created_at: string
  upload_count: number
  image_count: number
}
export interface UploadInfo {
  id: number
  filename: string
  content_type: string
  size_bytes: number
  download_url: string
  preview_url: string
  text_url: string
}
export interface DocumentText {
  status: 'extracted' | 'partial' | 'ocr_required'
  page_count: number
  pages: { page_number: number; text: string; status: 'extracted' | 'ocr_required' }[]
}
export interface CaseDetail extends CaseSummary {
  uploads: UploadInfo[]
}

export type DatasetSplit = 'unassigned' | 'train' | 'validation' | 'test'
export interface DatasetAssignment {
  case_id: number
  split: DatasetSplit
  revision: number
  updated_at: string | null
}

export type ReviewStatus = 'Needs Review' | 'In Progress' | 'Reviewed'
export interface Annotation {
  id: string
  x: number
  y: number
  width: number
  height: number
  category: string
  review_status: ReviewStatus
  notes: string
}
export interface AnnotationSet {
  case_id: number
  upload_id: number
  image_width: number
  image_height: number
  revision: number
  review_status: ReviewStatus
  annotations: Annotation[]
  updated_at: string | null
}
export interface Dashboard {
  case_count: number
  document_count: number
  image_count: number
  upload_count: number
  annotation_count: number
  needs_review_count: number
  species: string[]
}

const baseUrl = (import.meta.env.VITE_API_BASE_URL || (import.meta.env.PROD ? '' : 'http://localhost:8000')).replace(/\/$/, '')
export const downloadUrl = (path: string) => `${baseUrl}${path}`

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response
  try { response = await sessionFetch(`${baseUrl}${path}`, options) }
  catch { throw new Error('Cannot reach the backend. Check that it is running on port 8000.') }
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body?.detail
    throw new ApiError(response.status, Array.isArray(detail)
      ? detail.map((item: { loc: string[]; msg: string }) => `${item.loc.join('.')}: ${item.msg}`).join('; ')
      : typeof detail === 'string' ? detail : `Request failed (${response.status}).`)
  }
  return body as T
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}
export interface User {
  id: number; username: string; display_name: string; role: 'admin' | 'member'
  active: boolean; must_change_password: boolean; created_at: string
}
export interface AdminOverview { users: number; active_users: number; administrators: number; cases: number; uploads: number; upload_bytes: number }
export interface AuditEvent { id: number; actor_id: number | null; actor: string | null; action: string; target: string; created_at: string }
export interface Page<T> { items: T[]; total: number }
const jsonPost = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const authApi = {
  status: () => request<{ service: string; needs_setup: boolean; web_setup_available: boolean }>('/auth/status'),
  setup: (username: string, display_name: string, password: string) => request<User>('/auth/setup', jsonPost({ username, display_name, password })),
  me: () => request<User>('/auth/me'),
  login: (username: string, password: string) => request<User>('/auth/login', jsonPost({ username, password })),
  logout: () => request('/auth/logout', jsonPost({})),
  password: (current_password: string, password: string) => request<User>('/auth/password', jsonPost({ current_password, password })),
}
export const adminApi = {
  overview: () => request<AdminOverview>('/admin/overview'),
  users: (offset = 0) => request<Page<User>>(`/admin/users?limit=20&offset=${offset}`),
  createUser: (data: { username: string; display_name: string; password: string; role: User['role'] }) => request<User>('/admin/users', jsonPost(data)),
  updateUser: (id: number, data: Pick<User, 'display_name' | 'role' | 'active'>) => request<User>(`/admin/users/${id}`, { ...jsonPost(data), method: 'PUT' }),
  resetPassword: (id: number, password: string) => request(`/admin/users/${id}/password`, jsonPost({ password })),
  audit: (offset = 0) => request<Page<AuditEvent>>(`/admin/audit?limit=20&offset=${offset}`),
}

export const api = {
  datasetAssignment: (caseId: number, signal?: AbortSignal) =>
    request<DatasetAssignment>(`/cases/${caseId}/dataset-assignment`, { signal }),
  saveDatasetAssignment: (caseId: number, data: Pick<DatasetAssignment, 'split' | 'revision'>, signal?: AbortSignal) =>
    request<DatasetAssignment>(`/cases/${caseId}/dataset-assignment`, { method: 'PUT', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
  dashboard: (signal?: AbortSignal) => request<Dashboard>('/dashboard', { signal }),
  annotations: (caseId: number, uploadId: number, signal?: AbortSignal) =>
    request<AnnotationSet>(`/cases/${caseId}/uploads/${uploadId}/annotations`, { signal }),
  saveAnnotations: (caseId: number, uploadId: number, data: Pick<AnnotationSet, 'revision' | 'review_status' | 'annotations'>) =>
    request<AnnotationSet>(`/cases/${caseId}/uploads/${uploadId}/annotations`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
  documentText: (path: string, signal: AbortSignal) => request<DocumentText>(path, { signal }),
  listCases: (offset = 0, search = '', species = '', signal?: AbortSignal) =>
    request<CaseSummary[]>(`/cases?limit=20&offset=${offset}&search=${encodeURIComponent(search)}&species=${encodeURIComponent(species)}`, { signal }),
  viewCase: (id: number, signal?: AbortSignal) => request<CaseDetail>(`/cases/${id}`, { signal }),
  createCase: (data: Pick<CaseSummary, 'patient_name' | 'species' | 'notes'>) =>
    request<CaseDetail>('/cases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
  upload: (id: number, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request(`/cases/${id}/uploads`, { method: 'POST', body })
  },
}
