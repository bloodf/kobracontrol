// #91: a WebView2 document denied its storage throws a SecurityError on merely reading window.sessionStorage.
// The page must still load, and what it stores is kept in memory for the page instead.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { safeStorage } from '../../src/core/storage.ts';

const denied = () => { throw new DOMException('Access is denied for this document.', 'SecurityError'); };
const deniedScope = () => Object.defineProperties({}, { sessionStorage: { get: denied }, localStorage: { get: denied } });

test('a store whose property read throws keeps values in memory', () => {
  for (const kind of ['sessionStorage', 'localStorage'] as const) {
    const s = safeStorage(kind, deniedScope());
    assert.equal(s.getItem('k'), null);
    s.setItem('k', 'v');
    assert.equal(s.getItem('k'), 'v');
    s.removeItem('k');
    assert.equal(s.getItem('k'), null);
  }
});

test('a store whose calls throw (quota, denied) keeps values in memory', () => {
  const broken = { getItem: denied, setItem: denied, removeItem: denied };
  const s = safeStorage('sessionStorage', { sessionStorage: broken });
  s.setItem('k', 'v');
  assert.equal(s.getItem('k'), 'v');
});

test('a working store is used', () => {
  const m = new Map<string, string>([['old', '1']]);
  const store = { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, removeItem: (k: string) => { m.delete(k); } };
  const s = safeStorage('localStorage', { localStorage: store });
  assert.equal(s.getItem('old'), '1', 'reads what an earlier visit stored');
  s.setItem('k', 'v');
  assert.equal(m.get('k'), 'v');
  s.removeItem('old');
  assert.equal(m.has('old'), false);
});

test('the alerts module loads and works when reading sessionStorage throws (the blank tab of #91)', async () => {
  Object.defineProperty(globalThis, 'sessionStorage', { get: denied, configurable: true });
  try {
    const { alerts } = await import('../../src/core/dismissals.ts?denied');
    alerts.dismiss('offline:a:timeout');
    assert.equal(alerts.isDismissed('offline:a:timeout'), true);
  } finally {
    delete (globalThis as { sessionStorage?: unknown }).sessionStorage;
  }
});
