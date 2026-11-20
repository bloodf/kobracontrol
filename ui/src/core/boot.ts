// The plugin fills a JSON block before serving the page: the boot payload (version, host language, language
// preference). During `vite dev` it is absent and the defaults apply.
import type { LangPref } from './i18n-core';

export interface Boot {
  /** "print": Kobra Control's print dialog (with its data); "app": the tab. */
  mode?: 'app' | 'print';
  data?: unknown;
  version: string;
  lang: string | null;
  pref?: LangPref;
}

function readJson<T>(id: string, fallback: T): T {
  const text = document.getElementById(id)?.textContent?.trim() ?? '';
  if (!text || text.startsWith('__')) return fallback;
  try { return JSON.parse(text) as T; } catch { return fallback; }
}

export const boot: Boot = { version: 'dev', lang: null, ...readJson<Partial<Boot>>('kobra-boot', {}) };
