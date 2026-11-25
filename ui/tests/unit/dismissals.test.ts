// Closed page alerts: closed with one click, they stay closed while their condition (key) lasts, also across a poll
// where the condition blinks off, and come back for a new condition or once it has been gone a while.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dismissals, FORGET_AFTER_MS } from '../../src/core/dismissals.ts';

function memoryStore() {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, removeItem: (k: string) => { m.delete(k); }, m };
}

test('a closed alert stays closed for its key and only for its key', () => {
  const d = dismissals(memoryStore());
  assert.equal(d.isDismissed('offline:10.0.0.5:timeout'), false);
  d.dismiss('offline:10.0.0.5:timeout');
  assert.equal(d.isDismissed('offline:10.0.0.5:timeout'), true);
  assert.equal(d.isDismissed('offline:10.0.0.5:refused'), false, 'another error is another condition');
});

test('a condition that blinks off for a poll does not bring it back', () => {
  let now = 1000;
  const d = dismissals(memoryStore(), () => now);
  d.dismiss('busy:a:dash:printing');
  d.gone('busy:a:dash:printing');
  now += 5000;   // one poll later the condition is there again
  d.back('busy:a:dash:printing');
  assert.equal(d.isDismissed('busy:a:dash:printing'), true);
});

test('a condition gone for a while is forgotten: the same problem coming back later shows again', () => {
  let now = 1000;
  const d = dismissals(memoryStore(), () => now);
  d.dismiss('stale:a');
  d.gone('stale:a');
  now += FORGET_AFTER_MS;
  d.back('stale:a');
  assert.equal(d.isDismissed('stale:a'), false);
});

test('keep: an informational alert stays closed for the session however long its condition was gone', () => {
  let now = 0;
  const d = dismissals(memoryStore(), () => now);
  d.dismiss('busy:a:dash:printing');
  d.gone('busy:a:dash:printing');
  now += 10 * FORGET_AFTER_MS;
  d.back('busy:a:dash:printing', Infinity);
  assert.equal(d.isDismissed('busy:a:dash:printing'), true);
});

test('the gone time counts from when it went, not from the last time it was seen gone', () => {
  let now = 0;
  const d = dismissals(memoryStore(), () => now);
  d.dismiss('k');
  d.gone('k');
  now += FORGET_AFTER_MS / 2;
  d.gone('k');   // told again: still the first time counts
  now += FORGET_AFTER_MS / 2;
  d.back('k');
  assert.equal(d.isDismissed('k'), false);
});

test('kept in the session store (a reload of the tab included), and in memory when the store refuses', () => {
  const store = memoryStore();
  dismissals(store).dismiss('k');
  assert.equal(dismissals(store).isDismissed('k'), true, 'a new page instance reads it back');
  const broken = { getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('denied'); }, removeItem: () => { throw new Error('denied'); } };
  const d = dismissals(broken);
  d.dismiss('k');
  assert.equal(d.isDismissed('k'), true);
  const none = dismissals(null);
  none.dismiss('k');
  assert.equal(none.isDismissed('k'), true);
});
