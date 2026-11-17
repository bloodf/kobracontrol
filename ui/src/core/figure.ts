// What the printer drawing shows on its four spools: pure rules, tested in tests/unit/figure.test.ts.
import { hexOf } from './logic.ts';

export interface FigureSlotIn { global_index: number; box_id: number; index: number; status: number; color: number[]; type: string;
  material_name?: string; spool_id: number | null }
export interface FigureSpoolIn { id: number; material: string; colour?: string; colours?: string[] }
export interface FigureSpool {
  /** 1..4, left to right as numbered on the holder. */ n: number;
  /** Empty reel: no slot, or no filament in it. */ empty: boolean;
  /** "#rrggbb" bands of the winding; [] when nothing says the colour. */ colors: string[];
  material: string; active: boolean; source: 'spoolman' | 'ace' | 'empty';
}

/** "#rrggbb" from a Spoolman colour ("#AABBCC" or "AABBCC"); '' when it is not one. */
export function hexColour(raw: unknown): string {
  const m = typeof raw === 'string' ? /^#?([0-9a-f]{6})(?:[0-9a-f]{2})?$/i.exec(raw.trim()) : null;
  return m ? '#' + m[1].toLowerCase() : '';
}

/**
 * The four spools on the holder: the ACE's slots (or the print head's when there is no ACE), first four by unit and
 * slot. The colour comes from the Spoolman spool bound to the slot, else from what the ACE reports.
 */
export function figureSpools(slots: readonly FigureSlotIn[], spools: readonly FigureSpoolIn[], bound: Record<number, number>, loaded: number): FigureSpool[] {
  const box = slots.filter(sl => sl.box_id >= 0);
  const four = [...(box.length ? box : slots)].sort((a, b) => a.box_id - b.box_id || a.index - b.index).slice(0, 4);
  return [0, 1, 2, 3].map(i => {
    const sl = four[i];
    if (!sl || sl.status !== 5) return { n: i + 1, empty: true, colors: [], material: '', active: false, source: 'empty' as const };
    const id = bound[sl.global_index] ?? sl.spool_id;
    const sp = id == null ? undefined : spools.find(x => x.id === id);
    const multi = (sp?.colours ?? []).map(hexColour).filter(Boolean);
    const spColors = multi.length > 1 ? multi : [hexColour(sp?.colour)].filter(Boolean);
    const ace = hexOf(sl.color);
    return {
      n: i + 1, empty: false,
      colors: spColors.length ? spColors : ace ? [ace] : [],
      material: sp?.material || sl.material_name || sl.type || '',
      active: sl.global_index === loaded, source: sp ? 'spoolman' as const : 'ace' as const,
    };
  });
}

export type ColourName = 'black' | 'white' | 'grey' | 'red' | 'orange' | 'brown' | 'yellow' | 'green' | 'cyan' | 'blue' | 'purple' | 'pink';

/** A plain colour word for "#rrggbb", for screen readers; '' when it is not a colour. */
export function colourName(hex: string): ColourName | '' {
  const c = hexColour(hex);
  if (!c) return '';
  const [r, g, b] = [1, 3, 5].map(k => parseInt(c.slice(k, k + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  if (l < 0.15) return 'black';
  if (s < 0.15 || d < 0.08) return l > 0.85 ? 'white' : l < 0.25 ? 'black' : 'grey';
  const h = (max === r ? ((g - b) / d + 6) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4) * 60;
  if (h < 15 || h >= 345) return l > 0.7 ? 'pink' : 'red';
  if (h < 45) return l < 0.4 ? 'brown' : 'orange';
  if (h < 70) return l < 0.3 ? 'brown' : 'yellow';
  if (h < 165) return 'green';
  if (h < 195) return 'cyan';
  if (h < 255) return 'blue';
  if (h < 290) return 'purple';
  return 'pink';
}
