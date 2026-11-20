// The command tracker (B-04/B-05): one per action, unknown after the timeout, no automatic retry, late answers.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Tracker } from '../../src/core/tracker.ts';

function setup() {
  let now = 0;
  const timers: { at: number; fn: () => void }[] = [];
  const sends: { cmd: string; resolve: (v: unknown) => void; reject: (e: unknown) => void }[] = [];
  const clock = { now: () => now, setTimeout: (fn: () => void, ms: number) => { timers.push({ at: now + ms, fn }); return 0; } };
  // What the page's toasts would show: one per key (a keyed toast replaces the one with the same key).
  let shown: { kind: string; text: string; key?: string }[] = [];
  const show = (kind: string, text: string, key?: string) => { shown = [...shown.filter(n => !key || n.key !== key), { kind, text, key }]; };
  const tr = new Tracker((cmd) => new Promise((resolve, reject) => sends.push({ cmd, resolve, reject })), (k, p) => `${k} ${JSON.stringify(p)}`, show, clock);
  const advance = async (ms: number) => { now += ms; for (const t of timers.filter(t => t.at <= now)) { timers.splice(timers.indexOf(t), 1); t.fn(); } await new Promise(r => setImmediate(r)); };
  return { tr, sends, advance, shown: () => shown };
}

test('a second press while waiting sends nothing; success clears the pending state', async () => {
  const { tr, sends, shown } = setup();
  const a = tr.run({ key: 'pause', label: 'Pause', cmd: 'pause', okText: 'Pausing' });
  assert.deepEqual(await tr.run({ key: 'pause', label: 'Pause', cmd: 'pause' }), { ok: false, reason: 'busy' });
  assert.equal(sends.length, 1); assert.ok(tr.isBusy('pause'));
  sends[0].resolve(true);
  assert.deepEqual(await a, { ok: true, result: true });
  assert.ok(!tr.isBusy('pause'));
  assert.deepEqual(shown(), [{ kind: 'success', text: 'Pausing', key: 'pause' }]);
});

test('no answer: unknown outcome that stays, no retry; a late answer replaces it', async () => {
  const { tr, sends, advance, shown } = setup();
  const a = tr.run({ key: 'cancel', label: 'Cancel', cmd: 'cancel', timeoutMs: 15000 });
  await advance(15000);
  assert.deepEqual(await a, { ok: false, reason: 'timeout' });
  assert.equal(sends.length, 1, 'never retried');
  assert.equal(shown().length, 1); assert.equal(shown()[0].kind, 'unknown');
  await advance(60000);
  assert.equal(shown()[0].kind, 'unknown', 'still shown');
  assert.ok(!tr.isBusy('cancel'), 'the user may decide again');
  sends[0].reject(new Error('printer busy'));
  await advance(0);
  assert.equal(shown().length, 1, 'the late answer replaces the unknown'); assert.equal(shown()[0].kind, 'error');
  assert.match(shown()[0].text, /msg.lateError/);
});

test('errors are reported; E-stop may be pressed again while waiting', async () => {
  const { tr, sends, shown } = setup();
  const e1 = tr.run({ key: 'estop', label: 'E-stop', cmd: 'emergency_stop', allowRepeat: true });
  const e2 = tr.run({ key: 'estop', label: 'E-stop', cmd: 'emergency_stop', allowRepeat: true });
  assert.equal(sends.length, 2);
  sends[0].reject(new Error('unreachable')); sends[1].resolve(true);
  await e1; await e2;
  assert.equal(sends.length, 2);
  assert.match(shown().find(n => n.kind === 'error')?.text ?? '', /msg.failed/);
  assert.ok(!tr.isBusy('estop'));
});

test('{confirmed: false} shows the "sent, waiting" text, not success; {confirmed: true} and other answers show success', async () => {
  const { tr, sends, shown } = setup();
  const a = tr.run({ key: 'a', label: 'A', cmd: 'a', okText: 'done', sentText: 'sent' });
  sends[0].resolve({ confirmed: false }); await a;
  assert.deepEqual(shown().map(n => [n.kind, n.text]), [['info', 'sent']]);
  const b = tr.run({ key: 'b', label: 'B', cmd: 'b', okText: 'done', sentText: 'sent' });
  sends[1].resolve({ confirmed: true }); await b;
  const c = tr.run({ key: 'c', label: 'C', cmd: 'c', okText: 'done', sentText: 'sent' });
  sends[2].resolve(true); await c;
  assert.deepEqual(shown().map(n => [n.kind, n.text]), [['info', 'sent'], ['success', 'done'], ['success', 'done']]);
});
