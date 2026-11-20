// Numbers, sizes, durations, dates and small joins in the page language. Pure (no Vue, no DOM): the page binds it to
// its locale in i18n.ts and the unit tests call it directly. Unit symbols (g, mm, °C, kB) are the same everywhere;
// the words and the punctuation around them come from the messages.
import type { MessageKey } from './messages';

type Text = (key: MessageKey, params?: Record<string, unknown>) => string;

export function makeFmt(locale: () => string, t: Text) {
  const nf = (v: number, max: number, min = 0) => new Intl.NumberFormat(locale(), { maximumFractionDigits: max, minimumFractionDigits: min }).format(v);
  const fmt = {
    number: (v: number, digits = 0) => nf(v, digits, digits),
    grams: (v: number | null | undefined) => (v == null ? '? g' : `${nf(Math.round(v), 0)} g`),
    percent: (v: number | string) => t('fmt.percent', { value: typeof v === 'number' ? nf(v, 0) : v }),
    bytes(b: number | null | undefined): string {
      if (b == null) return '';
      return b > 1e9 ? `${nf(b / 1e9, 1)} GB` : b > 1e6 ? `${nf(b / 1e6, 1)} MB` : `${nf(b / 1e3, 0)} kB`;
    },
    duration(s: number | null | undefined): string {
      if (s == null || !isFinite(s)) return '—';
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
      return h ? t('fmt.hm', { h, m }) : t('fmt.m', { m });
    },
    dateTime: (unix: number) => new Intl.DateTimeFormat(locale(), { dateStyle: 'short', timeStyle: 'short' }).format(new Date(unix * 1000)),
    date: (unix: number) => new Intl.DateTimeFormat(locale(), { dateStyle: 'short' }).format(new Date(unix * 1000)),
    /** For a narrow column: the time for today, the date for any other day. */
    when: (unix: number, now = Date.now() / 1000) => (new Date(unix * 1000).toDateString() === new Date(now * 1000).toDateString() ? fmt.time(unix) : fmt.date(unix)),
    time: (unix: number) => new Intl.DateTimeFormat(locale(), { timeStyle: 'short' }).format(new Date(unix * 1000)),
    ago(unix: number | null | undefined, now = Date.now() / 1000): string {
      if (unix == null) return '';
      const s = Math.max(0, Math.round(now - unix));
      return s < 60 ? t('age.seconds', { n: s }) : s < 3600 ? t('age.minutes', { n: Math.round(s / 60) }) : t('age.at', { time: fmt.time(unix) });
    },
    /** "A, B" (zh-CN: "A、B"). */
    list: (items: readonly string[]) => items.join(t('fmt.listSep')),
    /** "label: value" (zh-CN: "label：value"). */
    pair: (label: string, value: string) => t('fmt.pair', { label, value }),
  };
  return fmt;
}
