// Pure rules of the page (node --test runs this TypeScript directly).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseTarget, parseWhole, family, hexOf, groupSlots, skippable, thumbSrc, boundSlots, listFiles, clipLength, fingerprintText, finishAt, heaterPhase } from '../../src/core/logic.ts';
import { normalizeLocale, resolveLocale, interpolate } from '../../src/core/i18n-core.ts';

test('a blank target is never 0; 0 typed is Off; out of range refused', () => {
  assert.deepEqual(parseTarget('', 300), { kind: 'empty' });
  assert.deepEqual(parseTarget(null, 300), { kind: 'empty' });
  assert.deepEqual(parseTarget(0, 300), { kind: 'off' });
  assert.deepEqual(parseTarget('215,4', 300), { kind: 'heat', value: 215 });
  assert.deepEqual(parseTarget(999, 300), { kind: 'invalid' });
  assert.deepEqual(parseTarget(101, 100), { kind: 'invalid' });
  assert.deepEqual(parseTarget(-1, 300), { kind: 'invalid' });
  assert.deepEqual(parseTarget('abc', 300), { kind: 'invalid' });
});

test('whole numbers inside a range; blank and text are null', () => {
  assert.equal(parseWhole('', 30, 80), null);
  assert.equal(parseWhole(null, 30, 80), null);
  assert.equal(parseWhole(29, 30, 80), null);
  assert.equal(parseWhole(81, 30, 80), null);
  assert.equal(parseWhole('45,4', 30, 80), 45);
  assert.equal(parseWhole('x', 30, 80), null);
});

test('material family ignores suffixes', () => {
  assert.equal(family('PLA+'), 'PLA');
  assert.equal(family('pla-cf'), 'PLA');
  assert.equal(family(''), '');
});

test('slot colour [r,g,b] becomes #rrggbb; malformed is blank', () => {
  assert.equal(hexOf([255, 0, 16]), '#ff0010');
  assert.equal(hexOf([255, 0, 16, 128]), '#ff0010');
  assert.equal(hexOf([300, -5, 0]), '#ff0000');
  assert.equal(hexOf([1, 2]), '');
  assert.equal(hexOf(null), '');
  assert.equal(hexOf(['a', 0, 0]), '');
});

test('slots group by box, ACE units by id, then the spool holder, slots by index', () => {
  const sl = (g: number, box: number, i: number) => ({ global_index: g, box_id: box, index: i });
  const groups = groupSlots([sl(7, 1, 0), sl(1, -1, 1), sl(0, -1, 0), sl(3, 0, 0)]);
  assert.deepEqual(groups.map(g => [g.boxId, g.slots.map(s => s.global_index)]), [[0, [3]], [1, [7]], [-1, [0, 1]]]);
  assert.deepEqual(groupSlots([]), []);
});

test('skippable objects: the printer’s objects minus the skipped ones', () => {
  assert.deepEqual(skippable(['a', 'b', 'c', 'a', ''], ['b']), ['a', 'c']);
  assert.deepEqual(skippable([], []), []);
  assert.deepEqual(skippable(null, null), []);
  assert.deepEqual(skippable(['x', 3, null], 'y'), ['x']);
});

test('thumbnails: data URL as is, bare base64 as PNG, junk nothing', () => {
  assert.equal(thumbSrc('data:image/png;base64,AAAA'), 'data:image/png;base64,AAAA');
  assert.equal(thumbSrc('iVBORw0KGgo='), 'data:image/png;base64,iVBORw0KGgo=');
  assert.equal(thumbSrc('<script>'), '');
  assert.equal(thumbSrc(undefined), '');
});

test('bound spools: the live status wins; a null live value unbinds', () => {
  assert.deepEqual(boundSlots({ 0: 7, 1: null }, { '1': 9, '2': 11 }), { 0: 7, 2: 11 });
  assert.deepEqual(boundSlots({}, { '3': 5 }), { 3: 5 });
});

test('locale resolution: explicit choice, host, browser, English', () => {
  const cases: [unknown, string | null][] = [['pt_BR', 'pt-BR'], ['en-GB', 'en'], ['es', 'es'], ['es_ES', 'es'], ['es-419', 'es'],
    ['de', 'de'], ['de_AT', 'de'], ['zh_CN', 'zh-CN'], ['zh_TW', 'zh-CN'], ['zh-Hant-TW', 'zh-CN'], ['pl', 'pl'], ['pl_PL', 'pl'], ['pl-PL', 'pl'], ['PL', 'pl'], ['fr', null], ['', null], [null, null]];
  for (const [code, want] of cases) assert.equal(normalizeLocale(code), want, String(code));
  assert.equal(resolveLocale('pt-BR', 'en', ['en']), 'pt-BR');
  assert.equal(resolveLocale('de', 'zh_CN', ['es']), 'de');
  assert.equal(resolveLocale('auto', 'pt', ['en']), 'pt-BR');
  assert.equal(resolveLocale('auto', 'zh_TW', ['en']), 'zh-CN');
  assert.equal(resolveLocale('auto', 'pl_PL', ['en']), 'pl');
  assert.equal(resolveLocale('auto', null, ['fr', 'pl-PL']), 'pl');
  assert.equal(resolveLocale('auto', 'ja', ['fr', 'es-MX']), 'es');
  assert.equal(resolveLocale('auto', null, ['fr']), 'en');
  assert.equal(interpolate('{a} and {b}', { a: 1 }), '1 and {b}');
});

test('files: search ignores case and spaces around it; the four orders', () => {
  const files = [{ name: 'b.gcode', size: 5, timestamp: 20 }, { name: 'cube.gcode', size: 9, timestamp: 30 }, { name: 'Arch.gcode', size: 1, timestamp: 10 }];
  const names = (q: string, sort: Parameters<typeof listFiles>[2]) => listFiles(files, q, sort).map(f => f.name);
  assert.deepEqual(names('', 'newest'), ['cube.gcode', 'b.gcode', 'Arch.gcode']);
  assert.deepEqual(names('', 'oldest'), ['Arch.gcode', 'b.gcode', 'cube.gcode']);
  assert.deepEqual(names('', 'name'), ['Arch.gcode', 'b.gcode', 'cube.gcode']);
  assert.deepEqual(names('', 'largest'), ['cube.gcode', 'b.gcode', 'Arch.gcode']);
  assert.deepEqual(names('  CU ', 'newest'), ['cube.gcode']);
  assert.deepEqual(names('zzz', 'newest'), []);
  assert.equal(files[0].name, 'b.gcode', 'the input is not reordered');
});

test('a video length reads m:ss, h:mm:ss from an hour on; nothing for no length', () => {
  assert.equal(clipLength(6), '0:06');
  assert.equal(clipLength(83), '1:23');
  assert.equal(clipLength(59.6), '1:00');
  assert.equal(clipLength(3725), '1:02:05');
  assert.equal(clipLength(0.2), '0:01', 'a video that has a length is never 0:00');
  for (const none of [0, -3, NaN, Infinity, null, undefined, '83']) assert.equal(clipLength(none), '');
});

test('fingerprints read in pairs; anything that is not hex is shown as is', () => {
  assert.equal(fingerprintText('ab01ff'), 'AB:01:FF');
  assert.equal(fingerprintText(''), '');
  assert.equal(fingerprintText('xyz'), 'xyz');
});

test('the finish time needs a running print that is not preparing and a remaining time', () => {
  const st = { state: 'printing', preparing: false, remaining_s: 600, updated_at: 1000 };
  assert.equal(finishAt(st, 5000), 1600);
  assert.equal(finishAt({ ...st, updated_at: 0 }, 5000), 5600);
  assert.equal(finishAt({ ...st, preparing: true }, 5000), null);
  assert.equal(finishAt({ ...st, remaining_s: 0 }, 5000), null);
  assert.equal(finishAt({ ...st, state: 'paused' }, 5000), null);
  assert.equal(finishAt(null, 5000), null);
});

test('heater phase: off, heating, at target (within 2 °C), cooling; unknown without a target or a reading', () => {
  assert.equal(heaterPhase(25, 0), 'off');
  assert.equal(heaterPhase(150, 220), 'heating');
  assert.equal(heaterPhase(218.5, 220), 'target');
  assert.equal(heaterPhase(240, 220), 'cooling');
  assert.equal(heaterPhase(25, undefined), null);
  assert.equal(heaterPhase(undefined, 220), null);
});
