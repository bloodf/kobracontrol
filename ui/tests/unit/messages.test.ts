// Every message key is used by the page, and all six languages have the same keys and placeholders.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { en, ptBR } from '../../src/core/messages.ts';
import { es } from '../../src/core/locales/es.ts';
import { de } from '../../src/core/locales/de.ts';
import { zhCN } from '../../src/core/locales/zh-CN.ts';
import { pl } from '../../src/core/locales/pl.ts';

const SRC = fileURLToPath(new URL('../../src/', import.meta.url));   // a path on Windows too, not /D:/...
const files = (dir: string): string[] => readdirSync(dir, { withFileTypes: true })
  .flatMap(e => (e.isDirectory() ? (e.name === 'locales' ? [] : files(join(dir, e.name)))
    : /\.(vue|ts)$/.test(e.name) && e.name !== 'messages.ts' ? [join(dir, e.name)] : []));
const code = files(SRC).map(f => readFileSync(f, 'utf8')).join('\n');
// Keys built at run time from a value the printer or the page supplies: `t(\`link.${link}\`)` and the like.
const dynamic = ['link.', 'status.state.', 'phase.', 'speed.mode.', 'ace.mode.', 'conn.source.', 'lang.', 'temps.phase.', 'stock.usage.', 'match.r.', 'check.state.', 'check.name.', 'check.fix.'];
const others = { 'pt-BR': ptBR, es, de, 'zh-CN': zhCN, pl } as Record<string, Record<string, string>>;
const holes = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort().join(',');

test('every English key is used by the page', () => {
  const unused = Object.keys(en).filter(k => {
    const base = k.replace(/_(one|other)$/, '');
    return !code.includes(`'${k}'`) && !code.includes(`'${base}'`) && !dynamic.some(p => k.startsWith(p));
  });
  assert.deepEqual(unused, []);
});

test('every language has exactly the English keys, the same placeholders, and no U1 wording', () => {
  for (const [lang, dict] of Object.entries(others)) {
    // Polish adds "_few" and "_many" next to every "_one" / "_other" pair
    const extra = lang === 'pl' ? Object.keys(en).filter(k => k.endsWith('_one')).flatMap(k => [k.replace(/_one$/, '_few'), k.replace(/_one$/, '_many')]) : [];
    assert.deepEqual(Object.keys(dict).sort(), [...Object.keys(en), ...extra].sort(), lang);
    for (const k of extra) assert.equal(holes(dict[k]), 'n', `${lang} placeholders of ${k}`);
    for (const k of Object.keys(en) as (keyof typeof en)[]) {
      assert.ok(dict[k]?.trim(), `${lang} ${k} empty`);
      assert.equal(holes(dict[k]), holes(en[k]), `${lang} placeholders of ${k}`);
      assert.doesNotMatch(dict[k], /\bU1\b|toolhead|Snapmaker|Moonraker|Klipper/i, `${lang} U1 wording in ${k}`);
    }
  }
});

test('the new languages are translated, not English copies', () => {
  for (const [lang, dict] of Object.entries({ es, de, 'zh-CN': zhCN, pl })) {
    // language names ("lang.de": "Deutsch") are the same in every language by design
    const same = Object.keys(en).filter(k => !/^lang\.[a-z]{2}(-[A-Z]{2})?$/.test(k) && dict[k as keyof typeof en] === en[k as keyof typeof en]);
    assert.ok(same.length < 50, `${lang}: ${same.length} values equal to English`);
    for (const k of ['nav.files', 'nav.settings', 'act.pause', 'confirm.stop.yes', 'files.empty'] as const) {
      if (k in en) assert.notEqual(dict[k], en[k], `${lang} ${k}`);
    }
  }
});

test('Chinese uses full-width punctuation inside Chinese text', () => {
  for (const [k, v] of Object.entries(zhCN)) {
    assert.doesNotMatch(v, /[\u4e00-\u9fff][,;?!:]|[\u4e00-\u9fff]\.(\s|$)/, k);
  }
});
