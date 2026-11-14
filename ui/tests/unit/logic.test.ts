// Pure rules of the page (node --test runs this TypeScript directly).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseTarget, parseWhole, family, hexOf, groupSlots, skippable, thumbSrc, boundSlots } from '../../src/core/logic.ts';
import { normalizeLocale, resolveLocale, interpolate } from '../../src/core/i18n-core.ts';
import { en, ptBR } from '../../src/core/messages.ts';

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

test('slots group by box, print head first, ACE units by id, slots by index', () => {
  const sl = (g: number, box: number, i: number) => ({ global_index: g, box_id: box, index: i });
  const groups = groupSlots([sl(7, 1, 0), sl(1, -1, 1), sl(0, -1, 0), sl(3, 0, 0)]);
  assert.deepEqual(groups.map(g => [g.boxId, g.slots.map(s => s.global_index)]), [[-1, [0, 1]], [0, [3]], [1, [7]]]);
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
  assert.equal(normalizeLocale('pt_BR'), 'pt-BR');
  assert.equal(normalizeLocale('en-GB'), 'en');
  assert.equal(normalizeLocale('de'), null);
  assert.equal(resolveLocale('pt-BR', 'en', ['en']), 'pt-BR');
  assert.equal(resolveLocale('auto', 'pt', ['en']), 'pt-BR');
  assert.equal(resolveLocale('auto', null, ['de', 'pt-BR']), 'pt-BR');
  assert.equal(resolveLocale('auto', null, ['de']), 'en');
  assert.equal(interpolate('{a} and {b}', { a: 1 }), '1 and {b}');
});

test('both languages have the same keys and the same placeholders; no U1 wording', () => {
  assert.deepEqual(Object.keys(ptBR).sort(), Object.keys(en).sort());
  const holes = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort().join(',');
  for (const k of Object.keys(en) as (keyof typeof en)[]) {
    assert.equal(holes(ptBR[k]), holes(en[k]), `placeholders of ${k}`);
    assert.doesNotMatch(en[k] + ptBR[k], /\bU1\b|toolhead|Snapmaker|Moonraker|Klipper/i, `U1 wording in ${k}`);
  }
});
