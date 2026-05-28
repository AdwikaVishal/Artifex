// Simple app state - no external dependencies
// Using a simple object + React's built-in useState/useSyncExternalStore

let sidebarOpen = true

const listeners = new Set<() => void>()

function notify() {
  listeners.forEach((l) => l())
}

export function getSidebarOpen() {
  return sidebarOpen
}

export function setSidebarOpen(open: boolean) {
  sidebarOpen = open
  notify()
}

export function subscribeToSidebar(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
