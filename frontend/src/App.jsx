import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { sql as sqlLang, PostgreSQL } from '@codemirror/lang-sql'
import { EditorView, keymap } from '@codemirror/view'
import { Prec } from '@codemirror/state'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'
import { api, getCode, setCode } from './api.js'

const FINISHED = ['submitted', 'solved', 'revealed']

const PHASE_LABEL = { waiting: 'Waiting', pretest: 'Pretest', practice: 'Practice', heldout: 'Final test', break: 'Break', done: 'Done' }
const draftKey = (qid) => `los_draft_${getCode()}_${qid}`
const loadDraft = (qid) => { try { return localStorage.getItem(draftKey(qid)) || '' } catch { return '' } }
const saveDraft = (qid, v) => { try { localStorage.setItem(draftKey(qid), v) } catch {} }

const editorTheme = EditorView.theme({
  '&': { backgroundColor: 'var(--editor-bg)', color: 'var(--editor-text)' },
  '.cm-content': { caretColor: 'var(--accent)', padding: '16px 0' },
  '.cm-gutters': { backgroundColor: 'var(--editor-bg)', color: 'var(--editor-gutter)', border: 'none', paddingLeft: '12px' },
  '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'var(--editor-line)' },
  '&.cm-focused .cm-cursor': { borderLeftColor: 'var(--accent)' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': { backgroundColor: 'color-mix(in srgb, var(--accent) 30%, transparent) !important' },
  '.cm-placeholder': { color: 'var(--editor-gutter)' },
})
const highlight = syntaxHighlighting(HighlightStyle.define([
  { tag: t.keyword, color: 'var(--kw)', fontWeight: '500' },
  { tag: [t.function(t.variableName), t.standard(t.name)], color: 'var(--fn)' },
  { tag: t.string, color: 'var(--str)' },
  { tag: t.number, color: 'var(--num)' },
  { tag: t.comment, color: 'var(--editor-gutter)', fontStyle: 'italic' },
]))

function friendly(e) {
  if (e.status === 503) return e.message
  if (!e.status || e.status >= 500) return "Can't reach the server right now. Your typing is saved on this computer, so wait a few seconds and try again."
  return e.message
}

export default function App() {
  const [me, setMe] = useState(null)
  const [err, setErr] = useState('')
  const [connecting, setConnecting] = useState(!!getCode())
  const [offset, setOffset] = useState(0)   // server clock - browser clock, in ms

  const refresh = useCallback(async () => {
    if (!getCode()) { setMe(null); setConnecting(false); return }
    try {
      const t0 = Date.now()
      const m = await api('/me')
      setOffset(Date.parse(m.server_now) - (t0 + Date.now()) / 2)
      setMe(m); setErr(''); setConnecting(false)
    }
    catch (e) {
      if (e.status === 401 || e.status === 403) { setCode(''); setMe(null); setConnecting(false); setErr(e.status === 403 ? e.message : '') }
      else setErr(friendly(e))
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])
  useEffect(() => { const id = setInterval(refresh, 8000); return () => clearInterval(id) }, [refresh])

  if (connecting && !me) return <Centered>Connecting… {err && <p className="mt-3 text-sm msg-warn px-3 py-2 rad">{err}</p>}</Centered>
  if (!getCode() || !me) return <Login onDone={refresh} notice={err} />
  return (
    <div className="h-full flex flex-col md:overflow-hidden">
      <header className="flex items-center justify-between px-6 min-h-[60px] bd-b flex-wrap gap-3 card">
        <div className="flex items-center gap-3">
          <span className="w-7 h-7 rad btn-accent inline-flex items-center justify-center f-head font-bold text-[15px]" aria-hidden="true">L</span>
          <span className="f-head font-bold text-lg tracking-tight">Learning OS</span>
          <span className="text-xs font-semibold px-2.5 py-1 rad btn-primary min-h-0">{PHASE_LABEL[me.phase]}</span>
        </div>
        <div className="flex items-center gap-4 text-sm t-muted">
          {me.deadline && <Countdown deadline={me.deadline} offset={offset} />}
          <span>Logged in as <b style={{ color: 'var(--text)' }}>{me.name}</b></span>
          <button className="btn btn-ghost" onClick={() => { setCode(''); setMe(null) }}>Log out</button>
        </div>
      </header>
      {err && <div className="px-6 py-2 text-sm msg-warn">{err}</div>}
      <Body key={me.phase} me={me} refresh={refresh} offset={offset} />
    </div>
  )
}

function useRemaining(deadline, offset) {
  // Computed synchronously from props on every render (never a stale value from a previous phase);
  // the interval only forces a re-render twice a second.
  const [, tick] = useState(0)
  useEffect(() => {
    if (!deadline) return
    const id = setInterval(() => tick((n) => n + 1), 500)
    return () => clearInterval(id)
  }, [deadline])
  return deadline ? Math.max(0, Date.parse(deadline) - (Date.now() + offset)) : null
}

function Countdown({ deadline, offset }) {
  const ms = useRemaining(deadline, offset)
  if (ms == null) return null
  const s = Math.ceil(ms / 1000)
  const low = s <= 120
  return (
    <span className={`f-mono text-base font-semibold px-2.5 py-1 rad ${low ? 'msg-err' : 'chip'}`} style={low ? undefined : { color: 'var(--text)' }}
      role="timer" aria-label={`${Math.floor(s / 60)} minutes ${s % 60} seconds left`}>
      {String(Math.floor(s / 60)).padStart(2, '0')}:{String(s % 60).padStart(2, '0')}
    </span>
  )
}

const INTRO = {
  pretest: ['Before we start',
    'These questions cover something you have not learned yet. Nobody is expected to solve them. They only show where you are starting from.',
    'Do what you can. Leaving a question blank is completely fine. You have 15 minutes. When the timer ends, whatever is in each editor is submitted automatically.',
    'Next comes a practice session where you can get help.'],
  practice: ['Practice',
    'Try each question yourself first. If you are stuck, use the "Get help" button. It is there for you.',
    'If you are stuck on one question for about 5 minutes, move on to the next. You have 45 minutes.'],
  heldout: ['Final test',
    'New questions, no help. Do what you can. Blanks are fine.',
    'You have 30 minutes. When the timer ends, whatever is in each editor is submitted automatically.'],
}

function Intro({ phase, onStart }) {
  const [title, ...lines] = INTRO[phase]
  return (
    <Centered>
      <div className="max-w-lg w-full card bd rad p-8 space-y-4 text-left shadowed" style={{ color: 'var(--text)' }}>
        <h2 className="f-head text-2xl font-bold">{title}</h2>
        {lines.map((l) => <p key={l} className="leading-relaxed">{l}</p>)}
        <button autoFocus onClick={onStart} className="btn btn-accent">Start</button>
      </div>
    </Centered>
  )
}

function Centered({ children }) {
  return <div className="h-full flex flex-col items-center justify-center t-muted px-4 text-center">{children}</div>
}

function Body({ me, refresh, offset }) {
  const isTest = me.phase === 'pretest' || me.phase === 'heldout'
  const allDone = me.questions.length > 0 && me.questions.every((x) => FINISHED.includes(me.status[x.id]))
  const introKey = `los_intro_${me.phase}`
  const [introSeen, setIntroSeen] = useState(() => { try { return sessionStorage.getItem(introKey) === '1' } catch { return false } })
  useEffect(() => { try { setIntroSeen(sessionStorage.getItem(introKey) === '1') } catch { setIntroSeen(false) } }, [introKey])
  const remaining = useRemaining(me.deadline, offset)
  const timeUp = remaining === 0
  const autoSent = useRef(false)

  // Test phases: at 0, submit whatever is in each unsubmitted editor (blank if nothing typed).
  useEffect(() => {
    if (!isTest || !timeUp || autoSent.current) return
    autoSent.current = true
    ;(async () => {
      for (const q of me.questions) {
        if (me.status[q.id] === 'submitted') continue
        for (let attempt = 0; attempt < 6; attempt++) {   // retry network/DB blips; stop on 409 (done) or 410 (too late)
          try { await api(`/questions/${q.id}/submit`, { method: 'POST', body: { sql: loadDraft(q.id) } }); break }
          catch (e) { if (e.status === 409 || e.status === 410) break; await new Promise((r) => setTimeout(r, 2000)) }
        }
      }
      refresh()
    })()
  }, [isTest, timeUp])   // eslint-disable-line react-hooks/exhaustive-deps

  if (me.phase === 'waiting') return <Centered>Welcome, {me.name}. Please wait. The invigilator will start the session.</Centered>
  if (me.questions.length === 0) {
    return <Centered>{me.phase === 'done' ? 'All done. Thank you for taking part!' : 'This part is finished. Please wait for the invigilator.'}</Centered>
  }
  if (isTest && timeUp && !allDone) return <Centered>Time is up. Submitting your answers…</Centered>
  if (me.phase === 'practice' && timeUp && !me.survey_done) return <Centered><span className="f-head text-2xl mb-4" style={{ color: 'var(--text)' }}>Practice time is up.</span><Survey refresh={refresh} /></Centered>
  if (!introSeen && INTRO[me.phase] && !timeUp && !allDone && !me.survey_done) return <Intro phase={me.phase} onStart={() => { try { sessionStorage.setItem(introKey, '1') } catch {} setIntroSeen(true) }} />
  if (isTest && allDone) return <Centered><span className="f-head text-2xl" style={{ color: 'var(--text)' }}>All answers submitted.</span><span className="mt-2">Please wait for the invigilator.</span></Centered>
  if (me.phase === 'practice' && me.survey_done) return <Centered><span className="f-head text-2xl" style={{ color: 'var(--text)' }}>Thanks, practice is finished.</span><span className="mt-2">Please wait for the invigilator.</span></Centered>
  return <Workspace key={me.phase} me={me} refresh={refresh} isTest={isTest} allDone={allDone} />
}

function Login({ onDone, notice }) {
  const [code, setC] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault(); if (busy) return
    setErr(''); setBusy(true)
    const c = code.trim().toLowerCase()
    try { await api('/login', { method: 'POST', body: { code: c } }); setCode(c); onDone() }
    catch (e) { setErr(e.status === 401 ? 'That code was not found. Check the slip you were given.' : friendly(e)) }
    setBusy(false)
  }
  return (
    <div className="h-full flex items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm card bd rad p-8 space-y-4 shadowed">
        <h1 className="f-head text-2xl font-bold">Learning OS · SQL</h1>
        <label className="block text-sm t-muted" htmlFor="code">Enter the code on your slip</label>
        <input id="code" autoFocus autoComplete="off" value={code} onChange={(e) => setC(e.target.value)} placeholder="abc123-def456"
          className="w-full bd rad px-3 py-2.5 f-mono focus:outline-none" style={{ outlineColor: 'var(--accent)' }} />
        {(err || notice) && <p className="text-sm msg-err px-3 py-2 rad">{err || notice}</p>}
        <button disabled={busy} className="btn btn-accent w-full justify-center">{busy ? 'Starting… (the server may take a moment to wake up)' : 'Start'}</button>
      </form>
    </div>
  )
}

function Workspace({ me, refresh, isTest }) {
  const [idx, setIdx] = useState(() => {
    const i = me.questions.findIndex((q) => !FINISHED.includes(me.status[q.id]))
    return i === -1 ? 0 : i
  })
  const q = me.questions[idx]
  const finished = me.questions.filter((x) => FINISHED.includes(me.status[x.id])).length
  // a question solved only after "Show solution" is finished but not counted as solved
  const done = me.questions.filter((x) => ['submitted', 'solved'].includes(me.status[x.id])).length
  const goNext = () => setIdx((cur) => {
    const n = me.questions.length
    for (let k = 1; k <= n; k++) {           // next question not finished yet, wrapping round
      const j = (cur + k) % n
      if (!FINISHED.includes(me.status[me.questions[j].id])) return j
    }
    return Math.min(cur + 1, n - 1)
  })

  useEffect(() => {      // tab-switch log, in practice too (reported per learner, never enforced)
    const send = (kind) => api('/event', { method: 'POST', body: { kind, qid: q.id } }).catch(() => {})
    const onVis = () => send(document.hidden ? 'hidden' : 'visible')
    const onBlur = () => send('blur')
    document.addEventListener('visibilitychange', onVis); window.addEventListener('blur', onBlur)
    return () => { document.removeEventListener('visibilitychange', onVis); window.removeEventListener('blur', onBlur) }
  }, [q.id])

  return (
    <div className="flex-1 flex flex-col md:flex-row min-h-0">
      <aside className="md:w-[38%] md:min-w-[340px] md:max-w-[540px] md:bd-r bd-b panel flex flex-col min-h-0 shrink-0">
        <nav className="flex flex-wrap gap-2 p-4 bd-b" aria-label="Questions">
          {me.questions.map((x, i) => {
            const s = me.status[x.id]
            const isDone = s === 'submitted' || s === 'solved'
            const isRevealed = s === 'revealed'
            return (
              <button key={x.id} onClick={() => setIdx(i)} className="qbtn" data-state={isDone ? 'done' : ''} data-current={i === idx ? '1' : ''}
                title={isRevealed ? 'Solution shown: not counted as solved' : undefined}
                aria-label={`Question ${i + 1}${isDone ? (isTest ? ', submitted' : ', solved') : isRevealed ? ', solution shown' : ''}`}>
                {isDone ? '✓' : isRevealed ? '–' : i + 1}
              </button>
            )
          })}
          <span className="ml-auto self-center text-xs t-muted">{done}/{me.questions.length} {isTest ? 'submitted' : 'solved'}</span>
        </nav>
        <div className="flex-1 overflow-auto p-6 space-y-6">
          <div className="space-y-3">
            <div className="text-xs uppercase tracking-widest font-semibold t-accent">Question {idx + 1} of {me.questions.length}</div>
            <Prompt text={q.prompt} />
            {isTest && <p className="text-xs t-muted">Test mode: you can run queries and see what they return, but you won't be told whether they're correct. Submit when you're ready. You can't change an answer after submitting.</p>}
            {!isTest && <p className="text-xs t-muted">Stuck for more than about 5 minutes? It's fine to move on to the next question and come back.</p>}
          </div>
          <Schema />
        </div>
      </aside>
      <main className="flex-1 min-w-0 flex flex-col min-h-[600px] md:min-h-0">
        <Editor key={q.id} q={q} me={me} isTest={isTest} refresh={refresh}
          onNext={goNext} />
        {me.phase === 'practice' && <FinishPractice refresh={refresh} open={finished === me.questions.length} />}
      </main>
    </div>
  )
}

function Prompt({ text }) {
  const [body, cols] = text.split(/\nColumns:\s*/)
  return (
    <>
      <p className="f-head text-[21px] leading-snug font-medium whitespace-pre-line">{body}</p>
      {cols && <p className="text-sm t-muted">Columns, in this order: <code className="f-mono chip px-1.5 py-0.5 rad text-[13px]" style={{ color: 'var(--text)' }}>{cols}</code></p>}
    </>
  )
}

function Schema() {
  const [s, setS] = useState(null)
  const [failed, setFailed] = useState(false)
  const load = useCallback(() => {
    setFailed(false)
    let tries = 0
    const go = () => api('/schema').then(setS).catch(() => { if (++tries < 4) setTimeout(go, 1500 * tries); else setFailed(true) })
    go()
  }, [])
  useEffect(load, [load])
  return (
    <section className="card bd rad p-4 space-y-3 shadowed" aria-label="Schema">
      <div className="flex justify-between text-sm font-semibold"><span>Schema</span><span className="t-muted font-normal f-mono">shop</span></div>
      {failed && <p className="text-sm msg-err px-3 py-2 rad">The schema didn't load. <button className="underline" onClick={load}>Retry</button></p>}
      {!s && !failed && <p className="text-sm t-muted">Loading…</p>}
      {s && <>
        <SchemaMap tables={s.tables} />
        <ul className="text-xs t-muted space-y-1 list-disc pl-4">{s.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      </>}
    </section>
  )
}

// The tables laid out by how they join, with the joining column on each link.
// Same for every learner in both arms.
const MAP = [
  ['T:customers', 'R:customer_id', 'T:orders', 'R:order_id', 'T:payments'],
  ['', '', 'D:order_id', '', ''],
  ['T:products', 'L:product_id', 'T:order_items', '', ''],
  ['D:category_id', '', '', '', ''],
  ['T:categories', '', '', '', ''],
]

function SchemaMap({ tables }) {
  const byName = Object.fromEntries(tables.map((t) => [t.table, t]))
  return (
    <div className="grid gap-y-1 f-mono text-[11px] leading-snug" style={{ gridTemplateColumns: 'minmax(0,1fr) 26px minmax(0,1fr) 26px minmax(0,1fr)' }}
      role="img" aria-label="How the tables join: customers to orders on customer_id; orders to payments and to order_items on order_id; order_items to products on product_id; products to categories on category_id">
      {MAP.flat().map((cell, i) => {
        const [kind, name] = cell.split(':')
        if (kind === 'T') {
          const t = byName[name]
          return (
            <div key={i} className="card bd rad px-2 py-1.5 min-w-0">
              <div className="f-head text-[13px] font-bold t-accent break-all">{name}</div>
              {t && t.columns.map((c) => (
                <div key={c.name} className="break-all">
                  {c.name}{c.key && <span className="t-muted"> {c.key}</span>}
                </div>
              ))}
            </div>
          )
        }
        if (kind === 'R' || kind === 'L') return (
          <div key={i} className="flex flex-col items-center justify-center t-muted" aria-hidden="true">
            <span className="text-base leading-none" style={{ color: 'var(--accent-text)' }}>⟷</span>
          </div>
        )
        if (kind === 'D') return (
          <div key={i} className="flex items-center justify-center gap-1 t-muted py-0.5" aria-hidden="true">
            <span className="text-base leading-none" style={{ color: 'var(--accent-text)' }}>↕</span><span className="text-[10px]">{name}</span>
          </div>
        )
        return <div key={i} aria-hidden="true" />
      })}
    </div>
  )
}

function Editor({ q, me, isTest, refresh, onNext }) {
  const submittedSql = (me.submitted_sql || {})[q.id]
  const status = me.status[q.id]
  const locked = isTest && status === 'submitted'
  const solved = !isTest && (status === 'solved' || status === 'revealed')
  const [code, setCodeText] = useState(() => (locked && submittedSql != null ? submittedSql : loadDraft(q.id)))
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [hints, setHints] = useState([])
  const [hintBusy, setHintBusy] = useState(false)
  const [canReveal, setCanReveal] = useState(false)
  const [confirmReveal, setConfirmReveal] = useState(false)
  const codeRef = useRef(code)
  codeRef.current = code
  const runRef = useRef(null)
  const hintEnd = useRef(null)

  useEffect(() => { api(`/questions/${q.id}/view`, { method: 'POST' }).catch(() => {}) }, [q.id])
  useEffect(() => {
    if (!me.help_available) return
    api(`/questions/${q.id}/hints`).then((d) => { setHints(d.hints); setCanReveal(d.reveal_available) }).catch(() => {})
  }, [q.id, me.help_available])
  useEffect(() => { hintEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [hints.length])
  useEffect(() => {   // Ctrl/Cmd+Enter runs the query even when focus is outside the editor
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !e.defaultPrevented && !e.target.closest?.('.cm-editor')) {
        e.preventDefault(); runRef.current?.()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const run = async () => {
    if (!codeRef.current.trim() || busy || locked) return
    setBusy(true)
    try {
      const r = await api(`/questions/${q.id}/run`, { method: 'POST', body: { sql: codeRef.current } })
      setRes(r)
      if (typeof r.reveal_available === 'boolean') setCanReveal(r.reveal_available)
      if (r.correct) refresh()
    } catch (e) { setRes({ error: friendly(e), infra: true }) }
    setBusy(false)
  }
  runRef.current = run

  const submit = async () => {
    setBusy(true)
    try { await api(`/questions/${q.id}/submit`, { method: 'POST', body: { sql: codeRef.current } }); await refresh(); onNext() }
    catch (e) { setRes({ error: friendly(e), infra: true }) }
    setBusy(false); setConfirm(false)
  }

  const reveal = async () => {
    setHintBusy(true); setConfirmReveal(false)
    try { const h = await api(`/questions/${q.id}/reveal`, { method: 'POST' }); setHints((x) => [...x, { text: h.text }]); setCanReveal(false) }
    catch (e) { setHints((x) => [...x, { text: friendly(e), error: true }]) }
    setHintBusy(false)
  }

  const help = async () => {
    setHintBusy(true)
    try { const h = await api(`/questions/${q.id}/help`, { method: 'POST' }); setHints((x) => [...x, { text: h.text }]); setCanReveal(h.reveal_available) }
    catch (e) { setHints((x) => [...x, { text: friendly(e), error: true }]) }
    setHintBusy(false)
  }

  const extensions = useMemo(() => [
    sqlLang({ dialect: PostgreSQL }), editorTheme, highlight, EditorView.lineWrapping,
    Prec.highest(keymap.of([{ key: 'Mod-Enter', run: () => { runRef.current?.(); return true } }])),
  ], [])

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex-[3] min-h-[200px]" style={{ background: 'var(--editor-bg)' }}>
        <CodeMirror value={code} height="100%" theme="none" extensions={extensions} editable={!locked}
          placeholder="Write your SELECT query here…" aria-label="SQL editor"
          basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: true, autocompletion: false, closeBrackets: false, searchKeymap: false }}
          onChange={(v) => { setCodeText(v); saveDraft(q.id, v) }} style={{ height: '100%' }} />
      </div>
      <div className="flex items-center gap-2 px-5 py-3 bd-b bd-t card flex-wrap">
        <button onClick={run} disabled={busy || locked} className="btn btn-accent">
          {busy ? 'Running…' : 'Run'} <span className="text-xs opacity-70 font-normal">Ctrl+Enter</span>
        </button>
        {isTest && !locked && (!confirm
          ? <button onClick={() => setConfirm(true)} disabled={busy} className="btn btn-outline">Submit answer</button>
          : <span className="flex items-center gap-2 text-sm flex-wrap">
              <span className="font-semibold">Submit {code.trim() ? 'this query' : 'a BLANK answer'}? You can't change it afterwards.</span>
              <button onClick={submit} className="btn btn-primary">Yes, submit</button>
              <button onClick={() => setConfirm(false)} className="btn btn-ghost">Cancel</button>
            </span>)}
        {locked && <span className="text-sm t-muted">Submitted. This is the answer you sent.</span>}
        {!isTest && (solved || res?.correct) && (
          <button onClick={onNext} className="btn btn-primary">Next question →</button>
        )}
        {me.help_available && canReveal && !(solved || res?.correct) && (!confirmReveal
          ? <button onClick={() => setConfirmReveal(true)} disabled={hintBusy} className="btn btn-ghost ml-auto">Show solution</button>
          : <span className="ml-auto flex items-center gap-2 text-sm flex-wrap">
              <span>Show the full solution? This question will then count as not solved.</span>
              <button onClick={reveal} className="btn btn-primary">Show it</button>
              <button onClick={() => setConfirmReveal(false)} className="btn btn-ghost">Keep trying</button>
            </span>)}
        {me.help_available && (
          <button onClick={help} disabled={hintBusy || solved || res?.correct}
            title={solved || res?.correct ? 'Already solved' : undefined}
            className={`btn btn-outline ${canReveal && !(solved || res?.correct) ? '' : 'ml-auto'}`}>
            {hintBusy ? 'Thinking…' : solved || res?.correct ? (status === 'revealed' ? 'Solution shown' : 'Solved ✓') : 'Get help'}
          </button>
        )}
      </div>
      <div className="flex-[4] min-h-0 flex flex-col lg:flex-row">
        <Result res={res} />
        {me.help_available && hints.length > 0 && (
          <div className="lg:w-[38%] lg:max-w-[440px] lg:bd-l bd-t overflow-auto p-4 space-y-3 min-h-0" aria-live="polite">
            {hints.map((h, i) => (
              <div key={i} className={`p-4 text-sm leading-relaxed ${h.error ? 'msg-err rad' : 'hint'}`}>
                {!h.error && <div className="text-xs uppercase tracking-widest font-semibold t-accent mb-2">Help {i + 1}</div>}
                <Rich text={h.text} />
              </div>
            ))}
            <div ref={hintEnd} />
          </div>
        )}
      </div>
    </div>
  )
}

// **bold** and `inline code`, rendered safely (no HTML from the model ever reaches the DOM)
function Inline({ text }) {
  const parts = text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**') && p.length > 4) return <strong key={i}>{p.slice(2, -2)}</strong>
    if (p.startsWith('`') && p.endsWith('`') && p.length > 2) return <code key={i} className="f-mono chip px-1 rad text-[0.92em]">{p.slice(1, -1)}</code>
    return p
  })
}

function Rich({ text }) {
  const parts = text.split(/```[A-Za-z0-9_+-]*[ \t]*\n?([\s\S]*?)```/g)
  return parts.map((p, i) => i % 2
    ? <CodeBlock key={i} code={p.trim()} />
    : <span key={i} className="whitespace-pre-wrap"><Inline text={p} /></span>)
}

function CodeBlock({ code }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => { try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch {} }
  return (
    <div className="my-2 rad overflow-hidden" style={{ background: 'var(--editor-bg)', color: 'var(--editor-text)' }}>
      <div className="flex justify-end px-2 pt-1"><button onClick={copy} className="text-xs underline opacity-80">{copied ? 'Copied' : 'Copy'}</button></div>
      <pre className="px-3 pb-3 f-mono text-xs whitespace-pre-wrap break-words">{code}</pre>
    </div>
  )
}

function Result({ res }) {
  if (!res) return <div className="flex-1 p-5 text-sm t-muted">Run a query to see what it returns here.</div>
  return (
    <div className="flex-1 min-w-0 flex flex-col min-h-0">
      {res.error && <div className={`px-5 py-2.5 text-sm ${res.infra ? 'msg-warn' : 'msg-err f-mono'}`}>{res.error}</div>}
      {'correct' in res && !res.error && (
        <div className={`px-5 py-2.5 text-sm font-medium ${res.correct ? 'msg-ok' : 'msg-warn'}`}>{res.feedback}</div>
      )}
      {res.columns && (
        <div className="flex-1 overflow-auto px-5">
          <table className="text-[13px] f-mono border-collapse">
            <thead className="sticky top-0 card">
              <tr>{res.columns.map((c, i) => <th key={i} className="text-left px-3 py-2 font-medium t-muted" style={{ borderBottom: '2px solid var(--text)' }}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {res.rows.map((r, i) => (
                <tr key={i}>
                  {r.map((v, j) => <td key={j} className="px-3 py-1.5 bd-b whitespace-nowrap">{v === null ? <span className="t-muted">NULL</span> : String(v)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="py-2 text-xs t-muted">{res.row_count}{res.truncated ? '+' : ''} row(s){res.truncated || res.row_count > 200 ? ' · showing the first 200' : ''}</div>
        </div>
      )}
    </div>
  )
}

function FinishPractice({ refresh, open }) {
  const [show, setShow] = useState(false)
  useEffect(() => { if (open) setShow(true) }, [open])
  if (!show) return (
    <div className="px-5 py-2 bd-t text-right">
      <button onClick={() => setShow(true)} className="text-xs t-muted underline">I'm finished with practice</button>
    </div>
  )
  return <div className="bd-t"><Survey refresh={refresh} onCancel={() => setShow(false)} /></div>
}

function Survey({ refresh, onCancel }) {
  const [v, setV] = useState(0)
  const [err, setErr] = useState('')
  const send = async () => {
    try { await api('/survey', { method: 'POST', body: { value: v } }); refresh() }
    catch (e) { setErr(friendly(e)) }
  }
  return (
    <div className="flex items-center justify-center p-6">
      <div className="max-w-md w-full card bd rad p-6 space-y-4 shadowed">
        <p className="f-head text-lg">One last question: how likely are you to open this tomorrow?</p>
        <div className="flex gap-2" role="radiogroup" aria-label="Likelihood from 1 to 5">
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} role="radio" aria-checked={v === n} onClick={() => setV(n)}
              className={`flex-1 btn justify-center ${v === n ? 'btn-accent' : 'btn-ghost'}`}>{n}</button>
          ))}
        </div>
        <div className="flex justify-between text-xs t-muted"><span>Not at all</span><span>Very likely</span></div>
        {err && <p className="text-sm msg-err px-3 py-2 rad">{err}</p>}
        <div className="flex gap-2">
          <button disabled={!v} onClick={send} className="btn btn-primary flex-1 justify-center">Send and finish practice</button>
          {onCancel && <button onClick={onCancel} className="btn btn-ghost">Keep practising</button>}
        </div>
      </div>
    </div>
  )
}
