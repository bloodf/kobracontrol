import { computed, reactive, ref, watch } from 'vue';
import * as bridge from '../core/bridge';
import { Tracker, message, type NoticeKind, type RunOptions } from '../core/tracker';
import { showToast } from '@orca-plugins/ui-foundation/src/components/toast';
import { t, tMaybe } from '../core/i18n';
import { cancelDialog } from '../core/dialog';
import { autoRefresh, cleanEvery, userBusy, REFRESH_DEFAULT_S } from '../core/autorefresh';
import { boundSlots } from '../core/logic';
import { playable } from '../core/player';
import type { Certificate, Config, Info, Limits, Located, PresetMatch, Requirement, RequirementId, Spool, Status, StockView, UsageView } from './types';

export type Phase = 'connecting' | 'connected' | 'noTarget' | 'noCertificate' | 'unreachable';
export const LIMITS: Limits = { nozzle_max: 300, bed_max: 100 };
export const STALE_STATUS_S = 10;

/** Open Settings at one page (conn-h, print-h, ...): a "Settings" link elsewhere on the page. */
export function openSettings(page: string): void { s.settingsPage = page; s.tab = 'settings'; }

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
  /** Each ready slot's preset as the Device tab reports it, by global slot index (preset_matches). */
  matches: {} as Record<string, PresetMatch>,
  matchBusy: false,
  /** Seconds between Spoolman re-reads (settings spoolman_refresh_s; 0 = off), and whether the last ones failed. */
  refreshS: REFRESH_DEFAULT_S,
  spoolsRetrying: false,
  spoolsError: '',
  spoolsLoaded: false,
  config: null as Config | null,
  tab: 'dash',
  settingsPage: '',                 // the settings page a link asked for, opened once Settings shows
  hidden: document.hidden,
  camOn: false,
  frame: '',
  video: false,                      // the page's own player shows the stream (no ffmpeg)
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
  /** Settings > Requirements, as the plugin last checked them; `checking` while its file checks run. */
  requirements: [] as Requirement[],
  checking: false,
  /** The widgets on the Dashboard's open layout: the camera streams only while its widget is there. */
  widgets: [] as string[],
});

// What commands answered goes to the page's toasts (bottom-left): "Pause failed: timeout" is a title and its detail.
// An unknown outcome stays until closed, like an error: the user has to look at the printer.
const TOAST_TONE = { error: 'error', unknown: 'warn', success: 'success', info: 'info' } as const;
export function toast(kind: NoticeKind, text: string, key?: string): void {
  note(text, kind === 'error' || kind === 'unknown' ? 'err' : 'out');
  const i = text.indexOf(': ');
  showToast({ tone: TOAST_TONE[kind], title: i < 0 ? text : text.slice(0, i + 1), body: i < 0 ? undefined : text.slice(i + 2), key,
    ...(kind === 'unknown' ? { timeout: 0 } : {}) });
}
// The Console widget's log: what the page sent to the printer, what came back and what the printer did. The Kobra X
// takes no typed G-code, so this is the console it has. Reads the page repeats on its own are left out.
export interface LogLine { id: number; text: string; kind: 'in' | 'out' | 'err' }
export const activity = ref<LogLine[]>([]);
export const LOG_MAX = 1000;
let logId = 0;
const QUIET = new Set(['spools', 'device', 'connect', 'cloud_state']);
export function note(text: string, kind: LogLine['kind'] = 'out'): void {
  const at = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  activity.value = [...activity.value, { id: ++logId, text: `${at}  ${text}`, kind }].slice(-LOG_MAX);
}
// A pasted Anycubic Cloud token (cloud_sign_in) never reaches the console.
const argText = (args?: Record<string, unknown>) => Object.entries(args ?? {}).map(([k, v]) => `${k}=${k === 'token' ? '***' : typeof v === 'object' ? JSON.stringify(v) : v}`).join(' ');
export const tracker = new Tracker(
  (cmd, args) => { if (!QUIET.has(cmd)) note(`> ${cmd} ${argText(args)}`.trim(), 'in'); return bridge.command(cmd, args, s.info?.generation); },
  (key, params) => t(key, params),
  toast,
);
export const run = (o: RunOptions) => tracker.run(o);
export const requirement = (id: RequirementId) => s.requirements.find(r => r.id === id);
/** ffmpeg was looked for and is not there: the camera is off (the plugin does not start it either). */
// ffmpeg only matters when this page can't play the camera itself: no H.264 here, or an RTSP stream.
export const pagePlays = computed(() => playable() && !String(s.status?.camera_url ?? '').toLowerCase().startsWith('rtsp://'));
export const noFfmpeg = computed(() => requirement('ffmpeg')?.state === 'missing' && !pagePlays.value);
/** Anycubic Slicer Next is not in its usual folder: Find certificate searches only a path typed in. */
export const noSlicer = computed(() => requirement('anycubic_slicer')?.state === 'missing');
/** Settings > Requirements > Check again: the plugin looks for ffmpeg and Anycubic Slicer Next again. */
export function checkRequirements(): void {
  s.checking = true;
  bridge.post({ type: 'check_requirements' });
}
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
/** What a connected printer refuses right now (it prints, prepares, dries...). The page says it once, in the banner
 *  under the page header (#kc-busy); the controls it turns off point there. All false while `controlsOff` says more. */
export const busy = computed(() => {
  const can = controlsOff.value ? null : s.status?.can;
  return { feed: !!can && !can.feed, move: !!can && !can.move, heat: !!can && !can.heat, print: !!can && !can.print };
});
/** The id of the banner that says why a control is off: the page's (#kc-why), the busy one (#kc-busy), or none. */
export const whyId = (off: boolean) => (controlsOff.value ? 'kc-why' : off ? 'kc-busy' : undefined);
/** Numbers in the status are real only after the printer has reported once (blank is never 0). */
export const reported = computed(() => !!s.status?.updated_at);
/** Spool id bound to each slot (global index). */
export const bindings = computed(() => boundSlots(
  Object.fromEntries((s.status?.slots ?? []).map(sl => [sl.global_index, sl.spool_id])), s.stock?.bindings ?? {}));

function reset(): void {
  s.epoch++;
  // The Spoolman spools stay: they are the last ones read, and hello() clears them only for another printer. An
  // OrcaSlicer device or preset event (selection_changed) says hello again for the same printer, and must not blank them.
  Object.assign(s, { info: null, error: '', offline: '', status: null, statusAt: 0,
    frame: '', video: false, camError: '', camReason: '', usageError: '', retryAt: 0, history: {}, historyAt: 0, device: '' });   // candidates stay until an answer replaces them
  if (s.stock) s.stock = { ...s.stock, bindings: {}, same_spoolman: null, usage: 'unknown' };
  cancelDialog();
}

let helloInFlight = false;
/** The printer the spools in `s.spools` were read for. */
let spoolsFor = '';
let lastNote = '';
/** Ask the plugin for the printer. `retry`: the user pressed Retry, so a failed connection tries again now
 *  instead of after its growing delay; otherwise its last error comes back at once. */
export async function hello(retry = false): Promise<void> {
  const offered = s.phase === 'noTarget' && s.candidates.length > 0;
  const was = s.info?.address ?? spoolsFor;
  reset();
  // A printer offered for a choice stays on screen while the plugin is asked again: no flicker to "Connecting".
  if (!offered) s.phase = 'connecting';
  const epoch = s.epoch;
  helloInFlight = true;
  try {
    const r: Info = await bridge.request({ type: 'hello', retry });
    if (epoch !== s.epoch) return;
    if (was && r.address !== was) Object.assign(s, { spools: [], spoolsError: '', spoolsLoaded: false });   // another printer
    spoolsFor = r.address;
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

/** The user clicked "Allow and use" on a printer the search found that OrcaSlicer does not let the plugin reach yet:
 *  the plugin has OrcaSlicer show its dialog now (on its UI thread, so a Yes is saved at once), then connects. Never
 *  asked without that click: a printer found on the network is not used until the user chooses it. */
async function allowFound(hosts: string[]): Promise<void> {
  const fresh = hosts.slice(0, 1);
  if (!fresh.length) return;
  try {
    const r = await bridge.request({ type: 'allow_hosts', hosts: fresh, user: true });
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
  if (c.needs_allow) { await allowFound([c.ip]); return; }
  const r = await run({ key: 'choose', label: t('act.choose'), cmd: 'choose_printer', args: { host: c.ip } });
  if (r.ok) { s.candidates = []; void hello(); }   // chosen: the offer is answered
}

/** Spools and slot links from Spoolman; false when the read failed. */
export async function loadSpools(quiet: boolean): Promise<boolean> {
  if (!targetKnown.value) return true;
  const epoch = s.epoch, address = s.info?.address;
  const r = await run({ key: 'spools', label: t('act.spools'), cmd: 'spools', quiet: true });
  // A hello for the same printer while this read was out keeps its answer: the read hello() asks for is refused as
  // 'busy' meanwhile, so dropping this one would leave the list empty until the next refresh.
  if (epoch !== s.epoch && (!s.info || s.info.address !== address)) return true;
  if (r.ok) {
    s.spools = r.result.spools ?? [];
    s.spoolsError = '';
    s.spoolsLoaded = true;
  } else if (r.reason !== 'busy') {
    s.spoolsError = r.error ?? t('common.unknown');
    if (!quiet) tracker.notify('error', t('msg.failed', { action: t('act.spools'), error: s.spoolsError }));
  }
  return r.ok || r.reason === 'busy';
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

/** The Stock tab lists spools only when the plugin says the list is usable (`available`); otherwise it says why not. */
export const stockVisible = computed(() => !s.stockError && s.stock?.available === true);

function onMessage(m: any): void {
  switch (m.type) {
    case 'status':
      if (s.info && typeof m.gen === 'number' && m.gen !== s.info.generation) break;   // the printer before a switch
      s.status = m.data; s.statusAt = Date.now();
      if (m.data?.limits) s.limits = { ...LIMITS, ...m.data.limits };   // per model: a Kobra 3 bed stops at 110
      if (m.data?.connected === true) keepHistory(m.data);
      if (m.data?.connected === true) s.offline = '';   // a disconnected status is followed by its 'offline' message
      // Statuses come every second, connected or not: only one that says connected means it answers again.
      if (m.data?.connected === true && (s.phase === 'unreachable' || s.phase === 'noCertificate') && !helloInFlight) void hello();
      break;
    // s.now too: the countdown is retry_at minus now, and the 1 s clock can lag behind in a throttled tab.
    case 'offline': s.offline = String(m.error ?? ''); s.retryAt = Number(m.retry_at) || 0; s.now = Date.now(); break;
    case 'frame': s.frame = m.image; s.video = false; s.camError = ''; s.camReason = ''; break;
    case 'camera_error': if (s.camOn) { s.camError = String(m.error ?? ''); s.camReason = String(m.reason ?? 'failed'); s.frame = ''; s.video = false; } break;
    case 'requirements': s.requirements = Array.isArray(m.items) ? m.items : []; s.checking = m.checking === true; break;
    case 'notice': tracker.notify('info', String(m.text ?? '')); break;
    case 'config': s.certificate = m.certificate ?? null; s.located = m.located ?? null; s.limits = { ...LIMITS, ...(m.limits ?? {}) }; configHandlers.forEach(h => h(m)); break;
    case 'selection_changed': void hello(); break;
    case 'show_tab': if (m.tab === 'settings') openSettings('print-h'); else if (['dash', 'stock', 'files'].includes(m.tab)) s.tab = m.tab; break;   // the print setup's "Plugin settings"
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

const stockTab = () => s.tab === 'dash' || s.tab === 'stock';
export function lease(): void {
  const vis = !s.hidden && s.tab === 'dash';
  // The stock is read for its own tab and for the dashboard, whose slot cards and drawing show the linked spools.
  bridge.post({ type: 'lease', camera: s.camOn && vis && s.widgets.includes('camera'), stock: !s.hidden && stockTab() && stockVisible.value, mse: playable() });
}

// ------------------------------------------------------------------ slot presets (filmatch)
// Read again whenever what a slot holds changes (material, colour, linked spool); Change remembers another preset.
const takeMatches = (r: any) => { s.matches = Object.fromEntries(((r?.matches ?? []) as PresetMatch[]).map(m => [String(m.slot), m])); };
export async function loadMatches(): Promise<void> {
  try { takeMatches(await bridge.request({ type: 'preset_matches' })); } catch { /* the cards just show no preset line */ }
}
export async function pickPreset(slot: number, name: string | null): Promise<void> {
  if (s.matchBusy) return;
  s.matchBusy = true;
  try { takeMatches(await bridge.request({ type: 'preset_pick', slot, name })); }
  catch (e) { tracker.notify('error', t('msg.failed', { action: t('match.change'), error: message(e) })); }
  finally { s.matchBusy = false; }
}
const holds = () => JSON.stringify((s.status?.slots ?? []).map(sl => [sl.global_index, sl.status, sl.type, sl.color, sl.sku, sl.rfid, sl.brand, sl.spool_id]));

export function start(): () => void {
  bridge.attach();
  const off = bridge.onMessage(onMessage);
  const onVis = () => { s.hidden = document.hidden; lease(); };
  document.addEventListener('visibilitychange', onVis);
  const timers = [
    window.setInterval(lease, 2000),
    window.setInterval(() => { s.now = Date.now(); }, 1000),
    window.setInterval(() => { if (stockTab() && !s.hidden) void loadStock(false); }, 5000),
    window.setInterval(() => { if (s.tab === 'dash' && !s.hidden) void loadUsage(); }, 10000),
  ];
  // Spoolman can change from elsewhere (Spooler, Spoolman's own page): re-read the links while the page shows.
  const auto = autoRefresh({ load: () => loadSpools(true), every: () => s.refreshS, held: userBusy, onFailing: f => { s.spoolsRetrying = f; } });
  const offCfg = onConfig(m => { const v = cleanEvery(m.settings?.spoolman_refresh_s); if (v !== s.refreshS) { s.refreshS = v; auto.restart(); } });
  // Spooler says right away when it linked or unlinked a spool (its presence's "links"): re-read without waiting.
  const offLinks = watch(() => s.stock?.spooler?.links, (now, was) => { if (was !== undefined && now !== was) void loadSpools(true); });
  // What the printer does goes in the Console too.
  const offState = watch(() => s.status?.state, (now, was) => { if (now && was && now !== was) note(t('console.state', { state: tMaybe(`status.state.${now}`, now) })); });
  const offHolds = watch(holds, (now, was) => { if (now !== was && s.status) void loadMatches(); });
  void hello();
  return () => { off(); offCfg(); offLinks(); offState(); offHolds(); auto.stop(); document.removeEventListener('visibilitychange', onVis); timers.forEach(clearInterval); };
}
