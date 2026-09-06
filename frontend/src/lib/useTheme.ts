import { useCallback, useEffect, useState } from 'react'

const TOKENS = [
  'series-1', 'series-2', 'series-3', 'series-4', 'series-5', 'series-6',
  'surface-1', 'surface-2', 'grid', 'axis',
  'text-primary', 'text-secondary', 'text-muted',
  'good', 'warning', 'critical',
] as const

export type Tokens = Record<(typeof TOKENS)[number], string>

/** Recharts writes colours as SVG *attributes*, where `var(--x)` is not reliably
 *  resolved. So read the computed values off :root and hand real hex to the
 *  charts - re-reading whenever the theme changes. */
export function useTokens(): Tokens {
  const read = useCallback((): Tokens => {
    const cs = getComputedStyle(document.documentElement)
    const out = {} as Tokens
    for (const t of TOKENS) {
      out[t] = cs.getPropertyValue(`--${t}`).trim() || '#888888'
    }
    return out
  }, [])

  const [tokens, setTokens] = useState<Tokens>(read)

  useEffect(() => {
    const refresh = () => setTokens(read())
    refresh()

    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', refresh)

    // the in-app toggle stamps data-theme on <html>
    const obs = new MutationObserver(refresh)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

    return () => {
      mq.removeEventListener('change', refresh)
      obs.disconnect()
    }
  }, [read])

  return tokens
}

export type ThemeMode = 'system' | 'light' | 'dark'

export function useThemeMode(): [ThemeMode, (m: ThemeMode) => void] {
  const [mode, setMode] = useState<ThemeMode>(() => {
    try {
      return (localStorage.getItem('theme') as ThemeMode) || 'system'
    } catch {
      return 'system'
    }
  })

  useEffect(() => {
    const root = document.documentElement
    if (mode === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', mode)
    try {
      localStorage.setItem('theme', mode)
    } catch {
      /* private mode - the choice just won't persist */
    }
  }, [mode])

  return [mode, setMode]
}
