import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { CaseDetail, Dashboard } from './api'
import CaseList from './CaseList'
import CaseOverview from './CaseOverview'
import CreateCase from './CreateCase'
import CytologyWorkspace from './CytologyWorkspace'
import './App.css'
import Admin from './Admin'
import Research from './Research'
import { ChangePassword, LogoutButton } from './Auth'
import { useAuth } from './auth-context'

function App() {
  const { user } = useAuth()
  const [route, setRoute] = useState(() => window.location.hash.slice(1) || 'dashboard')
  const [menuOpen, setMenuOpen] = useState(false)
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [caseState, setCaseState] = useState<{ id: number; detail: CaseDetail } | null>(null)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const dirty = useRef(false)
  const acceptedRoute = useRef(route)
  const pendingWarning = useRef('')
  const match = /^cases\/(\d+)(?:\/(records|cytology)(?:\/(\d+))?)?$/.exec(route)
  const caseId = match ? Number(match[1]) : null
  const tab = match?.[2] || 'summary'
  const detail = caseState?.id === caseId ? caseState.detail : null
  const onDirty = useCallback((value: boolean) => { dirty.current = value }, [])
  const navigate = useCallback((next: string) => { window.location.hash = next }, [])
  useEffect(() => {
    function changed() {
      const next = window.location.hash.slice(1) || 'dashboard'
      if (dirty.current && next !== acceptedRoute.current && !window.confirm('Discard unsaved cytology annotations?')) {
        window.history.replaceState(null, '', `#${acceptedRoute.current}`); return
      }
      dirty.current = false; acceptedRoute.current = next; setRoute(next); setMenuOpen(false); setError(pendingWarning.current); pendingWarning.current = ''; window.scrollTo(0, 0)
    }
    function beforeUnload(event: BeforeUnloadEvent) { if (dirty.current) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('hashchange', changed); window.addEventListener('beforeunload', beforeUnload)
    return () => { window.removeEventListener('hashchange', changed); window.removeEventListener('beforeunload', beforeUnload) }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    api.dashboard(controller.signal).then(data => { if (!controller.signal.aborted) setDashboard(data) }).catch(err => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [refresh, route])
  useEffect(() => {
    if (caseId === null) return
    const controller = new AbortController()
    api.viewCase(caseId, controller.signal).then(data => { if (!controller.signal.aborted) setCaseState({ id: caseId, detail: data }) })
      .catch(err => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [caseId, refresh])
  const selectedRoute = (target: string) => caseId ? `cases/${caseId}/${target}` : target
  const title = route === 'research' ? 'Research workspace' : route === 'admin' ? 'Administration' : route === 'account' ? 'Your account' : route === 'dashboard' ? 'Workspace dashboard' : route === 'cases' ? 'Case library' : route === 'new' ? 'Create a case' :
    route === 'records' ? 'Clinical records' : route === 'cytology' ? 'Cytology workspace' : tab === 'cytology' ? 'Cytology workspace' : tab === 'records' ? 'Clinical records' : 'Case overview'

  return <div className="app-shell">
    <aside className={`sidebar ${menuOpen ? 'is-open' : ''}`} aria-label="Main navigation">
      <a href="#dashboard" className="brand"><span className="brand-mark">V</span><span>VetInsight<small>CASE WORKSPACE</small></span></a>
      <nav>{[['dashboard', '▦', 'Dashboard'], ['cases', '▱', 'Cases'], ['records', '▤', 'Clinical records'], ['cytology', '⊕', 'Cytology workspace'], ['research', '◈', 'Research']].map(([target, icon, label]) =>
        <button key={target} className={(route === target || (target === 'cases' && match && tab === 'summary') || tab === target) ? 'active' : ''}
          onClick={() => navigate(target === 'records' || target === 'cytology' ? selectedRoute(target) : target)}><span aria-hidden="true">{icon}</span>{label}</button>)}</nav>
      {user.role === 'admin' && <button className="sidebar-create" onClick={() => navigate('admin')}>Administration</button>}
      <button className="sidebar-create" onClick={() => navigate('account')}>{user.display_name} · {user.role}</button>
      <LogoutButton canLeave={() => !dirty.current || window.confirm('Discard unsaved annotations and sign out?')} />
      <button className="sidebar-create" onClick={() => navigate('new')}>＋ Create case</button>
      <div className="sidebar-foot"><strong>Manual review workspace</strong><p>Case records & image annotations</p></div>
    </aside>
    <div className="main-shell"><header className="topbar"><button className="secondary menu-toggle" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>☰ Menu</button>
      <span>{detail ? `CASE-${String(detail.id).padStart(4, '0')} · ${detail.patient_name}` : 'Veterinary case management'}</span><span className="badge blue">{route === 'research' ? 'Recorded histology experiment' : 'Manual cytology review'}</span></header>
      <main><div className="page-heading"><div><p className="eyebrow">VetInsight / {caseId ? `Case ${caseId}` : 'Workspace'}</p><h1>{title}</h1>
        <p className="muted">{route === 'research' ? 'Explore measured experiments, recorded predictions and study limitations.' : route === 'new' ? 'Create a patient record and attach your source documents.' : caseId ? 'Clinical records and cytology, connected to the same case.' : 'Manage case records, review documents and annotate cytology images.'}</p></div>
        {route !== 'new' && <button onClick={() => navigate('new')}>＋ Create case</button>}</div>
        {error && <div className="error" role="alert">{error}<button className="secondary" onClick={() => { setError(''); setRefresh(value => value + 1) }}>Retry</button></div>}
        {route === 'dashboard' && <div className="stats-grid">{[['Cases', dashboard?.case_count, 'Stored patient records'], ['Clinical documents', dashboard?.document_count, 'Uploaded PDFs'], ['Cytology images', dashboard?.image_count, 'Uploaded JPG & PNG files'], ['Manual annotations', dashboard?.annotation_count, dashboard ? `${dashboard.needs_review_count} need review` : 'Loading review counts']].map(([label, count, description]) =>
          <section className="stat-card" key={String(label)}><p>{label}</p><strong>{count ?? '—'}</strong><small>{description}</small></section>)}</div>}
        {(route === 'dashboard' || route === 'cases') && <CaseList key={`${route}-${refresh}`} dashboard={dashboard} navigate={navigate} />}
        {(route === 'records' || route === 'cytology') && <section className="empty"><h2>Select a case</h2><p>Open a case to access its {route === 'records' ? 'clinical records' : 'cytology images'}.</p><button onClick={() => navigate('cases')}>Browse cases</button></section>}
        {route === 'admin' && <Admin />}
        {route === 'research' && <Research />}
        {route === 'account' && <ChangePassword />}
        {route === 'new' && <CreateCase navigate={navigate} onCreated={(id, warning) => { pendingWarning.current = warning || ''; setRefresh(value => value + 1); navigate(`cases/${id}`) }} />}
        {match && !detail && !error && <p role="status">Loading case…</p>}
        {match && detail && <><section className="patient-banner"><div className="patient-mark" aria-hidden="true">{detail.patient_name.slice(0, 1).toUpperCase()}</div>
          <div><h2>{detail.patient_name} <span className="badge">CASE-{String(detail.id).padStart(4, '0')}</span></h2><p>{detail.species} · {detail.uploads.length} attachments · {detail.image_count} images</p></div></section>
          <nav className="case-tabs" aria-label="Case workspace tabs">{[['summary', 'Overview'], ['records', 'Clinical records'], ['cytology', 'Cytology images']].map(([target, label]) =>
            <button key={target} className={tab === target ? 'active' : 'secondary'} onClick={() => navigate(`cases/${detail.id}${target === 'summary' ? '' : `/${target}`}`)}>{label}</button>)}</nav>
          {tab === 'cytology' ? <CytologyWorkspace key={detail.id} detail={detail} initialImageId={match[3] ? Number(match[3]) : undefined} onDirty={onDirty} onSaved={() => setRefresh(value => value + 1)}
            onUpload={() => navigate(`cases/${detail.id}`)} onSelectImage={id => navigate(`cases/${detail.id}/cytology/${id}`)} /> : <CaseOverview key={`${detail.id}-${tab}`} detail={detail} tab={tab} navigate={navigate} onUpdated={data => { setCaseState({ id: data.id, detail: data }); setRefresh(value => value + 1) }} />}
        </>}
        {route === 'dashboard' && <section className="workflow-note"><h2>A connected review workflow</h2><div className="steps-grid"><div><span>01</span><h3>Create a case</h3><p>Record patient details and source notes.</p></div><div><span>02</span><h3>Review documents</h3><p>View records with embedded PDF text alongside.</p></div><div><span>03</span><h3>Annotate images</h3><p>Draw regions, assign categories and save your review.</p></div></div></section>}
        {!match && !['dashboard', 'cases', 'new', 'records', 'cytology', 'admin', 'account', 'research'].includes(route) && <section className="empty"><h2>Page not found</h2><button onClick={() => navigate('dashboard')}>Return to dashboard</button></section>}
      </main></div>
  </div>
}
export default App
