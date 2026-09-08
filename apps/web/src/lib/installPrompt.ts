/**
 * S1.14: PWA install prompt.
 *
 * Chromium fires `beforeinstallprompt` when the app is installable; we defer
 * the event, surface an install affordance in the top bar, and call prompt()
 * when the user taps it. Once installed (or running standalone) the UI hides.
 */

export interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

let deferred: InstallPromptEvent | null = null
let wasInstalled = false
const listeners = new Set<() => void>()

function notify() {
  listeners.forEach((fn) => fn())
}

export function onInstallChange(fn: () => void): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

export function installed(): boolean {
  if (wasInstalled) return true
  try {
    return window.matchMedia('(display-mode: standalone)').matches === true
  } catch {
    return false
  }
}

export function canInstall(): boolean {
  return deferred !== null && !installed()
}

export async function promptInstall(): Promise<'accepted' | 'dismissed' | 'unavailable'> {
  if (!deferred) return 'unavailable'
  const evt = deferred
  await evt.prompt()
  const choice = await evt.userChoice
  deferred = null
  notify()
  return choice.outcome
}

/** Call once at boot; safe in SSR/jsdom. */
export function initInstallPrompt(): void {
  if (typeof window === 'undefined') return
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()
    deferred = e as InstallPromptEvent
    notify()
  })
  window.addEventListener('appinstalled', () => {
    deferred = null
    wasInstalled = true
    notify()
  })
  try {
    window.matchMedia('(display-mode: standalone)').addEventListener?.('change', notify)
  } catch {
    /* Safari without matchMedia listeners: standalone detection stays static */
  }
}
