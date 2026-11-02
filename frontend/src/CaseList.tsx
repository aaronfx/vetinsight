import { useEffect, useState } from 'react'
import { api } from './api'
import type { CaseSummary, Dashboard } from './api'

export default function CaseList({ dashboard, navigate }: { dashboard: Dashboard | null; navigate: (route: string) => void }) {
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [search, setSearch] = useState('')
  const [species, setSpecies] = useState('')
  const [offset, setOffset] = useState(0)
  const [loaded, setLoaded] = useState('')
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const query = `${search}|${species}|${offset}|${refresh}`
  useEffect(() => {
    const controller = new AbortController()
    api.listCases(offset, search, species, controller.signal).then(result => {
      if (controller.signal.aborted) return
      setCases(result); setLoaded(query); setError('')
    }).catch(err => { if (!controller.signal.aborted) { setError(err.message); setLoaded(query) } })
    return () => controller.abort()
  }, [offset, search, species, query])
  const loading = loaded !== query
  return <>
    <section className="filters" aria-label="Filter cases">
      <label className="search-field">Search cases<input value={search} maxLength={120} placeholder="Patient name or case ID" onChange={event => { setSearch(event.target.value); setOffset(0) }} /></label>
      <label>Species<select value={species} onChange={event => { setSpecies(event.target.value); setOffset(0) }}><option value="">All species</option>
        {dashboard?.species.map(item => <option key={item}>{item}</option>)}</select></label>
      <button className="secondary" onClick={() => setRefresh(value => value + 1)}>Refresh cases</button>
    </section>
    <section className="case-table-panel">
      <div className="panel-title"><h2>Case library</h2><span className="badge">{loading ? 'Loading' : `${cases.length} shown`}</span></div>
      {error && <p className="error" role="alert">{error}</p>}
      {loading ? <p className="empty" role="status">Loading cases…</p> : cases.length === 0 ? <div className="empty"><h3>No cases found</h3><p>Create a case or change the filters.</p><button onClick={() => navigate('new')}>Create case</button></div> :
        <div className="table-scroll"><table><thead><tr><th>Case identifier</th><th>Patient</th><th>Date added</th><th>Records & images</th><th>Actions</th></tr></thead>
          <tbody>{cases.map(item => <tr key={item.id}><td><strong>CASE-{String(item.id).padStart(4, '0')}</strong></td>
            <td><strong>{item.patient_name}</strong><small>{item.species}</small></td><td>{new Date(item.created_at).toLocaleDateString()}</td>
            <td><span className="badge">{item.upload_count - item.image_count} PDFs</span> <span className="badge blue">{item.image_count} images</span></td>
            <td><button className="secondary" onClick={() => navigate(`cases/${item.id}`)}>Open case</button></td></tr>)}</tbody></table></div>}
      <div className="table-footer"><span>{cases.length > 0 ? `Showing ${offset + 1}–${offset + cases.length}` : 'No results'}</span>
        <nav aria-label="Case pages"><button className="secondary" disabled={offset === 0 || loading} onClick={() => setOffset(offset - 20)}>Previous</button>
          <button className="secondary" disabled={cases.length < 20 || loading} onClick={() => setOffset(offset + 20)}>Next</button></nav></div>
    </section>
  </>
}
