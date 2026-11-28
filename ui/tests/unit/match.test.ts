import { test } from 'node:test';
import assert from 'node:assert/strict';
import { presetLabel, presetLabels } from '../../src/core/match.ts';

test('preset labels drop the bundle prefix and the printer suffix', () => {
  assert.equal(presetLabel('_local/spooler/3D Procer PLA Marrom terra @Snapmaker U1'), '3D Procer PLA Marrom terra');
  assert.equal(presetLabel('Spooler/eSUN PLA+ @Anycubic Kobra X 0.4 nozzle'), 'eSUN PLA+');
  assert.equal(presetLabel('Generic PLA @System'), 'Generic PLA');
  assert.equal(presetLabel('Generic PLA'), 'Generic PLA');
  assert.equal(presetLabel('@x'), '@x');
});

test('colliding labels keep the full name', () => {
  const m = presetLabels(['_local/spooler/A PLA @Anycubic Kobra X', 'A PLA', 'Generic PLA']);
  assert.deepEqual([...m.values()], ['_local/spooler/A PLA @Anycubic Kobra X', 'A PLA', 'Generic PLA']);
});
