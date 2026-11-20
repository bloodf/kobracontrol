// The spool's level: the fraction of filament left, drawn by OuiSpool and OuiLevel.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { levelTone, slotFraction, spoolFraction } from '../../src/core/spool-level.ts';

test('fraction needs both weights', () => {
  assert.equal(spoolFraction(250, 1000), 0.25);
  assert.equal(spoolFraction(1200, 1000), 1);
  assert.equal(spoolFraction(-5, 1000), 0);
  assert.equal(spoolFraction(250, null), null);
  assert.equal(spoolFraction(null, 1000), null);
  assert.equal(spoolFraction(250, 0), null);
});

test('a slot is drawn from Spoolman, else the ACE percentage, else unknown', () => {
  assert.equal(slotFraction({ remaining: 250, initial: 1000 }, 80), 0.25);
  assert.equal(slotFraction({ remaining: 250, initial: null }, 80), 0.8);
  assert.equal(slotFraction(null, 30), 0.3);
  assert.equal(slotFraction(undefined, 140), 1);
  assert.equal(slotFraction(null, -3), 0);
  assert.equal(slotFraction(null, 0), 0);
  assert.equal(slotFraction(null, null), null);
  assert.equal(slotFraction({ remaining: null, initial: 1000 }, undefined), null);
  assert.equal(slotFraction(null, Number.NaN), null);
});

test('the level bar is green, amber when low, red when almost empty', () => {
  assert.equal(levelTone(0.8), 'normal');
  assert.equal(levelTone(0.8, true), 'low');        // Spoolman's own low mark
  assert.equal(levelTone(0.15), 'low');
  assert.equal(levelTone(0.16), 'normal');
  assert.equal(levelTone(0.05), 'critical');
  assert.equal(levelTone(0, true), 'critical');
  assert.equal(levelTone(null), 'normal');          // unknown is never low
  assert.equal(levelTone(null, true), 'low');
  assert.equal(levelTone(Number.NaN), 'normal');
});
