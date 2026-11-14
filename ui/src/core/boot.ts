// The plugin fills two JSON blocks before serving the page: the boot payload (version, host language, language
// preference) and the sanitized icon map. During `vite dev` they are absent and the defaults apply.
export interface Boot {
  version: string;
  lang: string | null;
  pref?: 'auto' | 'en' | 'pt-BR';
}

function readJson<T>(id: string, fallback: T): T {
  const text = document.getElementById(id)?.textContent?.trim() ?? '';
  if (!text || text.startsWith('__')) return fallback;
  try { return JSON.parse(text) as T; } catch { return fallback; }
}

export const boot: Boot = { version: 'dev', lang: null, ...readJson<Partial<Boot>>('kobra-boot', {}) };
export const icons: Record<string, string> = readJson('kobra-icons', {});
