import { computed, reactive } from 'vue';
import * as bridge from '../core/bridge';
import { Tracker, message, type NoticeKind, type RunOptions } from '../core/tracker';
import { showToast } from '../../shared/src/components/toast';
import { t } from '../core/i18n';
import { cancelDialog } from '../core/dialog';
import { boundSlots } from '../core/logic';
import type { Certificate, Config, Info, Limits, Located, Spool, Status, StockView, UsageView } from './types';

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
  retryAt: 0,                        // unix s of the plugin's next automatic attempt, 0 = none planned
  candidates: [] as bridge.Candidate[],   // printers found when there was more than one
  located: null as Located | null,   // the address in use and where it came from (config)
  history: {} as Record<string, (number | null)[]>,   // recent nozzle/bed readings, oldest first (drawn, not used)
  historyAt: 0,
  /** The printer's details and Print Assist were asked for (cmd device): '' not yet, 'asking', 'done'. */
  device: '' as '' | 'asking' | 'done',
});

// What commands answered goes to the page's toasts (bottom-left): "Pause failed: timeout" is a title and its detail.
// An unknown outcome stays until closed, like an error: the user has to look at the printer.
const TOAST_TONE = { error: 'error', unknown: 'warn', success: 'success', info: 'info' } as const;
export function toast(kind: NoticeKind, text: string, key?: string): void {
  const i = text.indexOf(': ');
  showToast({ tone: TOAST_TONE[kind], title: i < 0 ? text : text.slice(0, i + 1), body: i < 0 ? undefined : text.slice(i + 2), key,
    ...(kind === 'unknown' ? { timeout: 0 } : {}) });
}
export const tracker = new Tracker(
  (cmd, args) => bridge.command(cmd, args, s.info?.generation),
  (key, params) => t(key, params),
  toast,
);
export const run = (o: RunOptions) => tracker.run(o);
bridge.setErrorSink(e => tracker.notify('error', t('msg.plugin', { error: message(e) })));

export const printerName = computed(() => s.info?.printer || t('app.printer'));
export const targetKnown = computed(() => s.phase === 'connected' || s.phase === 'unreachable');
/** The one connection state every part of the page shows (badge, banner, Status card, camera, controls). */
export type Link = 'connecting' | 'connected' | 'offline' | 'noCertificate' | 'noTarget';
/** The selected preset uses another printer agent (Kobralink's "moonraker", say): its name, else ''. */
export const otherAgent = computed(() => {
  const agent = s.located?.preset_agent ?? '';
  return agent && agent !== 'kobracontrol' ? agent : '';
});
let agentNoted = false;
export const link = computed<Link>(() => {
  if (s.phase === 'connected') return s.offline ? 'offline' : 'connected';
  return s.phase === 'unreachable' ? 'offline' : s.phase;
});
export const statusAge = computed(() => (s.statusAt ? (s.now - s.statusAt) / 1000 : Infinity));
/** The values on screen are the last known ones, not live: drawn grey with their age. */
export const stale = computed(() => !!s.status && (link.value === 'offline' || statusAge.value > STALE_STATUS_S));
export const printing = computed(() => s.status?.state === 'printing' || s.status?.state === 'paused');
/** Why printer commands are off, or '' when they can be used. */
export const controlsOff = computed(() => {
  if (link.value === 'noCertificate') return t('reason.noCertificate');
  if (link.value === 'noTarget') return t('reason.noTarget');
  if (link.value === 'offline') return t('reason.offline');
  if (link.value === 'connecting') return t('reason.connecting');
  if (!s.status?.connected) return t('reason.waiting');
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
    frame: '', camError: '', camReason: '', usageError: '', retryAt: 0, history: {}, historyAt: 0, device: '' });   // candidates stay until an answer replaces them
  if (s.stock) s.stock = { ...s.stock, bindings: {}, same_spoolman: null, usage: 'unknown' };
  cancelDialog();
}

let helloInFlight = false;
let lastNote = '';
/** Ask the plugin for the printer. `retry`: the user pressed Retry, so a failed connection tries again now
 *  instead of after its growing delay; otherwise its last error comes back at once. */
export async function hello(retry = false): Promise<void> {
  const offered = s.phase === 'noTarget' && s.candidates.length > 0;
  reset();
  // A printer offered for a choice stays on screen while the plugin is asked again: no flicker to "Connecting".
  if (!offered) s.phase = 'connecting';
  const epoch = s.epoch;
  helloInFlight = true;
  try {
    const r: Info = await bridge.request({ type: 'hello', retry });
    if (epoch !== s.epoch) return;
    s.info = r;
    s.phase = 'connected';
    s.candidates = [];
    if (r.note && r.note !== lastNote) { lastNote = r.note; tracker.notify('info', r.note); }   // once: how it was found
    if (otherAgent.value && !agentNoted) { agentNoted = true; tracker.notify('info', t('agent.other', { agent: otherAgent.value })); }
    void loadSpools(true);
  } catch (e) {
    if (epoch !== s.epoch) return;
    s.phase = e instanceof bridge.ReplyError && e.noCertificate ? 'noCertificate'
      : e instanceof bridge.ReplyError && e.noTarget ? 'noTarget' : 'unreachable';
    s.error = message(e);
    s.candidates = e instanceof bridge.ReplyError ? e.candidates : [];
    if (e instanceof bridge.ReplyError && e.pending.length) void allowFound(e.pending);
    s.offline = '';   // the answer is newer than any 'offline' message that came while it was awaited
  } finally {
    helloInFlight = false;
    if (epoch === s.epoch) { void loadStock(false); void loadUsage(); }
  }
}

/** Ask the printer for its network address, counters and Print Assist switches (read only; the answers come in the
 *  status). Once per connection, and only while the printer is idle (the Printer panel calls it): these messages are
 *  not tried on a Kobra X yet, so none is sent during a print. A firmware that does not answer just leaves them out. */
export async function loadDevice(): Promise<void> {
  const epoch = s.epoch;
  s.device = 'asking';
  let ok = true;
  try { await bridge.command('device', {}, s.info?.generation); } catch { ok = false; }
  // A refused or failed ask (the printer started a print meanwhile, the connection dropped) is asked again the next
  // time the printer is idle; the panel shows only what was reported.
  if (epoch === s.epoch) s.device = ok ? 'done' : '';
}

/** The search found a printer OrcaSlicer does not let the plugin reach yet: ask the plugin to have OrcaSlicer show
 *  its dialog now (on its UI thread, so a Yes is saved at once), then connect. Clicking Allow is the only action;
 *  each address is asked about once per page load, so a No is not asked again in a loop. */
let autoAsked = false;   // dialogs are counted, not addresses: one without a click per page load (the plugin: per session)
async function allowFound(hosts: string[], user = false): Promise<void> {
  if (!user && autoAsked) return;
  const fresh = user ? hosts : hosts.slice(0, 1);
  if (!fresh.length) return;
  if (!user) autoAsked = true;
  try {
    const r = await bridge.request({ type: 'allow_hosts', hosts: fresh, user });
    if (r?.allowed?.length) { void hello(); return; }
    // Not allowed (refused, or no dialog came): say what to do instead of waiting for ever.
    s.error = t('fr.allow.fallback', { ip: fresh[0] });
  } catch (e) {
    tracker.notify('error', t('msg.plugin', { error: message(e) }));
  }
}

/** Settings > Search again, and the first-run card: look for the printer on the network again. */
export async function searchAgain(): Promise<void> {
  const r = await run({ key: 'search', label: t('act.search'), cmd: 'search_printer', timeoutMs: 30000, quiet: true });
  if (r.ok || s.phase !== 'connected') void hello();   // a failed search: hello shows its message
}

/** The user picked one of the printers offered: one OrcaSlicer may not reach yet is allowed first (its dialog). */
export async function choosePrinter(c: bridge.Candidate): Promise<void> {
  if (c.needs_allow) { await allowFound([c.ip], true); return; }
  const r = await run({ key: 'choose', label: t('act.choose'), cmd: 'choose_printer', args: { host: c.ip } });
  if (r.ok) { s.candidates = []; void hello(); }   // chosen: the offer is answered
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
      s.status = m.data; s.statusAt = Date.now();
      if (m.data?.connected === true) keepHistory(m.data);
      if (m.data?.connected === true) s.offline = '';   // a disconnected status is followed by its 'offline' message
      // Statuses come every second, connected or not: only one that says connected means it answers again.
      if (m.data?.connected === true && (s.phase === 'unreachable' || s.phase === 'noCertificate') && !helloInFlight) void hello();
      break;
    // s.now too: the countdown is retry_at minus now, and the 1 s clock can lag behind in a throttled tab.
    case 'offline': s.offline = String(m.error ?? ''); s.retryAt = Number(m.retry_at) || 0; s.now = Date.now(); break;
    case 'frame': s.frame = m.image; s.camError = ''; s.camReason = ''; break;
    case 'camera_error': if (s.camOn) { s.camError = String(m.error ?? ''); s.camReason = String(m.reason ?? 'failed'); s.frame = ''; } break;
    case 'notice': tracker.notify('info', String(m.text ?? '')); break;
    case 'config': s.certificate = m.certificate ?? null; s.located = m.located ?? null; s.limits = { ...LIMITS, ...(m.limits ?? {}) }; configHandlers.forEach(h => h(m)); break;
    case 'selection_changed': void hello(); break;
    case 'reply': if (m.error) tracker.notify('error', t('msg.plugin', { error: String(m.error) })); break;
  }
}
const HISTORY_EVERY_MS = 30000, HISTORY_MAX = 20;   // ten minutes of readings, one every 30 s
function keepHistory(d: Status): void {
  if (!d.updated_at || s.statusAt - s.historyAt < HISTORY_EVERY_MS) return;
  const add = (key: string, v: number | undefined) => [key, [...(s.history[key] ?? []), v ?? null].slice(-HISTORY_MAX)] as const;
  s.history = Object.fromEntries([add('nozzle', d.nozzle_temp), add('bed', d.bed_temp)]);
  s.historyAt = s.statusAt;
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
