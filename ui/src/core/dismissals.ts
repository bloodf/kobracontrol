/** Closed page alerts (KcAlert). One click closes an alert for its key, the condition it is about ("offline:<address>:
 *  <error>"); a new or different condition has another key and shows. The condition blinking off for a poll or two
 *  does not bring it back: a closed alert is forgotten only once its condition has been gone FORGET_AFTER_MS, so the
 *  same problem coming back later shows again. Kept for the session (sessionStorage: a reload of the tab included),
 *  in memory when the store refuses. */
import { safeStorage, type KeyStore } from './storage.ts';

export type { KeyStore };
export const FORGET_AFTER_MS = 60_000;
const PREFIX = 'kc-alert:';

export function dismissals(store: KeyStore | null, now: () => number = Date.now) {
  const closed = new Set<string>();             // this page's closes, also when the store refuses
  const goneSince = new Map<string, number>();  // key -> when its condition went away
  const stored = (key: string) => { try { return store?.getItem(PREFIX + key) === '1'; } catch { return false; } };
  const isDismissed = (key: string) => closed.has(key) || stored(key);
  return {
    isDismissed,
    dismiss(key: string): void {
      closed.add(key);
      goneSince.delete(key);
      try { store?.setItem(PREFIX + key, '1'); } catch { /* kept in memory */ }
    },
    /** The alert's condition went away (its `show` turned false). */
    gone(key: string): void {
      if (isDismissed(key) && !goneSince.has(key)) goneSince.set(key, now());
    },
    /** The condition is there again: forgotten if it was gone at least `after` ms (Infinity: never, for the session). */
    back(key: string, after = FORGET_AFTER_MS): void {
      const since = goneSince.get(key);
      goneSince.delete(key);
      if (since === undefined || now() - since < after) return;
      closed.delete(key);
      try { store?.removeItem(PREFIX + key); } catch { /* nothing stored */ }
    },
  };
}

/** The page's one list of closed alerts. */
export const alerts = dismissals(safeStorage('sessionStorage'));
