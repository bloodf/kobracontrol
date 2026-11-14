import { computed, reactive } from 'vue';
import * as bridge from '../core/bridge';
import { Tracker, message, type RunOptions } from '../core/tracker';
import { t } from '../core/i18n';
import { cancelDialog } from '../core/dialog';
import { boundSlots } from '../core/logic';
import type { Certificate, Config, Info, Limits, Spool, Status, StockView, UsageView } from './types';

export type Phase = 'connecting' | 'connected' | 'noTarget' | 'noCertificate' | 'unreachable';
export const LIMITS: Limits = { nozzle_max: 300, bed_max: 100 };
export const STALE_STATUS_S = 10;

export const s = reactive({
  phase: 'connecting' as Phase,
  epoch: 0,
  info: null as Info | null,
  error: '',
  offline: '',
  status: null as Status | null,
  statusAt: 0,
  now: Date.now(),
  limits: { ...LIMITS },
  certificate: null as Certificate | null,
  spools: [] as Spool[],
  spoolsError: '',
  spoolsLoaded: false,
  config: null as Config | null,
  tab: 'dash',
  hidden: document.hidden,
  camOn: false,
  frame: '',
  camError: '',
  camReason: '',
  stock: null as StockView | null,
  stockError: '',
  stockLoading: false,
  usage: null as UsageView | null,
  usageError: '',
});

export const tracker = new Tracker(
  (cmd, args) => bridge.command(cmd, args, s.info?.generation),
  (key, params) => t(key, params),
);
export const run = (o: RunOptions) => tracker.run(o);
bridge.setErrorSink(e => tracker.notify('error', t('msg.plugin', { error: message(e) })));

export const printerName = computed(() => s.info?.printer || t('app.printer'));
export const targetKnown = computed(() => s.phase === 'connected' || s.phase === 'unreachable');
export const statusAge = computed(() => (s.statusAt ? (s.now - s.statusAt) / 1000 : Infinity));
export const printing = computed(() => s.status?.state === 'printing' || s.status?.state === 'paused');
/** Why printer commands are off, or '' when they can be used. */
export const controlsOff = computed(() => {
  if (s.phase === 'noCertificate') return t('reason.noCertificate');
  if (s.phase === 'noTarget') return t('reason.noTarget');
  if (s.phase === 'unreachable' || s.offline) return t('reason.offline');
  if (s.phase === 'connecting' || !s.status) return t('reason.waiting');
  return '';
});
/** Numbers in the status are real only after the printer has reported once (blank is never 0). */
export const reported = computed(() => !!s.status?.updated_at);
/** Spool id bound to each slot (global index). */
export const bindings = computed(() => boundSlots(
  Object.fromEntries((s.status?.slots ?? []).map(sl => [sl.global_index, sl.spool_id])), s.stock?.bindings ?? {}));

function reset(): void {
  s.epoch++;
  Object.assign(s, { info: null, error: '', offline: '', status: null, statusAt: 0, spools: [], spoolsError: '', spoolsLoaded: false,
    frame: '', camError: '', camReason: '', usageError: '' });
  if (s.stock) s.stock = { ...s.stock, bindings: {}, same_spoolman: null, usage: 'unknown' };
  cancelDialog();
}

let helloInFlight = false;
export async function hello(): Promise<void> {
  reset();
  s.phase = 'connecting';
  const epoch = s.epoch;
  helloInFlight = true;
  try {
    const r: Info = await bridge.request({ type: 'hello' });
    if (epoch !== s.epoch) return;
    s.info = r;
    s.phase = 'connected';
    void loadSpools(true);
  } catch (e) {
    if (epoch !== s.epoch) return;
    s.phase = e instanceof bridge.ReplyError && e.noCertificate ? 'noCertificate'
      : e instanceof bridge.ReplyError && e.noTarget ? 'noTarget' : 'unreachable';
    s.error = message(e);
  } finally {
    helloInFlight = false;
    if (epoch === s.epoch) { void loadStock(false); void loadUsage(); }
  }
}

export async function loadSpools(quiet: boolean): Promise<void> {
  if (!targetKnown.value) return;
  const epoch = s.epoch;
  const r = await run({ key: 'spools', label: t('act.spools'), cmd: 'spools', quiet: true });
  if (epoch !== s.epoch) return;
  if (r.ok) {
    s.spools = r.result.spools ?? [];
    s.spoolsError = '';
    s.spoolsLoaded = true;
  } else if (r.reason !== 'busy') {
    s.spoolsError = r.error ?? t('common.unknown');
    if (!quiet) tracker.notify('error', t('msg.failed', { action: t('act.spools'), error: s.spoolsError }));
  }
}

let stockSeq = 0;
export async function loadStock(refresh: boolean): Promise<void> {
  const mine = ++stockSeq, epoch = s.epoch;
  s.stockLoading = true;
  try {
    const r: StockView = await bridge.command('stock', { refresh }, s.info?.generation);
    if (mine === stockSeq && epoch === s.epoch) { s.stock = r; s.stockError = ''; }
  } catch (e) {
    if (mine === stockSeq && epoch === s.epoch) s.stockError = message(e);
  } finally {
    if (mine === stockSeq) s.stockLoading = false;
  }
}

export async function loadUsage(): Promise<void> {
  const epoch = s.epoch;
  try {
    const r: UsageView = await bridge.command('usage', {}, s.info?.generation);
    if (epoch === s.epoch) { s.usage = r; s.usageError = ''; }
  } catch (e) {
    if (epoch === s.epoch) s.usageError = message(e);
  }
}

/** The Stock card shows only when the plugin says the list is usable (`available`); every other reason hides it. */
export const stockVisible = computed(() => !s.stockError && s.stock?.available === true);

function onMessage(m: any): void {
  switch (m.type) {
    case 'status':
      s.status = m.data; s.statusAt = Date.now(); s.offline = '';
      if (s.phase === 'unreachable' && !helloInFlight) void hello();   // it answers again: fetch its generation
      break;
    case 'offline': s.offline = String(m.error ?? ''); break;
    case 'frame': s.frame = m.image; s.camError = ''; s.camReason = ''; break;
    case 'camera_error': if (s.camOn) { s.camError = String(m.error ?? ''); s.camReason = String(m.reason ?? 'failed'); s.frame = ''; } break;
    case 'notice': tracker.notify('info', String(m.text ?? '')); break;
    case 'config': s.certificate = m.certificate ?? null; s.limits = { ...LIMITS, ...(m.limits ?? {}) }; configHandlers.forEach(h => h(m)); break;
    case 'selection_changed': void hello(); break;
    case 'reply': if (m.error) tracker.notify('error', t('msg.plugin', { error: String(m.error) })); break;
  }
}
const configHandlers = new Set<(m: Config) => void>();
export const onConfig = (h: (m: Config) => void) => { configHandlers.add(h); return () => configHandlers.delete(h); };

export function lease(): void {
  const vis = !s.hidden && s.tab === 'dash';
  bridge.post({ type: 'lease', camera: s.camOn && vis, stock: vis && stockVisible.value });
}

export function start(): () => void {
  bridge.attach();
  const off = bridge.onMessage(onMessage);
  const onVis = () => { s.hidden = document.hidden; lease(); };
  document.addEventListener('visibilitychange', onVis);
  const timers = [
    window.setInterval(lease, 2000),
    window.setInterval(() => { s.now = Date.now(); }, 1000),
    window.setInterval(() => { if (s.tab === 'dash' && !s.hidden) void loadStock(false); }, 5000),
    window.setInterval(() => { if (s.tab === 'dash' && !s.hidden) void loadUsage(); }, 10000),
  ];
  void hello();
  return () => { off(); document.removeEventListener('visibilitychange', onVis); timers.forEach(clearInterval); };
}
