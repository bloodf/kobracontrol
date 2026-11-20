import { computed, ref } from 'vue';
import { en, ptBR, type MessageKey } from './messages';
import { es } from './locales/es';
import { de } from './locales/de';
import { zhCN } from './locales/zh-CN';
import { pl } from './locales/pl';
import { interpolate, isLocale, pluralKey, resolveLocale, type LangPref, type Locale } from './i18n-core';
import { makeFmt } from './format';
import { boot } from './boot';

const PREF_KEY = 'kobracontrol.lang';
const dicts: Record<Locale, Record<MessageKey, string>> = { en, 'pt-BR': ptBR, es, de, 'zh-CN': zhCN, pl };

// The explicit choice lives in the plugin's settings (boot "pref"); localStorage is only a fallback cache.
let persist: (value: LangPref) => void = () => {};
export function onLangPref(fn: (value: LangPref) => void): void { persist = fn; }
function readPref(): LangPref {
  const fromHost = (boot as { pref?: unknown }).pref;
  if (isLocale(fromHost) || fromHost === 'auto') return fromHost;
  try {
    const v = localStorage.getItem(PREF_KEY);
    return isLocale(v) ? v : 'auto';
  } catch { return 'auto'; }
}

export const langPref = ref<LangPref>(readPref());
const hostLang = ref<unknown>(null);
export const locale = computed<Locale>(() => resolveLocale(langPref.value, hostLang.value, navigator.languages ?? [navigator.language]));
export const autoLocale = computed<Locale>(() => resolveLocale('auto', hostLang.value, navigator.languages ?? [navigator.language]));

export function setHostLanguage(value: unknown): void { hostLang.value = value; }
export function setLangPref(value: LangPref): void {
  langPref.value = value;
  persist(value);
  try { if (value === 'auto') localStorage.removeItem(PREF_KEY); else localStorage.setItem(PREF_KEY, value); } catch { /* per-viewer only */ }
}

export function t(key: MessageKey, params?: Record<string, unknown>): string {
  return interpolate(dicts[locale.value][key] ?? en[key] ?? key, params);
}
/** Plural keys come in pairs "<base>_one" / "<base>_other"; a language with more forms (Polish: "_few", "_many") adds them. */
export function tn(base: string, n: number, params?: Record<string, unknown>): string {
  return t(pluralKey(dicts[locale.value], locale.value, base, n) as MessageKey, { n, ...params });
}
/** A message key when it exists (state names, codes from Python); otherwise the raw value. */
export function tMaybe(key: string, fallback: string, params?: Record<string, unknown>): string {
  return key in en ? t(key as MessageKey, params) : fallback;
}

export const fmt = makeFmt(() => locale.value, t);
