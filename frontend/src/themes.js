// Six themes. The study uses ONE (DEFAULT_THEME) for every learner in both arms.
// ?theme=<id> overrides it for previews only. Light/dark is the learner's own choice (button in the header),
// remembered per browser; it changes colours only, never layout or content, in both arms alike.
export const THEMES = {
  ember: {
    label: 'Ember', fonts: 'family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500',
    v: { bg: '#FFFFFF', panel: '#FAFAF9', card: '#FFFFFF', border: '#E7E5E4', text: '#0C0A09', muted: '#57534E',
      accent: '#FF6A00', onAccent: '#0C0A09', accentText: '#C2410C', primary: '#0C0A09', onPrimary: '#FFFFFF',
      editorBg: '#0C0A09', editorText: '#E7E5E4', editorGutter: '#57534E', editorLine: '#1C1917', kw: '#FF8A3D', fn: '#FDBA74', str: '#A3E635', num: '#FCD34D',
      warnBg: '#FFF7ED', warnText: '#9A3412', okBg: '#ECFDF5', okText: '#065F46', errBg: '#FEF2F2', errText: '#991B1B',
      hintBg: '#FFFFFF', hintBorder: '#0C0A09', chip: '#F5F5F4', radius: '10px',
      head: "'Space Grotesk', Inter, sans-serif", sans: 'Inter, sans-serif', mono: "'JetBrains Mono', ui-monospace, monospace" } },
  terminal: {
    label: 'Terminal', fonts: 'family=IBM+Plex+Mono:wght@400;500;600',
    v: { bg: '#070B08', panel: '#070B08', card: '#0B120D', border: '#1B3322', text: '#CFEBD6', muted: '#7FA88A',
      accent: '#39FF88', onAccent: '#04140A', accentText: '#39FF88', primary: '#39FF88', onPrimary: '#04140A',
      editorBg: '#030604', editorText: '#CFEBD6', editorGutter: '#2F5A3C', editorLine: '#0C1A10', kw: '#39FF88', fn: '#FFD866', str: '#7CE0FF', num: '#FFB000',
      warnBg: '#1A1606', warnText: '#FFD866', okBg: '#06200F', okText: '#39FF88', errBg: '#250A0A', errText: '#FF8A8A',
      hintBg: '#0B120D', hintBorder: '#FFD866', chip: '#0F1A12', radius: '0px',
      head: "'IBM Plex Mono', monospace", sans: "'IBM Plex Mono', monospace", mono: "'IBM Plex Mono', monospace" } },
  paper: {
    label: 'Paper', fonts: 'family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@400',
    v: { bg: '#F6F1E7', panel: '#F6F1E7', card: '#FFFDF8', border: '#DDD2BC', text: '#1F2A44', muted: '#5B6478',
      accent: '#A61E25', onAccent: '#FFFFFF', accentText: '#A61E25', primary: '#1F2A44', onPrimary: '#F6F1E7',
      editorBg: '#FFFDF8', editorText: '#1F2A44', editorGutter: '#B9AD94', editorLine: '#F3ECDD', kw: '#2747A8', fn: '#8A4B08', str: '#2F6B3B', num: '#A61E25',
      warnBg: '#FBEFD9', warnText: '#7A3E00', okBg: '#E5F1E3', okText: '#1F5B2A', errBg: '#F8E1E1', errText: '#8B1A1F',
      hintBg: '#FFF6D6', hintBorder: '#E8D79A', chip: '#EFE7D6', radius: '6px',
      head: 'Fraunces, Georgia, serif', sans: "'Source Sans 3', sans-serif", mono: "'JetBrains Mono', ui-monospace, monospace" } },
  blueprint: {
    label: 'Blueprint', fonts: 'family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500',
    v: { bg: '#0B1A33', panel: '#0B1A33', card: '#0F2242', border: '#23406E', text: '#E6EEF9', muted: '#9FB3D1',
      accent: '#5CC8FF', onAccent: '#04122A', accentText: '#5CC8FF', primary: '#5CC8FF', onPrimary: '#04122A',
      editorBg: '#071226', editorText: '#E6EEF9', editorGutter: '#3A5C92', editorLine: '#0F2242', kw: '#5CC8FF', fn: '#FFC46B', str: '#7CF5D0', num: '#FFC46B',
      warnBg: '#2A2410', warnText: '#FFC46B', okBg: '#0C2E2A', okText: '#7CF5D0', errBg: '#3A1420', errText: '#FF9DB0',
      hintBg: '#0F2242', hintBorder: '#FFC46B', chip: '#16305A', radius: '2px',
      head: "'IBM Plex Sans', sans-serif", sans: "'IBM Plex Sans', sans-serif", mono: "'IBM Plex Mono', monospace", grid: true } },
  brutalist: {
    label: 'Brutalist', fonts: 'family=Archivo+Black&family=Archivo:wght@400;600&family=Space+Mono:wght@400;700',
    v: { bg: '#FFFFFF', panel: '#FFFFFF', card: '#FFFFFF', border: '#000000', text: '#000000', muted: '#333333',
      accent: '#FFE600', onAccent: '#000000', accentText: '#000000', primary: '#000000', onPrimary: '#FFFFFF',
      editorBg: '#000000', editorText: '#FFFFFF', editorGutter: '#777777', editorLine: '#222222', kw: '#FFE600', fn: '#FF7AC6', str: '#7CFFB2', num: '#7CC8FF',
      warnBg: '#FFF4B8', warnText: '#000000', okBg: '#C8FFD9', okText: '#000000', errBg: '#FFE0E0', errText: '#000000',
      hintBg: '#FFE600', hintBorder: '#000000', chip: '#F0F0F0', radius: '0px', borderW: '2px',
      head: "'Archivo Black', sans-serif", sans: 'Archivo, sans-serif', mono: "'Space Mono', monospace" } },
  studio: {
    label: 'Studio', fonts: 'family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500',
    v: { bg: '#F4F3FB', panel: '#FFFFFF', card: '#FFFFFF', border: '#E4E1F5', text: '#24213A', muted: '#625D80',
      accent: '#5847E0', onAccent: '#FFFFFF', accentText: '#5847E0', primary: '#5847E0', onPrimary: '#FFFFFF',
      editorBg: '#1E1B33', editorText: '#E4E1F5', editorGutter: '#5D5880', editorLine: '#2A2647', kw: '#B3A8FF', fn: '#FFB38A', str: '#8EE6B5', num: '#FFB38A',
      warnBg: '#FFF4E5', warnText: '#8A4B08', okBg: '#DDF5E8', okText: '#13643B', errBg: '#FDE8EC', errText: '#9B1C31',
      hintBg: '#ECE9FE', hintBorder: '#ECE9FE', chip: '#F4F3FB', radius: '14px',
      head: "'Plus Jakarta Sans', sans-serif", sans: "'Plus Jakarta Sans', sans-serif", mono: "'JetBrains Mono', ui-monospace, monospace" } },
}

export const DEFAULT_THEME = import.meta.env.VITE_THEME || 'ember'

// Dark variant of each light theme that needs one (same fonts, radius and layout; colours only).
const DARK = {
  ember: { bg: '#121110', panel: '#161514', card: '#1B1918', border: '#2F2C2A', text: '#F5F5F4', muted: '#A8A29E',
    accent: '#FF6A00', onAccent: '#0C0A09', accentText: '#FF8A3D', primary: '#F5F5F4', onPrimary: '#0C0A09',
    editorBg: '#0B0A09', editorText: '#E7E5E4', editorGutter: '#57534E', editorLine: '#1C1917', kw: '#FF8A3D', fn: '#FDBA74', str: '#A3E635', num: '#FCD34D',
    warnBg: '#2B1A0B', warnText: '#FDBA74', okBg: '#0E2A1E', okText: '#6EE7B7', errBg: '#2E1415', errText: '#FCA5A5',
    hintBg: '#1B1918', hintBorder: '#78716C', chip: '#24211F' },
}

const MODE_KEY = 'los_mode'
let current = { id: DEFAULT_THEME, mode: 'light' }

function systemMode() {
  try { return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light' } catch { return 'light' }
}

export function getMode() { return current.mode }
export function canToggle() { return !!DARK[current.id] }

function paint() {
  const t = THEMES[current.id] || THEMES.ember
  const v = current.mode === 'dark' && DARK[current.id] ? { ...t.v, ...DARK[current.id] } : t.v
  const root = document.documentElement
  for (const [k, val] of Object.entries(v)) {
    if (typeof val === 'string') root.style.setProperty('--' + k.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase()), val)
  }
  root.style.setProperty('--border-w', v.borderW || '1px')
  const dark = current.mode === 'dark' || ['terminal', 'blueprint'].includes(current.id)
  root.style.colorScheme = dark ? 'dark' : 'light'      // native scrollbars, checkboxes, inputs follow
  root.dataset.mode = dark ? 'dark' : 'light'
  let meta = document.querySelector('meta[name="theme-color"]')
  if (!meta) { meta = document.createElement('meta'); meta.name = 'theme-color'; document.head.appendChild(meta) }
  meta.content = v.card
}

export function setMode(mode) {
  if (!DARK[current.id] || mode === current.mode) return
  const root = document.documentElement
  let reduce = false
  try { reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches } catch {}
  if (!reduce) {
    root.classList.add('theme-anim')
    clearTimeout(setMode._t)
    setMode._t = setTimeout(() => root.classList.remove('theme-anim'), 400)
  }
  current = { ...current, mode }
  try { localStorage.setItem(MODE_KEY, mode) } catch {}
  paint()
  window.dispatchEvent(new CustomEvent('los-mode', { detail: mode }))
}

export function applyTheme() {
  let id = DEFAULT_THEME
  try { const q = new URLSearchParams(window.location.search).get('theme'); if (q && THEMES[q]) id = q } catch {}
  if (!THEMES[id]) id = 'ember'
  let mode = systemMode()
  try { const m = localStorage.getItem(MODE_KEY); if (m === 'light' || m === 'dark') mode = m } catch {}
  current = { id, mode: DARK[id] ? mode : 'light' }
  paint()
  const root = document.documentElement
  root.dataset.theme = id
  if (THEMES[id].v.grid) root.dataset.grid = '1'
  const link = document.createElement('link')
  link.rel = 'stylesheet'
  link.href = `https://fonts.googleapis.com/css2?${THEMES[id].fonts}&display=swap`
  document.head.appendChild(link)
  return id
}
