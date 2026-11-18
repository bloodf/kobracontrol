/** Filament left as 0..1 (null when either weight is unknown). */
export function spoolFraction(remaining: number | null | undefined, initial: number | null | undefined): number | null {
  return typeof remaining === 'number' && typeof initial === 'number' && initial > 0 ? Math.max(0, Math.min(1, remaining / initial)) : null;
}

/**
 * What a slot's spool is drawn at: the linked Spoolman spool (remaining / initial), else the percentage the ACE reports
 * for the slot, else null (the bare reel). Never a made-up level.
 */
export function slotFraction(spool: { remaining?: number | null; initial?: number | null } | null | undefined, percent: number | null | undefined): number | null {
  return spoolFraction(spool?.remaining, spool?.initial) ?? (typeof percent === 'number' && Number.isFinite(percent) ? Math.max(0, Math.min(1, percent / 100)) : null);
}
