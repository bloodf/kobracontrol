// The print dialog's page rules (src/core/printsetup.ts), the same cases as tests/test_printsetup.py.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkChoice, colourDistance, issueKey, type PdFilament, type PdSlot } from '../../src/core/printsetup.ts';

const fam = (type: string) => type.split(' ')[0];
const slot = (tray: number, type: string, colour: string, usable = true): PdSlot =>
  ({ tray, global_index: tray - 4, box_id: 0, index: tray - 4, type, family: fam(type), material: type, colour, usable, spool: '' });
const fil = (index: number, type: string, colour: string): PdFilament => ({ index, type, family: fam(type), material: type, colour, grams: 1 });
const SLOTS = [slot(4, 'PLA', '#FF0000'), slot(5, 'PETG', '#0000FF'), slot(6, '', '#000000', false), slot(7, 'PLA', '#00FF00')];

test('blocking, warning and hint kinds', () => {
  const fils = [fil(0, 'PLA', '#FF0000'), fil(1, 'PETG', '#FF0000'), fil(2, 'PLA', '#FFFFFF'), fil(3, 'PLA', '#FF0000'), fil(4, 'PLA', '#FF0000'),
    fil(5, 'PLA SILK', '#FF0000')];
  const { blocking, warnings, hints } = checkChoice(fils, SLOTS, { 0: 4, 1: 4, 2: 7, 3: 6, 4: -1, 5: 4 });
  assert.deepEqual(blocking.map(b => [b.kind, b.f]), [['material', 1], ['empty', 3], ['none', 4]]);
  assert.deepEqual(warnings.map(w => w.id), ['variant:5:4']);
  assert.deepEqual(hints.map(h => h.id), ['colour:2:7']);
});

test('a missing slot and a filament with no choice block printing', () => {
  assert.equal(checkChoice([fil(0, 'PLA', '#FF0000')], SLOTS, { 0: 99 }).blocking[0].kind, 'empty');
  assert.equal(checkChoice([fil(0, 'PLA', '#FF0000')], SLOTS, {}).blocking[0].kind, 'none');
});

test('a clean match has no issue; colours compare 0..1', () => {
  const r = checkChoice([fil(0, 'PLA', '#FF0000')], SLOTS, { 0: 4 });
  assert.deepEqual([r.blocking, r.warnings, r.hints], [[], [], []]);
  assert.equal(colourDistance('#000000', '#FFFFFF'), 1);
  assert.equal(colourDistance('#123456', '123456'), 0);
});

test('a confirmation key ignores order', () => {
  const a = { id: 'material:1:4', kind: 'material' as const, f: 1, tray: 4 }, b = { ...a, id: 'material:0:5' };
  assert.equal(issueKey([a, b]), issueKey([b, a]));
});
