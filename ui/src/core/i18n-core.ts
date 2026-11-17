// Locale resolution, kept free of Vue so the unit tests can import it directly.
export const LOCALES = ['en', 'pt-BR', 'es', 'de', 'zh-CN'] as const;
export type Locale = typeof LOCALES[number];
export type LangPref = 'auto' | Locale;

// By the language alone: every Portuguese reads pt-BR, every Chinese (zh_CN, zh_TW, zh-Hant) reads zh-CN rather than English.
const BY_LANGUAGE: Record<string, Locale> = { en: 'en', pt: 'pt-BR', es: 'es', de: 'de', zh: 'zh-CN' };

export const isLocale = (value: unknown): value is Locale => (LOCALES as readonly unknown[]).includes(value);

/** OrcaSlicer's codes ("pt_BR", "zh_CN", "de") and the browser's ("es-419", "zh-Hans-CN") → a page locale; anything else → null (caller falls back). */
export function normalizeLocale(value: unknown): Locale | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  return BY_LANGUAGE[value.trim().replace(/_/g, '-').toLowerCase().split('-')[0]] ?? null;
}

/** Explicit choice first, then the host's language, then the browser's, then English. */
export function resolveLocale(pref: LangPref, host: unknown, browser: readonly string[]): Locale {
  if (isLocale(pref)) return pref;
  return normalizeLocale(host) ?? browser.map(normalizeLocale).find((l): l is Locale => !!l) ?? 'en';
}

export function interpolate(text: string, params?: Record<string, unknown>): string {
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (_, k: string) => (k in params ? String(params[k]) : `{${k}}`));
}
