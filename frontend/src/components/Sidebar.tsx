import { useEffect, useRef, useState } from 'react'

export interface TabDef {
  id: string
  label: string
  hint?: string
  icon: JSX.Element
}

const s = {
  width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: 1.9,
  strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
}

export const ICONS = {
  overview: (
    <svg {...s}>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </svg>
  ),
  models: (
    <svg {...s}>
      <path d="M12 3 3 7.5 12 12l9-4.5L12 3Z" />
      <path d="M3 16.5 12 21l9-4.5" />
      <path d="M3 12l9 4.5L21 12" />
    </svg>
  ),
  projects: (
    <svg {...s}>
      <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.5h7A1.5 1.5 0 0 1 19 10v7a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 3 17V7.5Z" />
    </svg>
  ),
  keys: (
    <svg {...s}>
      <circle cx="8" cy="12" r="3.4" />
      <path d="M11.4 12H21" />
      <path d="M17.5 12v3.2" />
      <path d="M20.4 12v2.2" />
    </svg>
  ),
  costs: (
    <svg {...s}>
      <path d="M12 2.8v18.4" />
      <path d="M16.5 7.2c-.7-1.4-2.4-2.2-4.5-2.2-2.5 0-4.2 1.2-4.2 3s1.6 2.6 4.2 3.2c2.9.7 4.6 1.5 4.6 3.4 0 2-1.9 3.2-4.6 3.2-2.3 0-4.1-.9-4.8-2.4" />
    </svg>
  ),
  billing: (
    <svg {...s}>
      <rect x="2.5" y="5" width="19" height="14" rx="2.5" />
      <path d="M2.5 10h19" />
      <path d="M6.5 15h4" />
    </svg>
  ),
  report: (
    <svg {...s}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6" />
      <path d="M9 17h4" />
    </svg>
  ),
  accounts: (
    <svg {...s}>
      <path d="M3 21v-1.5A4.5 4.5 0 0 1 7.5 15h3A4.5 4.5 0 0 1 15 19.5V21" />
      <circle cx="9" cy="8" r="3.4" />
      <path d="M17 21v-1.2a4 4 0 0 0-2.4-3.6" />
      <path d="M15.2 4.6a3.4 3.4 0 0 1 0 6.5" />
    </svg>
  ),
  rates: (
    <svg {...s}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9h18" />
      <path d="M9 9v11" />
    </svg>
  ),
}

/** Tab id lives in the URL hash, so a section is linkable and survives reload. */
export function useHashTab(ids: string[], fallback: string): [string, (id: string) => void] {
  const readHash = () => {
    const h = decodeURIComponent(window.location.hash.replace(/^#/, ''))
    return ids.includes(h) ? h : fallback
  }
  const [tab, setTabState] = useState(readHash)

  useEffect(() => {
    const onHash = () => setTabState(readHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
    // ids/fallback are module constants in practice
  }, [])

  const setTab = (id: string) => {
    setTabState(id)
    if (window.location.hash !== `#${id}`) window.location.hash = id
  }
  return [tab, setTab]
}

export function Sidebar({ tabs, active, onSelect, footer }:
  { tabs: TabDef[]; active: string; onSelect: (id: string) => void;
    footer?: React.ReactNode }) {
  const listRef = useRef<HTMLDivElement>(null)

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return
    e.preventDefault()
    const i = tabs.findIndex((t) => t.id === active)
    const next =
      e.key === 'Home' ? 0
      : e.key === 'End' ? tabs.length - 1
      : e.key === 'ArrowDown' ? (i + 1) % tabs.length
      : (i - 1 + tabs.length) % tabs.length
    onSelect(tabs[next].id)
    listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus()
  }

  return (
    <aside className="sidebar" aria-label="Dashboard sections">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 19V11" /><path d="M10 19V5" /><path d="M16 19v-6" /><path d="M22 19H2" />
          </svg>
        </span>
        <span className="brand-text">
          <span className="brand-name">OpenAI Usage</span>
          <span className="brand-sub">Cost Dashboard</span>
        </span>
      </div>

      <div ref={listRef} className="nav" role="tablist" aria-orientation="vertical"
           onKeyDown={onKeyDown}>
        {tabs.map((t) => {
          const selected = t.id === active
          return (
            <button
              key={t.id}
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={selected}
              aria-controls={`panel-${t.id}`}
              tabIndex={selected ? 0 : -1}
              className={'nav-item' + (selected ? ' active' : '')}
              onClick={() => onSelect(t.id)}
            >
              <span className="nav-icon">{t.icon}</span>
              <span className="nav-text">
                <span className="nav-label">{t.label}</span>
                {t.hint && <span className="nav-hint">{t.hint}</span>}
              </span>
            </button>
          )
        })}
      </div>

      {footer && <div className="sidebar-foot">{footer}</div>}
    </aside>
  )
}
