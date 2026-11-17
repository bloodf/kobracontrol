// The printer photo's spools: colour from Spoolman, else the ACE, else an empty reel.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { colourName, figureSpools, hexColour } from '../../src/core/figure.ts';

const slot = (g: number, box: number, i: number, o: Record<string, unknown> = {}) => ({ global_index: g, box_id: box, index: i, status: 5,
  color: [229, 72, 77], type: 'PLA', spool_id: null as number | null, ...o });
const SPOOLS = [
  { id: 7, material: 'PETG', colour: '#111111', remaining: 250, initial: 1000 },
  { id: 8, material: 'PLA', colour: 'FF0000', colours: ['#ff0000', '00ff00', '#0000FF'], remaining: 900, initial: 1000 },
  { id: 9, material: 'TPU', colour: 'nonsense', remaining: null, initial: 1000 },
];

test('Spoolman spool bound to the slot gives colour and material', () => {
  const [a] = figureSpools([slot(3, 0, 0)], SPOOLS, { 3: 7 }, -1);
  assert.deepEqual(a, { n: 1, empty: false, colors: ['#111111'], material: 'PETG', active: false, source: 'spoolman' });
});

test('the live spool_id counts when the binding map lacks it', () => {
  const [a] = figureSpools([slot(3, 0, 0, { spool_id: 7 })], SPOOLS, {}, -1);
  assert.equal(a.source, 'spoolman');
  assert.deepEqual(a.colors, ['#111111']);
});

test('multi-colour spool gives one band per colour', () => {
  const [a] = figureSpools([slot(3, 0, 0)], SPOOLS, { 3: 8 }, -1);
  assert.deepEqual(a.colors, ['#ff0000', '#00ff00', '#0000ff']);
});

test('a Spoolman spool without a usable colour falls back to the ACE colour', () => {
  const [a] = figureSpools([slot(3, 0, 0)], SPOOLS, { 3: 9 }, -1);
  assert.deepEqual(a.colors, ['#e5484d']);
  assert.equal(a.material, 'TPU');
});

test('no spool: the ACE colour and material', () => {
  const [a] = figureSpools([slot(3, 0, 0, { type: 'ABS' })], SPOOLS, {}, 3);
  assert.deepEqual(a, { n: 1, empty: false, colors: ['#e5484d'], material: 'ABS', active: true, source: 'ace' });
});

test('a spool id Spoolman does not list falls back to the ACE', () => {
  const [a] = figureSpools([slot(3, 0, 0)], SPOOLS, { 3: 99 }, -1);
  assert.equal(a.source, 'ace');
});

test('the print head slots are the four spools; a missing fourth (head with ACE) is empty', () => {
  const list = figureSpools([slot(3, 0, 0), slot(2, -1, 2, { status: 0 }), slot(1, -1, 1), slot(0, -1, 0, { color: [1, 2, 3] })], [], {}, 1);
  assert.equal(list.length, 4);
  assert.deepEqual(list.map(x => x.n), [1, 2, 3, 4]);
  assert.deepEqual(list.map(x => x.empty), [false, false, true, true]);
  assert.deepEqual(list.map(x => x.active), [false, true, false, false]);
  assert.deepEqual(list[0].colors, ['#010203']);
  assert.deepEqual(list[2], { n: 3, empty: true, colors: [], material: '', active: false, source: 'empty' });
});

test('an ACE slot loaded through the head is not one of the four', () => {
  assert.ok(figureSpools([slot(0, -1, 0), slot(3, 0, 0)], [], {}, 3).every(x => !x.active));
});

test('without a head box the first ACE unit stands in, in slot order', () => {
  const list = figureSpools([slot(5, 1, 0, { color: [9, 9, 9] }), slot(1, 0, 1, { color: [0, 0, 255] }), slot(0, 0, 0)], [], {}, -1);
  assert.deepEqual(list.map(x => x.colors[0] ?? ''), ['#e5484d', '#0000ff', '', '']);
});

test('hexColour accepts Spoolman forms only', () => {
  assert.equal(hexColour('AbCdEf'), '#abcdef');
  assert.equal(hexColour('#abcdef80'), '#abcdef');
  assert.equal(hexColour('red'), '');
  assert.equal(hexColour(null), '');
});

test('colour words', () => {
  const cases: Record<string, string> = { '#111111': 'black', '#fafafa': 'white', '#8a8a8a': 'grey', '#e5484d': 'red', '#6a2bc4': 'purple',
    '#c8c020': 'yellow', '#2850a8': 'blue', '#1e9e4a': 'green', '#ff8a1e': 'orange', '#6b4423': 'brown', '#ff9ec7': 'pink', '#20c0c8': 'cyan', 'x': '' };
  for (const [hex, name] of Object.entries(cases)) assert.equal(colourName(hex), name, hex);
});
