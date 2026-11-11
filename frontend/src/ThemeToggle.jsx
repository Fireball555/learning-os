import { useEffect, useState } from 'react'
import { canToggle, getMode, setMode } from './themes.js'

// Light/dark switch. Colours only; nothing about the task, hints or timing changes.
export default function ThemeToggle({ className = '' }) {
  const [mode, setM] = useState(getMode())
  useEffect(() => {
    const on = (e) => setM(e.detail)
    window.addEventListener('los-mode', on)
    return () => window.removeEventListener('los-mode', on)
  }, [])
  if (!canToggle()) return null
  const dark = mode === 'dark'
  const label = dark ? 'Switch to light mode' : 'Switch to dark mode'
  return (
    <button type="button" onClick={() => setMode(dark ? 'light' : 'dark')} aria-label={label} title={label}
      className={`btn btn-ghost theme-toggle ${className}`} data-dark={dark ? '1' : '0'}>
      <span className="tt-icon" aria-hidden="true">
        {/* sun */}
        <svg className="tt-sun" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6" />
        </svg>
        {/* moon */}
        <svg className="tt-moon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7z" />
        </svg>
      </span>
    </button>
  )
}
