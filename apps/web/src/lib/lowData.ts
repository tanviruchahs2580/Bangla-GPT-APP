/**
 * S1.13: low-data mode. Persisted in localStorage; an attribute on <html>
 * lets CSS drop images app-wide, and the tutor request body carries the flag
 * so answers come back short (measured by backend tests).
 */

const KEY = 'bgpt-lowdata'
type Listener = () => void
const listeners = new Set<Listener>()

function apply(on: boolean) {
  if (typeof document !== 'undefined') {
    if (on) document.documentElement.dataset.lowdata = '1'
    else delete document.documentElement.dataset.lowdata
  }
  listeners.forEach((fn) => fn())
}

export function getLowData(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function setLowData(on: boolean) {
  try {
    localStorage.setItem(KEY, on ? '1' : '0')
  } catch {
    /* private mode: setting still applies for this session */
  }
  apply(on)
}

export function toggleLowData(): boolean {
  setLowData(!getLowData())
  return getLowData()
}

export function onLowDataChange(fn: Listener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** Call once at boot so the attribute matches storage. */
export function initLowData() {
  apply(getLowData())
}
