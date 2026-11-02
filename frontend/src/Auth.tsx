import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError, authApi } from './api'
import type { User } from './api'
import { AuthContext, useAuth } from './auth-context'

export function ChangePassword() {
  const { user, setUser } = useAuth()
  const [current, setCurrent] = useState(''), [password, setPassword] = useState(''), [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setMessage('')
    if (password !== confirm) { setError('The new passwords do not match.'); return }
    setBusy(true)
    try {
      setUser(await authApi.password(current, password)); setCurrent(''); setPassword(''); setConfirm('')
      setMessage('Password changed. Other sessions have been signed out.')
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  return <section className="account-form"><h2>{user.must_change_password ? 'Set your own password' : 'Change password'}</h2>
    <p>{user.must_change_password ? 'Replace your temporary password before opening the workspace.' : 'Changing your password signs out your other sessions.'}</p>
    <form onSubmit={submit}><fieldset disabled={busy}>
      <label>Current password<input type="password" autoComplete="current-password" required maxLength={256} value={current} onChange={e => setCurrent(e.target.value)} /></label>
      <label>New password<input type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={password} onChange={e => setPassword(e.target.value)} /></label>
      <label>Confirm new password<input type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={confirm} onChange={e => setConfirm(e.target.value)} /></label>
      <small>Use at least 12 characters.</small><button type="submit">{busy ? 'Saving…' : 'Change password'}</button>
    </fieldset></form>{error && <p className="error" role="alert">{error}</p>}{message && <p role="status">{message}</p>}</section>
}

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null), [setup, setSetup] = useState(false), [loading, setLoading] = useState(true)
  const [webSetup, setWebSetup] = useState(false), [name, setName] = useState(''), [confirm, setConfirm] = useState('')
  const [username, setUsername] = useState(''), [password, setPassword] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    async function load() {
      setLoading(true); setError('')
      try {
        const status = await authApi.status()
        if (!active) return
        setSetup(status.needs_setup)
        setWebSetup(status.web_setup_available)
        if (!status.needs_setup) {
          try { const current = await authApi.me(); if (active) setUser(current) }
          catch (err) { if (!(err instanceof ApiError && err.status === 401)) throw err }
        }
      } catch (err) { if (active) setError((err as Error).message) }
      finally { if (active) setLoading(false) }
    }
    void load()
    const expired = () => { setUser(null); setPassword('') }
    window.addEventListener('vetinsight:unauthorized', expired)
    return () => { active = false; window.removeEventListener('vetinsight:unauthorized', expired) }
  }, [retry])
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try { setUser(await authApi.login(username, password)); setPassword('') }
    catch (err) { setError((err as Error).message); setPassword('') } finally { setBusy(false) }
  }
  async function createAdmin(event: FormEvent) {
    event.preventDefault(); setError('')
    if (password !== confirm) { setError('The passwords do not match.'); return }
    setBusy(true)
    try {
      setUser(await authApi.setup(username, name, password)); setPassword(''); setConfirm(''); setName(''); setSetup(false)
    } catch (err) {
      setError((err as Error).message); setPassword(''); setConfirm('')
      if (err instanceof ApiError && err.status === 409) setSetup(false)
    } finally { setBusy(false) }
  }
  async function logout() {
    await authApi.logout(); setUser(null); setPassword(''); window.location.hash = 'dashboard'
  }
  if (loading) return <main className="auth-shell"><p role="status">Checking your session…</p></main>
  if (!user) return <main className="auth-shell"><section><p className="eyebrow">VetInsight</p><h1>{setup ? 'Create your first administrator' : 'Sign in'}</h1>
    {setup && webSetup ? <><p>Create the administrator account for this workspace. This setup is available only on this computer and closes after the first account is created.</p>
      <form onSubmit={createAdmin}><fieldset disabled={busy}>
        <label>Username<input autoComplete="username" required pattern="[a-zA-Z0-9][a-zA-Z0-9_.\-]{2,79}" minLength={3} maxLength={80} value={username} onChange={e => setUsername(e.target.value)} /></label>
        <small>3–80 letters, numbers, dots, dashes or underscores.</small>
        <label>Display name<input autoComplete="name" required maxLength={120} value={name} onChange={e => setName(e.target.value)} /></label>
        <label>Password<input type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={password} onChange={e => setPassword(e.target.value)} /></label>
        <small>Use at least 12 characters.</small>
        <label>Confirm password<input type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={confirm} onChange={e => setConfirm(e.target.value)} /></label>
        <button type="submit">{busy ? 'Creating administrator…' : 'Create administrator account'}</button>
      </fieldset></form></> : setup ? <><p>On the computer hosting VetInsight, double-click <strong>Setup-Admin.cmd</strong>. Choose your username and password in the terminal, then return here.</p>
      <p>Browser setup is available only through localhost on that computer.</p><button onClick={() => setRetry(n => n + 1)}>Check setup again</button></> :
      <form onSubmit={login}><fieldset disabled={busy}><label>Username<input autoComplete="username" required maxLength={80} value={username} onChange={e => setUsername(e.target.value)} /></label>
        <label>Password<input type="password" autoComplete="current-password" required maxLength={256} value={password} onChange={e => setPassword(e.target.value)} /></label>
        <button type="submit">{busy ? 'Signing in…' : 'Sign in'}</button></fieldset></form>}
    {error && <p className="error" role="alert">{error}</p>}{!setup && <button className="secondary" onClick={() => setRetry(n => n + 1)}>Retry connection</button>}
    <small>{setup ? 'After setup, only an administrator can create additional accounts.' : 'Access is limited to accounts created by an administrator.'}</small></section></main>
  return <AuthContext.Provider value={{ user, setUser, logout }}>{user.must_change_password ? <main className="auth-shell"><ChangePassword /><LogoutButton /></main> : children}</AuthContext.Provider>
}

export function LogoutButton({ canLeave }: { canLeave?: () => boolean }) {
  const { logout } = useAuth(), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  return <><button className="secondary" disabled={busy} onClick={() => { if (canLeave && !canLeave()) return; setBusy(true); void logout().catch(err => setError(err.message)).finally(() => setBusy(false)) }}>Sign out</button>
    {error && <p role="alert" className="error">{error}</p>}</>
}
