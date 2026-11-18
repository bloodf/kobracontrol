// How the print setup names and colours a printer slot.
import { t } from '../core/i18n';
import type { PdSlot } from '../core/printsetup';

/** Readable text on a filament colour: dark ink on light colours, white on dark ones. */
export function inkOn(hex: string): string {
  const m = /^#?([0-9a-f]{6})/i.exec(hex ?? '');
  if (!m) return '#111';
  const [r, g, b] = [0, 2, 4].map(i => parseInt(m[1].slice(i, i + 2), 16) / 255).map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.4 ? '#111' : '#fff';
}

/** The short number on a slot: "1".."4" with one ACE, "2-3" (ACE 2, slot 3) with several, "H1" for the print head. */
export function slotNumber(s: PdSlot, all: readonly PdSlot[]): string {
  if (s.box_id < 0) return t('pd.headSlot', { n: s.index + 1 });
  const aces = new Set(all.filter(x => x.box_id >= 0).map(x => x.box_id));
  return aces.size > 1 ? `${s.box_id + 1}-${s.index + 1}` : String(s.index + 1);
}

/** "ACE 1 · Slot 2" / "Print head · Slot 1". */
export function slotName(s: PdSlot | undefined, _all?: readonly PdSlot[]): string {
  if (!s) return '?';
  return `${s.box_id < 0 ? t('ace.head') : t('ace.unit', { n: s.box_id + 1 })} · ${t('slot.name', { n: s.index + 1 })}`;
}
