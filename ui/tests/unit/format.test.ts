// Numbers, sizes, durations, dates, lists and plurals in each page language (core/format.ts with the real messages).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { makeFmt } from '../../src/core/format.ts';
import { interpolate, pluralKey } from '../../src/core/i18n-core.ts';
import { en, ptBR, type MessageKey } from '../../src/core/messages.ts';
import { es } from '../../src/core/locales/es.ts';
import { de } from '../../src/core/locales/de.ts';
import { zhCN } from '../../src/core/locales/zh-CN.ts';
import { pl } from '../../src/core/locales/pl.ts';

const dicts = { en, 'pt-BR': ptBR, es, de, 'zh-CN': zhCN, pl } as Record<string, Record<MessageKey, string>>;
const fmtFor = (l: string) => makeFmt(() => l, (k, p) => interpolate(dicts[l][k], p));
const nbsp = (s: string) => s.replace(/[  ]/g, ' ');

test('decimal and grouping separators follow the language', () => {
  assert.equal(fmtFor('en').number(1234.5, 1), '1,234.5');
  assert.equal(nbsp(fmtFor('pt-BR').number(1234.5, 1)), '1.234,5');
  assert.equal(nbsp(fmtFor('de').number(1234.5, 1)), '1.234,5');
  assert.equal(nbsp(fmtFor('es').number(21.5, 1)), '21,5');
  assert.equal(fmtFor('zh-CN').number(1234.5, 1), '1,234.5');
  assert.equal(nbsp(fmtFor('pl').number(21.5, 1)), '21,5');
  assert.equal(nbsp(fmtFor('pl').number(12345.5, 1)), '12 345,5');
  assert.equal(nbsp(fmtFor('de').grams(1234.4)), '1.234 g');
  assert.equal(nbsp(fmtFor('es').bytes(2_500_000)), '2,5 MB');
});

test('durations, percent, lists and label pairs use each language’s words and punctuation', () => {
  assert.equal(fmtFor('en').duration(3900), '1 h 5 min');
  assert.equal(fmtFor('de').duration(300), '5 min');
  assert.equal(fmtFor('zh-CN').duration(3900), '1 小时 5 分钟');
  assert.equal(fmtFor('zh-CN').percent(40), '40%');
  assert.equal(fmtFor('de').percent(40), '40 %');
  assert.equal(fmtFor('pl').percent(40), '40%');
  assert.equal(fmtFor('pl').duration(3900), '1 h 5 min');
  assert.equal(fmtFor('en').list(['A', 'B']), 'A, B');
  assert.equal(fmtFor('zh-CN').list(['A', 'B']), 'A、B');
  assert.equal(fmtFor('zh-CN').pair('喷嘴', '200'), '喷嘴：200');
  assert.equal(fmtFor('es').pair('Boquilla', '200'), 'Boquilla: 200');
});

test('dates follow the language order', () => {
  const at = Date.UTC(2026, 10, 16, 12, 0) / 1000;
  assert.match(fmtFor('de').dateTime(at), /16\.11\.26/);
  assert.match(fmtFor('es').dateTime(at), /16\/11\/26/);
  assert.match(fmtFor('zh-CN').dateTime(at), /2026\/11\/16/);
  assert.match(fmtFor('en').dateTime(at), /11\/16\/26/);
  // a narrow column: the time for today, the date alone for any other day
  assert.equal(fmtFor('en').when(at, at + 60), fmtFor('en').time(at));
  assert.equal(fmtFor('en').when(at, at + 3 * 86400), fmtFor('en').date(at));
  assert.match(fmtFor('de').date(at), /^16\.11\.26$/);
});

test('plural keys have both forms and pick by the language’s rule', () => {
  const bases = Object.keys(en).filter(k => k.endsWith('_one')).map(k => k.slice(0, -4));
  assert.ok(bases.length > 0);
  for (const [lang, dict] of Object.entries(dicts)) {
    const rules = new Intl.PluralRules(lang);
    for (const base of bases) {
      assert.ok(dict[`${base}_other` as MessageKey], `${lang} ${base}_other`);
      const one = interpolate(dict[`${base}_${rules.select(1) === 'one' ? 'one' : 'other'}` as MessageKey], { n: 1 });
      assert.ok(one, `${lang} ${base}`);
    }
  }
  assert.equal(new Intl.PluralRules('zh-CN').select(1), 'other');
  assert.equal(new Intl.PluralRules('de').select(1), 'one');
});

test('Polish plurals: one, few and many forms by Intl.PluralRules(\'pl\')', () => {
  const dict = pl as Record<string, string>;
  const say = (base: string, n: number) => interpolate(dict[pluralKey(dict, 'pl', base, n)], { n });
  assert.equal(say('videos.count', 1), '1 nagranie');
  assert.equal(say('videos.count', 2), '2 nagrania');
  assert.equal(say('videos.count', 5), '5 nagrań');
  assert.equal(say('videos.count', 12), '12 nagrań');
  assert.equal(say('videos.count', 22), '22 nagrania');
  assert.equal(say('usage.tracking', 22), '22 wydruki czekają na zaksięgowanie w Spoolmanie po zakończeniu.');
  assert.equal(say('usage.count', 0), '0 niepotwierdzonych zużyć');
  // other languages keep their one/other pair
  assert.equal(pluralKey(en as Record<string, string>, 'en', 'videos.count', 5), 'videos.count_other');
  assert.equal(pluralKey(de as Record<string, string>, 'de', 'videos.count', 1), 'videos.count_one');
  assert.equal(pluralKey(en as Record<string, string>, 'pt-BR', 'videos.count', 0), 'videos.count_other', 'Portuguese 0 is "one" by CLDR, but "_one" says 1');
});
