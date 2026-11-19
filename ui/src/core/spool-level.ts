/** Filament left as 0..1 (null when either weight is unknown). */
export function spoolFraction(remaining: number | null | undefined, initial: number | null | undefined): number | null {
  return typeof remaining === 'number' && typeof initial === 'number' && initial > 0 ? Math.max(0, Math.min(1, remaining / initial)) : null;
}

/**
 * What a slot's spool is drawn at: the linked Spoolman spool (remaining / initial), else the percentage the ACE reports
 * for the slot, else null (unknown: the full reel with the unknown badge). Never a made-up level.
 */
export function slotFraction(spool: { remaining?: number | null; initial?: number | null } | null | undefined, percent: number | null | undefined): number | null {
  return spoolFraction(spool?.remaining, spool?.initial) ?? (typeof percent === 'number' && Number.isFinite(percent) ? Math.max(0, Math.min(1, percent / 100)) : null);
}

/** The level bar's colour: red when almost empty (5 % or less), amber when Spoolman says low or 15 % or less is left,
 *  else green. An unknown amount is never low. */
export function levelTone(fraction: number | null | undefined, low?: boolean | null): 'normal' | 'low' | 'critical' {
  const known = typeof fraction === 'number' && Number.isFinite(fraction);
  return known && fraction <= 0.05 ? 'critical' : low || (known && fraction <= 0.15) ? 'low' : 'normal';
}
