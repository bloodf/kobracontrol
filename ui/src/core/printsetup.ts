// The print dialog's rules on the page, the same as the plugin's (src/kobracontrol/printsetup.py check): the plugin
// checks the answer again, so these only decide what the page shows and whether Print is enabled.
// family / material: the material family and normalised name as the plugin reckons them (ace.material_family,
// ace.normalize_material), so both sides judge alike.
export interface PdFilament { index: number; colour: string; type: string; family: string; material: string; grams: number }
export interface PdSlot { tray: number; global_index: number; box_id: number; index: number; type: string; family: string; material: string;
  colour: string; usable: boolean; spool: string }
export interface PdIssue { id: string; kind: 'none' | 'empty' | 'material' | 'variant' | 'colour'; f: number; tray: number }

const same = (a: string, b: string) => !a || !b || a === b;
/** Only the same filament family can be chosen for a filament (an empty material matches anything). */
export const sameFamily = (f: PdFilament, s: PdSlot): boolean => same(f.family, s.family);

export const COLOUR_FAR = 0.25;

function rgb(hex: string): number[] {
  const m = /^#?([0-9a-f]{6})/i.exec(String(hex ?? ''));
  if (!m) return [255, 255, 255];
  return [0, 2, 4].map(i => parseInt(m[1].slice(i, i + 2), 16));
}
export function colourDistance(a: string, b: string): number {
  const x = rgb(a), y = rgb(b);
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) / Math.hypot(255, 255, 255);
}

/** blocking (Print off): no usable slot, or another material family; warnings ("use anyway"): same family, another
 *  kind (PLA in a PLA Silk slot); hints: another colour. */
export function checkChoice(filaments: readonly PdFilament[], slots: readonly PdSlot[], trays: Record<string, number>) {
  const blocking: PdIssue[] = [], warnings: PdIssue[] = [], hints: PdIssue[] = [];
  for (const f of filaments) {
    const tray = trays[String(f.index)] ?? -1;
    const item = (kind: PdIssue['kind']): PdIssue => ({ id: `${kind}:${f.index}:${tray}`, kind, f: f.index, tray });
    const slot = tray >= 0 ? slots.find(s => s.tray === tray) : undefined;
    if (tray < 0) blocking.push(item('none'));
    else if (!slot || !slot.usable) blocking.push(item('empty'));
    else if (!sameFamily(f, slot)) blocking.push(item('material'));
    else if (!same(f.material, slot.material)) warnings.push(item('variant'));
    else if (colourDistance(f.colour, slot.colour) > COLOUR_FAR) hints.push(item('colour'));
  }
  return { blocking, warnings, hints };
}

/** One key for a set of warnings: a confirmation belongs to exactly that set. */
export const issueKey = (issues: readonly PdIssue[]): string => issues.map(i => i.id).sort().join('|');
