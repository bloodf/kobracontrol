// Pure rules shared by the page and its unit tests (no DOM, no Vue).
export type TargetInput = { kind: 'empty' } | { kind: 'invalid' } | { kind: 'off' } | { kind: 'heat'; value: number };

/** A blank field is never 0; 0 typed explicitly means off; anything outside 0..max is refused. */
export function parseTarget(raw: unknown, max: number): TargetInput {
  if (raw === null || raw === undefined || (typeof raw === 'string' && raw.trim() === '')) return { kind: 'empty' };
  const v = typeof raw === 'number' ? raw : Number(String(raw).replace(',', '.'));
  if (!Number.isFinite(v) || v < 0 || v > max) return { kind: 'invalid' };
  const value = Math.round(v);
  return value === 0 ? { kind: 'off' } : { kind: 'heat', value };
}

/** A whole number inside min..max, or null (blank, text, out of range). */
export function parseWhole(raw: unknown, min: number, max: number): number | null {
  if (raw === null || raw === undefined || (typeof raw === 'string' && raw.trim() === '')) return null;
  const v = typeof raw === 'number' ? raw : Number(String(raw).replace(',', '.'));
  return Number.isFinite(v) && v >= min && v <= max ? Math.round(v) : null;
}

export const family = (t: unknown): string => ((String(t ?? '').match(/[A-Za-z]+/) || [''])[0]).toUpperCase();

/** "#RRGGBB" for a slot colour [r, g, b]; '' when the colour is missing or malformed. */
export function hexOf(color: unknown): string {
  if (!Array.isArray(color) || color.length < 3) return '';
  const parts = color.slice(0, 3).map(c => Math.max(0, Math.min(255, Math.round(Number(c)))));
  return parts.some(Number.isNaN) ? '' : '#' + parts.map(c => c.toString(16).padStart(2, '0')).join('');
}

export interface SlotLike { global_index: number; box_id: number; index: number }
export interface SlotGroup<T extends SlotLike> { boxId: number; slots: T[] }

/** Slots grouped by the box that holds them: the print head (box -1) first, then ACE units by id. */
export function groupSlots<T extends SlotLike>(slots: readonly T[]): SlotGroup<T>[] {
  const groups = new Map<number, T[]>();
  for (const sl of slots) groups.set(sl.box_id, [...(groups.get(sl.box_id) ?? []), sl]);
  return [...groups.entries()].sort((a, b) => a[0] - b[0]).map(([boxId, list]) => ({ boxId, slots: [...list].sort((a, b) => a.index - b.index) }));
}

/** Object names a print can skip: the printer's objects minus those already skipped (anything but strings is dropped). */
export function skippable(objects: unknown, skipped: unknown): string[] {
  const names = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string' && x !== '') : []);
  const done = names(skipped);
  return [...new Set(names(objects))].filter(n => !done.includes(n));
}

/** A thumbnail as an image source: a data URL as is, bare base64 as PNG, anything else nothing. */
export function thumbSrc(raw: unknown): string {
  if (typeof raw !== 'string' || !raw) return '';
  if (raw.startsWith('data:image/')) return raw;
  return /^[A-Za-z0-9+/=\s]+$/.test(raw) ? `data:image/png;base64,${raw.replace(/\s+/g, '')}` : '';
}

/** Spool id bound to each slot, preferring the live status over the stock view. */
export function boundSlots(live: Record<number, number | null>, fromStock: Record<string, number>): Record<number, number> {
  const out: Record<number, number> = Object.fromEntries(Object.entries(fromStock).map(([k, v]) => [Number(k), v]));
  for (const [k, v] of Object.entries(live)) { if (v != null) out[Number(k)] = v; else delete out[Number(k)]; }
  return out;
}
