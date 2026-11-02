import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AuthProvider from './Auth'
import Admin from './Admin'
import type { User } from './api'

const mocks = vi.hoisted(() => ({ status: vi.fn(), setup: vi.fn(), me: vi.fn(), login: vi.fn(), password: vi.fn(), logout: vi.fn(), overview: vi.fn(), users: vi.fn(), audit: vi.fn(), createUser: vi.fn() }))
vi.mock('./api', async importOriginal => ({ ...await importOriginal<typeof import('./api')>(),
  authApi: { status: mocks.status, setup: mocks.setup, me: mocks.me, login: mocks.login, password: mocks.password, logout: mocks.logout },
  adminApi: { overview: mocks.overview, users: mocks.users, audit: mocks.audit, createUser: mocks.createUser },
}))
const admin: User = { id: 1, username: 'admin-test', display_name: 'Admin test', role: 'admin', active: true, must_change_password: false, created_at: '2026-11-01T12:00:00Z' }
beforeEach(() => {
  vi.resetAllMocks()
  mocks.status.mockResolvedValue({ needs_setup: false })
  mocks.me.mockResolvedValue(admin)
  mocks.overview.mockResolvedValue({ users: 1, active_users: 1, administrators: 1, cases: 0, uploads: 0, upload_bytes: 0 })
  mocks.users.mockResolvedValue({ items: [admin], total: 1 }); mocks.audit.mockResolvedValue({ items: [], total: 0 })
})
afterEach(cleanup)

describe('Admin authentication and workspace', () => {
  it('creates the first administrator through the local setup form and signs in', async () => {
    mocks.status.mockResolvedValue({ needs_setup: true, web_setup_available: true })
    mocks.setup.mockResolvedValue(admin)
    render(<AuthProvider><Admin /></AuthProvider>)
    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'admin-test' } })
    fireEvent.change(screen.getByLabelText('Display name'), { target: { value: 'Admin test' } })
    fireEvent.change(screen.getByLabelText('Password', { exact: true }), { target: { value: 'Local-test-password!2026' } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'Local-test-password!2026' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create administrator account' }))
    await screen.findByText('admin-test (you)')
    expect(mocks.setup).toHaveBeenCalledWith('admin-test', 'Admin test', 'Local-test-password!2026')
  })
  it('retains the first-admin form when password confirmation does not match', async () => {
    mocks.status.mockResolvedValue({ needs_setup: true, web_setup_available: true })
    render(<AuthProvider><Admin /></AuthProvider>)
    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'admin-test' } })
    fireEvent.change(screen.getByLabelText('Display name'), { target: { value: 'Admin test' } })
    fireEvent.change(screen.getByLabelText('Password', { exact: true }), { target: { value: 'Local-test-password!2026' } })
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'Different-password!2026' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create administrator account' }))
    expect((await screen.findByRole('alert')).textContent).toContain('do not match')
    expect(mocks.setup).not.toHaveBeenCalled()
  })
  it('shows first-admin setup instead of a public signup form', async () => {
    mocks.status.mockResolvedValue({ needs_setup: true })
    render(<AuthProvider><Admin /></AuthProvider>)
    await screen.findByText('Create your first administrator')
    expect(screen.getByText('Setup-Admin.cmd')).toBeTruthy()
    expect(screen.queryByLabelText('Password')).toBeNull()
    expect(mocks.me).not.toHaveBeenCalled()
  })
  it('shows sign-in errors and keeps the admin screen private', async () => {
    const { ApiError } = await import('./api')
    mocks.me.mockRejectedValue(new ApiError(401, 'Sign in'))
    mocks.login.mockRejectedValue(new ApiError(401, 'Username or password is incorrect.'))
    render(<AuthProvider><Admin /></AuthProvider>)
    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'wrong-user' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect((await screen.findByRole('alert')).textContent).toContain('incorrect')
    expect(mocks.overview).not.toHaveBeenCalled()
  })
  it('does not request admin data for a member', async () => {
    mocks.me.mockResolvedValue({ ...admin, role: 'member' })
    render(<AuthProvider><Admin /></AuthProvider>)
    await screen.findByText('Administrator access required')
    expect(mocks.users).not.toHaveBeenCalled()
  })
  it('requires temporary password replacement before opening administration', async () => {
    mocks.me.mockResolvedValue({ ...admin, must_change_password: true })
    mocks.password.mockResolvedValue(admin)
    render(<AuthProvider><Admin /></AuthProvider>)
    await screen.findByText('Set your own password')
    expect(mocks.users).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'Temporary-password-2026!' } })
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'Replacement-password-2026!' } })
    fireEvent.change(screen.getByLabelText('Confirm new password'), { target: { value: 'Replacement-password-2026!' } })
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
    await screen.findByText('Create account', { selector: 'h2' })
    expect(mocks.password).toHaveBeenCalledWith('Temporary-password-2026!', 'Replacement-password-2026!')
  })
  it('creates accounts through the API and protects self role/status controls', async () => {
    mocks.createUser.mockResolvedValue({ ...admin, id: 2, role: 'member' })
    render(<AuthProvider><Admin /></AuthProvider>)
    await screen.findByText('admin-test (you)')
    const own = within(screen.getByRole('form', { name: 'Edit admin-test' }))
    expect(own.getByLabelText('Role')).toHaveProperty('disabled', true)
    expect(own.getByLabelText('Account status')).toHaveProperty('disabled', true)
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reviewer-test' } })
    fireEvent.change(screen.getAllByLabelText('Display name')[0], { target: { value: 'Reviewer' } })
    fireEvent.change(screen.getByLabelText('Temporary password'), { target: { value: 'Temporary-password-2026!' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    await screen.findByText(/Account created\. Share/)
    expect(mocks.createUser).toHaveBeenCalledWith({ username: 'reviewer-test', display_name: 'Reviewer', password: 'Temporary-password-2026!', role: 'member' })
    expect(screen.getByLabelText('Temporary password')).toHaveProperty('value', '')
  })
})

