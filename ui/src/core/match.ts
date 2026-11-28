// Preset names as the slot cards show them: OrcaSlicer's internal name without the plugin bundle prefix
// ("_local/spooler/", "Spooler/") or the "@Printer" suffix. The full name stays in a tooltip.

/** "_local/spooler/3D Procer PLA Marrom terra @Snapmaker U1" -> "3D Procer PLA Marrom terra". */
export function presetLabel(name: string): string {
  const shown = name.replace(/^_local\/[^/]+\//, '').replace(/^spooler\//i, '').replace(/\s*@[^@]*$/, '').trim();
  return shown || name;
}

/** Each name's label; names whose labels collide keep their full name, so every label picks one preset. */
export function presetLabels(names: string[]): Map<string, string> {
  const count = new Map<string, number>();
  for (const n of new Set(names)) count.set(presetLabel(n), (count.get(presetLabel(n)) ?? 0) + 1);
  return new Map(names.map(n => [n, count.get(presetLabel(n))! > 1 ? n : presetLabel(n)]));
}
