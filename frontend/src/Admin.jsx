import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'

const PHASES = ['pretest', 'practice', 'break', 'heldout', 'done']
const MINUTES = { pretest: 15, practice: 45, heldout: 30 }
const left = (r) => {
  if (!MINUTES[r.phase] || !r.phase_started_at) return ''
  const ms = Date.parse(r.phase_started_at) + MINUTES[r.phase] * 60000 - Date.now()
  return ms > 0 ? `${Math.ceil(ms / 60000)} min left` : 'time up'
}
const TK = 'los_admin'
const getTok = () => { try { return sessionStorage.getItem(TK) || '' } catch { return '' } }

export default function Admin() {
  const [tok, setTok] = useState(getTok())
  const [rows, setRows] = useState([])
  const [sel, setSel] = useState([])
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [names, setNames] = useState('')
  const [pilot, setPilot] = useState(false)
  const [created, setCreated] = useState([])
  const [stats, setStats] = useState(null)

  const load = useCallback(async () => {
    if (!tok) return
    try {
      setRows(await api('/admin/learners', { admin: tok }))
      setStats(await api('/admin/stats', { admin: tok }))
    }
    catch (e) { setMsg('Could not load learners: ' + e.message) }
  }, [tok])
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id) }, [load])

  const act = async (fn) => {
    if (busy) return
    setBusy(true)
    try { const r = await fn(); setMsg(typeof r === 'string' ? r : 'Done.'); await load() }
    catch (e) { setMsg('Error: ' + e.message) }
    setBusy(false)
  }

  if (!tok) return (
    <div className="h-full flex items-center justify-center">
      <form onSubmit={(e) => { e.preventDefault(); const v = e.target.t.value; try { sessionStorage.setItem(TK, v) } catch {} setTok(v) }}
        className="card bd rad p-6 space-y-3">
        <label htmlFor="t" className="block font-semibold">Invigilator login</label>
        <input id="t" name="t" type="password" placeholder="Admin token" className="bd rad px-3 py-2" />
        <button className="btn btn-accent w-full justify-center">Enter</button>
      </form>
    </div>
  )

  const toggle = (id) => setSel((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id])
  const names_ = (ids) => rows.filter((r) => ids.includes(r.learner_id)).map((r) => r.display_name).join(', ')
  const download = async () => {
    const data = await api('/admin/export', { admin: tok })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' }))
    a.download = `learning-os-export-${new Date().toISOString().slice(0, 16).replace(':', '')}.json`
    a.click()
  }
  const movePhase = (p) => act(async () => {
    if (['heldout', 'done'].includes(p) && !window.confirm(`Move ${names_(sel)} to ${p}?`)) return 'Cancelled.'
    try { await api('/admin/phase', { method: 'POST', admin: tok, body: { learner_ids: sel, phase: p } }) }
    catch (e) {
      if (!/BACKWARDS/.test(e.message) || !window.confirm(e.message + '\n\nMove backwards anyway?')) throw e
      await api('/admin/phase', { method: 'POST', admin: tok, body: { learner_ids: sel, phase: p, force: true } })
    }
    const msg = `Moved ${names_(sel)} to ${p}.`
    setSel([])
    return msg
  })

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="f-head text-2xl font-bold">Invigilator console</h1>
        <div className="flex gap-2">
          <button onClick={download} className="btn btn-ghost">Download export</button>
          <button onClick={() => { try { sessionStorage.removeItem(TK) } catch {} setTok('') }} className="btn btn-ghost">Lock</button>
        </div>
      </div>
      {msg && <div className="text-sm px-3 py-2 rad msg-warn flex justify-between gap-3"><pre className="whitespace-pre-wrap f-mono text-xs">{msg}</pre><button onClick={() => setMsg('')} aria-label="Dismiss">✕</button></div>}

      {stats && Object.keys(stats).length > 0 && (
        <div className="text-sm flex gap-6 flex-wrap">
          {Object.entries(stats).map(([arm, s]) => {
            const share = s.help ? s.fallback / s.help : 0
            return <span key={arm} className={share > 0.2 ? 'msg-err px-2 rad' : 't-muted'}>
              {arm}: {s.help} help · {s.fallback} fallback{share > 0.2 ? ' (over 20%: check Groq limits)' : ''} · {s.blocked} guard blocks
            </span>
          })}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="t-muted text-left">
            <tr><th className="p-2"><input type="checkbox" aria-label="Select all" checked={sel.length === rows.length && rows.length > 0}
              onChange={(e) => setSel(e.target.checked ? rows.filter((r) => !r.excluded).map((r) => r.learner_id) : [])} /></th>
              <th>ID</th><th>Name</th><th>Code</th><th>Pilot</th><th>Pretest</th><th>Arm</th><th>Pair</th><th>Phase</th><th>Finished in phase</th><th></th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.learner_id} className="bd-t" style={r.excluded ? { opacity: 0.45 } : undefined}>
                <td className="p-2"><input type="checkbox" aria-label={`Select ${r.display_name}`} disabled={r.excluded} checked={sel.includes(r.learner_id)} onChange={() => toggle(r.learner_id)} /></td>
                <td>{r.learner_id}</td><td>{r.display_name}{r.excluded ? ' (excluded)' : ''}</td><td className="f-mono">{r.code}</td>
                <td>{r.is_pilot ? 'yes' : ''}</td>
                <td>{r.pretest_score}/6 <span className="t-muted">({r.pretest_done} submitted)</span></td>
                <td>{r.arm || <span className="t-muted">—</span>}
                  {r.is_pilot && !r.arm && <span className="ml-2 space-x-2">
                    {['tutor', 'baseline'].map((a) => <button key={a} className="text-xs underline t-accent"
                      onClick={() => act(() => api('/admin/arm', { method: 'POST', admin: tok, body: { learner_id: r.learner_id, arm: a } }))}>{a}</button>)}
                  </span>}</td>
                <td>{r.pair_no ?? ''}</td><td>{r.phase} <span className="t-muted text-xs">{left(r)}</span></td><td>{r.finished_in_phase}</td>
                <td>{!r.excluded && <button className="text-xs underline t-muted" onClick={() => act(async () => {
                  const reason = window.prompt(`Exclude ${r.display_name}? Their code stops working. Reason (e.g. no-show):`)
                  if (!reason) return 'Cancelled.'
                  await api('/admin/exclude', { method: 'POST', admin: tok, body: { learner_id: r.learner_id, reason } })
                  return `Excluded ${r.display_name}.`
                })}>exclude</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm t-muted">Move selected ({sel.length}) to (this starts that phase's clock):</span>
        {PHASES.map((p) => (
          <button key={p} disabled={!sel.length || busy} className="btn btn-ghost" onClick={() => movePhase(p)}>{p}</button>
        ))}
        <button disabled={busy} className="ml-auto btn btn-accent"
          onClick={() => act(async () => 'Assigned:\n' + JSON.stringify(await api('/admin/assign', { method: 'POST', admin: tok }), null, 1))}>
          {busy ? 'Working…' : 'Assign arms (pairs + coin flip)'}
        </button>
      </div>

      <div className="card bd rad p-4 space-y-3">
        <div className="font-semibold">Add learners</div>
        <textarea value={names} onChange={(e) => setNames(e.target.value)} rows={3} placeholder="One name per line" aria-label="Names"
          className="w-full bd rad p-2 text-sm" />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={pilot} onChange={(e) => setPilot(e.target.checked)} /> Pilot (excluded from results)</label>
        <button disabled={busy || !names.trim()} className="btn btn-primary" onClick={() => act(async () => {
          const r = await api('/admin/learners', { method: 'POST', admin: tok, body: { names: names.split('\n'), pilot } })
          setCreated(r); setNames(''); setPilot(false)
          return `Created ${r.length}${pilot ? ' PILOT' : ''} learner(s). Copy the codes below onto slips.`
        })}>Create</button>
        {created.length > 0 && <div className="f-mono text-sm">{created.map((c) => <div key={c.code}>{c.name}: {c.code}</div>)}</div>}
      </div>
    </div>
  )
}
