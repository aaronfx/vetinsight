import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { adminApi } from './api'
import type { AdminOverview, AuditEvent, Page, User } from './api'
import { useAuth } from './auth-context'

function UserCard({ user, onSaved }: { user: User; onSaved: (message: string) => void }) {
  const [name, setName] = useState(user.display_name), [role, setRole] = useState(user.role), [active, setActive] = useState(user.active)
  const [password, setPassword] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const { user: current } = useAuth()
  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try { await adminApi.updateUser(user.id, { display_name: name, role, active }); onSaved(`Account ${user.username} updated.`) }
    catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  async function reset(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try { await adminApi.resetPassword(user.id, password); setPassword(''); onSaved(`Temporary password set for ${user.username}. Their sessions were revoked.`) }
    catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  return <article className="admin-user"><div className="panel-title"><h3>{user.username}{current.id === user.id ? ' (you)' : ''}</h3>
    <span className="badge">{user.active ? 'Active' : 'Disabled'}</span></div><p className="muted">Created {new Date(user.created_at).toLocaleDateString()}{user.must_change_password ? ' · Password change required' : ''}</p>
    <form aria-label={`Edit ${user.username}`} onSubmit={save}><fieldset disabled={busy}><label>Display name<input required maxLength={120} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>Role<select disabled={current.id === user.id} value={role} onChange={e => setRole(e.target.value as User['role'])}><option value="member">Member</option><option value="admin">Administrator</option></select></label>
      <label>Account status<select disabled={current.id === user.id} value={active ? 'active' : 'disabled'} onChange={e => setActive(e.target.value === 'active')}><option value="active">Active</option><option value="disabled">Disabled</option></select></label>
      <button type="submit">Save account</button></fieldset></form>
    {current.id !== user.id && <details><summary>Reset password</summary><p>This signs out the user and requires a password change at their next login.</p>
      <form onSubmit={reset}><fieldset disabled={busy}><label>Temporary password<input type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={password} onChange={e => setPassword(e.target.value)} /></label><button type="submit" className="secondary">Set temporary password</button></fieldset></form></details>}
    {error && <p className="error" role="alert">{error}</p>}</article>
}

export default function Admin() {
  const { user } = useAuth()
  const [overview, setOverview] = useState<AdminOverview | null>(null), [users, setUsers] = useState<Page<User> | null>(null), [audit, setAudit] = useState<Page<AuditEvent> | null>(null)
  const [offset, setOffset] = useState(0), [auditOffset, setAuditOffset] = useState(0), [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [message, setMessage] = useState(''), [creating, setCreating] = useState(false)
  const [username, setUsername] = useState(''), [name, setName] = useState(''), [password, setPassword] = useState(''), [role, setRole] = useState<User['role']>('member')
  useEffect(() => {
    if (user.role !== 'admin') return
    let active = true
    Promise.all([adminApi.overview(), adminApi.users(offset), adminApi.audit(auditOffset)]).then(([nextOverview, nextUsers, nextAudit]) => {
      if (active) { setOverview(nextOverview); setUsers(nextUsers); setAudit(nextAudit) }
    }).catch(err => { if (active) setError(err.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [user.role, offset, auditOffset, refresh])
  function saved(text: string) { setMessage(text); setError(''); setLoading(true); setRefresh(n => n + 1) }
  async function create(event: FormEvent) {
    event.preventDefault(); setCreating(true); setError(''); setMessage('')
    try { await adminApi.createUser({ username, display_name: name, password, role }); setUsername(''); setName(''); setPassword(''); setRole('member'); setOffset(0); saved('Account created. Share the temporary password privately; the user must change it at sign-in.') }
    catch (err) { setError((err as Error).message); setPassword('') } finally { setCreating(false) }
  }
  if (user.role !== 'admin') return <section><h2>Administrator access required</h2><p>Your account can use the case workspace. Contact an administrator for account changes.</p></section>
  return <div className="admin-workspace"><p>Manage workspace accounts and review recorded activity. Members can access all cases; administrators also manage accounts.</p>
    <button className="secondary" disabled={loading} onClick={() => { setLoading(true); setError(''); setRefresh(n => n + 1) }}>Refresh administration</button>
    {loading && <p role="status">Loading administration…</p>}{error && <p className="error" role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {overview && <div className="stats-grid">{[['Accounts', overview.users], ['Active accounts', overview.active_users], ['Active administrators', overview.administrators], ['Cases', overview.cases]].map(([label, count]) => <section className="stat-card" key={label}><p>{label}</p><strong>{count}</strong></section>)}</div>}
    {overview && <p>{overview.uploads} stored attachments · {(overview.upload_bytes / 1024 / 1024).toFixed(2)} MiB of original uploaded files</p>}
    <section><h2>Create account</h2><form onSubmit={create}><fieldset disabled={creating || loading}>
      <div className="form-grid"><label>Username<input autoComplete="off" required pattern="[a-zA-Z0-9][a-zA-Z0-9_.\-]{2,79}" minLength={3} maxLength={80} value={username} onChange={e => setUsername(e.target.value)} /></label>
      <label>Display name<input required maxLength={120} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>Temporary password<input type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={password} onChange={e => setPassword(e.target.value)} /></label>
      <label>Role<select value={role} onChange={e => setRole(e.target.value as User['role'])}><option value="member">Member</option><option value="admin">Administrator</option></select></label></div>
      <small>Username: 3–80 letters, numbers, dots, dashes or underscores. Password: at least 12 characters.</small><button type="submit">{creating ? 'Creating…' : 'Create account'}</button>
    </fieldset></form></section>
    <section><h2>Accounts</h2><p>Disabling an account, changing its role or resetting its password revokes its sessions.</p>
      <div className="admin-users">{users?.items.map(account => <UserCard key={`${account.id}-${refresh}`} user={account} onSaved={saved} />)}</div>
      <nav aria-label="Account pages"><button className="secondary" disabled={loading || offset === 0} onClick={() => setOffset(n => Math.max(0, n - 20))}>Previous accounts</button>
        <span>{users ? `${offset + (users.items.length ? 1 : 0)}–${offset + users.items.length} of ${users.total}` : 'Loading accounts'}</span><button className="secondary" disabled={loading || !users || offset + 20 >= users.total} onClick={() => setOffset(n => n + 20)}>Next accounts</button></nav></section>
    <section><h2>Audit activity</h2><p>Records sign-ins, account changes and successful case writes. Clinical notes and passwords are not copied into this log.</p>
      <div className="table-scroll"><table><thead><tr><th>Time</th><th>Account</th><th>Action</th><th>Target</th></tr></thead><tbody>{audit?.items.map(item => <tr key={item.id}><td>{new Date(item.created_at).toLocaleString()}</td><td>{item.actor || 'Unauthenticated'}</td><td>{item.action}</td><td>{item.target}</td></tr>)}</tbody></table></div>
      <nav aria-label="Audit pages"><button className="secondary" disabled={loading || auditOffset === 0} onClick={() => setAuditOffset(n => Math.max(0, n - 20))}>Previous activity</button>
        <span>{audit ? `${auditOffset + (audit.items.length ? 1 : 0)}–${auditOffset + audit.items.length} of ${audit.total}` : 'Loading activity'}</span><button className="secondary" disabled={loading || !audit || auditOffset + 20 >= audit.total} onClick={() => setAuditOffset(n => n + 20)}>Next activity</button></nav></section>
  </div>
}
