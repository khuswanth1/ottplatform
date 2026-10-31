import { useSyncExternalStore } from 'react'

export const COUNTRIES = [
  ['IN', 'India'], ['US', 'United States'], ['GB', 'United Kingdom'], ['CA', 'Canada'], ['AU', 'Australia'],
  ['DE', 'Germany'], ['FR', 'France'], ['ES', 'Spain'], ['IT', 'Italy'], ['BR', 'Brazil'], ['MX', 'Mexico'],
  ['JP', 'Japan'], ['KR', 'South Korea'], ['AE', 'United Arab Emirates'], ['SG', 'Singapore'], ['ZA', 'South Africa'],
]
const KEY = 'ott.country'
const DEFAULT = 'IN' // initial region; users can change it
const listeners = new Set()

export function getCountry() {
  try {
    const v = localStorage.getItem(KEY)
    return COUNTRIES.some(([c]) => c === v) ? v : DEFAULT
  } catch { return DEFAULT }
}
export function setCountry(code) {
  try { localStorage.setItem(KEY, code) } catch { /* private mode: keep default */ }
  listeners.forEach((l) => l())
}
const subscribe = (l) => { listeners.add(l); return () => listeners.delete(l) }
export const useCountry = () => useSyncExternalStore(subscribe, getCountry, () => DEFAULT)
