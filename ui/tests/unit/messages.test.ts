// Every message key is used by the page, and both languages have the same keys (no dead or missing strings).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { en, ptBR } from '../../src/core/messages.ts';

const SRC = new URL('../../src/', import.meta.url).pathname;
const files = (dir: string): string[] => readdirSync(dir, { withFileTypes: true })
  .flatMap(e => (e.isDirectory() ? files(join(dir, e.name)) : /\.(vue|ts)$/.test(e.name) && e.name !== 'messages.ts' ? [join(dir, e.name)] : []));
const code = files(SRC).map(f => readFileSync(f, 'utf8')).join('\n');
// Keys built at run time from a value the printer or the page supplies: `t(\`link.${link}\`)` and the like.
const dynamic = ['link.', 'status.state.', 'phase.', 'speed.mode.', 'ace.mode.', 'conn.source.', 'lang.', 'temps.phase.', 'stock.usage.', 'files.sort.'];

test('every English key is used by the page', () => {
  const unused = Object.keys(en).filter(k => {
    const base = k.replace(/_(one|other)$/, '');
    return !code.includes(`'${k}'`) && !code.includes(`'${base}'`) && !dynamic.some(p => k.startsWith(p));
  });
  assert.deepEqual(unused, []);
});

test('pt-BR has exactly the English keys', () => {
  assert.deepEqual(Object.keys(ptBR).sort(), Object.keys(en).sort());
});
