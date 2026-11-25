/** Web storage that never throws. A WebView2 document can be denied its storage, and then even reading
 *  `window.sessionStorage` (or `typeof sessionStorage`) throws a SecurityError (#91), so every storage access of the
 *  page goes through here: the property read and each call are caught, and what the store refuses is kept in memory
 *  for this page instead. */
export interface KeyStore { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void }

export function safeStorage(kind: 'localStorage' | 'sessionStorage', scope: object = globalThis): KeyStore {
  const memory = new Map<string, string>();
  const real = (): KeyStore | undefined => (scope as Record<string, KeyStore | undefined>)[kind];
  return {
    getItem(k) {
      try { const v = real()?.getItem(k); if (v != null) return v; } catch { /* denied: memory */ }
      return memory.get(k) ?? null;
    },
    setItem(k, v) {
      memory.set(k, v);
      try { real()?.setItem(k, v); } catch { /* kept in memory */ }
    },
    removeItem(k) {
      memory.delete(k);
      try { real()?.removeItem(k); } catch { /* nothing stored */ }
    },
  };
}
