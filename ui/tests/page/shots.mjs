// MOCK evidence: the built page in owned headless Chrome (CSP, scripted bridge), screenshots in light/dark,
// all five languages and several widths, with overflow and DOM measurements. Not a substitute for OrcaSlicer.
//   OUT=<dir> PAGE=<page with icons> node tests/page/shots.mjs
// SCENES=<json> picks the scenes: [scene, theme, lang, width, height, scale = 1]. The store-* scenes are the
// pictures inside the listing and README images (scripts/marketing_images.py): a quiet day with no Spoolman
// reminders, today's date, and for store-status a camera frame read from FRAME=<jpeg file>.
import { writeFile, mkdtemp, rm, readFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { launch, MOCK_HOST, HELPERS, preparePage } from './cdp.mjs';
import { PRINT_DATA } from './print-data.mjs';

const OUT = process.env.OUT; const page = await readFile(process.env.PAGE, 'utf8');
await mkdir(OUT, { recursive: true });
const STATE = `
await until(() => __t.sent.find(m => m.type === 'hello'));
const hello = __t.sent.find(m => m.type === 'hello');
const DRY = {status: 0, target_temp: 0, duration: 0, remain_time: 0, humidity: null, current_temp: null};
const slot = (g, box, i, o) => ({global_index: g, box_id: box, box_pos: box < 0 ? 0 : box + 1, index: i, status: 5, type: 'PLA', color: [229, 72, 77], rfid: null, sku: null,
  activity: '', tray: g, usable: true, spool_id: null, ...o});
const VIEW = {connected: true, state: 'printing', preparing: false, kobra_state: 'printing', printer_name: 'Bench Kobra', model: 'Kobra X', firmware: '1.0',
  filename: 'desk_organiser_plate_1.gcode', progress: 37, layer: 142, total_layers: 380, elapsed_s: 4100, remaining_s: 7000, task_id: '1',
  nozzle_temp: 219.6, nozzle_target: 220, bed_temp: 59.8, bed_target: 60, fan_pct: 70, light_on: true, speed_mode: 2, files: [], 
  storage: {total: 8000, used: 2100}, skipped_objects: [], pause_reason: null, last_error: null, box_set_failed: false, updated_at: 1700000000, mode: 'ace_hub',
  // The print head's three slots are the photo's spools 1-3 (white, red, a multi-colour Spoolman spool); the fourth is empty with an ACE.
  slots: [slot(0, -1, 0, {color: [245, 245, 245]}), slot(1, -1, 1, {activity: 'loaded'}), slot(2, -1, 2, {color: [255, 140, 40], spool_id: 12}),
    slot(3, 0, 0, {spool_id: 7}), slot(4, 0, 1, {type: 'ABS', color: [20, 20, 20]}), slot(5, 0, 2, {status: 0, type: ''}), slot(6, 0, 3, {activity: 'loading', color: [120, 207, 213], percent: 30, weight: 300})],
  loaded_slot: 1, ace_units: [{id: 0, auto_feed: true, drying: {status: 1, target_temp: 50, duration: 240, remain_time: 130, humidity: 28, current_temp: 47.5}}],
  can: {pause: true, resume: false, stop: true, move: false, heat: true, feed: false, print: false},
  features: {flow_calibration_support: true, camera_timelapse_support: true}, mac: 'A4:7D:9F:12:6C:3E',
  stats: {print_minutes: 37230, print_count: 214, filament_g: 18420}, assist: {'0': true, '1': false, '3': true, '4': true, '5': false}};
if (STORE) Object.assign(VIEW, {updated_at: Date.now() / 1000, filename: 'desk_organiser.gcode'});
if (SCENE === 'store-ace') Object.assign(VIEW, {mode: 'ace_direct', slots: VIEW.slots.filter(s => s.box_id >= 0)});
if (SCN === 'idle' || SCN === 'assist' || SCENE === 'store-files') Object.assign(VIEW, {state: 'idle', kobra_state: 'free', filename: '', progress: 0, layer: 0, total_layers: 0, elapsed_s: 0, remaining_s: 0,
  nozzle_target: 0, bed_target: 0, can: {pause: false, resume: false, stop: false, move: true, heat: true, feed: true, print: true}});
const CONFIG = {type: 'config', settings: {host: '', printer_name: 'Bench Kobra', ui_language: 'auto', ffmpeg_path: '', camera_enabled: false, auto_leveling: true, vibration_compensation: true,
  spoolman_url: 'http://192.168.1.10:7912', spoolman_auto: true, spoolman_report_usage: true, spooler_hint_dismissed: false},
  certificate: {found: SCN !== 'nocert', source: 'Anycubic Slicer Next'}, spooler: {installed: true}, version: '0.1.0', limits: {nozzle_max: 300, bed_max: 100}};
if (SCN === 'nocert') __t.handler({type: 'reply', id: hello.id, error: 'no certificate', no_certificate: true});
else if (SCN === 'notarget') __t.handler({type: 'reply', id: hello.id, error: 'No Kobra X answered the network search. Enter the printer’s own address under Settings > Printer address.', no_target: true});
else if (SCN === 'different') __t.handler({type: 'reply', id: hello.id, error: 'A different Kobra X answered at 192.168.1.61. Use it? Kobra Control does not switch to another printer by itself.', no_target: true,
  candidates: [{ip: '192.168.1.61', name: 'Workshop KX', model: 'Anycubic Kobra X', needs_allow: false, different: true}]});
else {
  __t.handler({type: 'reply', id: hello.id, result: {address: '192.168.1.50', printer: 'Bench Kobra', generation: 1}});
  __t.handler({type: 'status', data: VIEW});
}
if (SCN === 'needs') CONFIG.ffmpeg = '';   // one requirement missing, with how to install it
__t.handler(CONFIG);
await settle();
const SUNSET = {id: 12, name: 'Sunset', vendor: 'Acme', material: 'PLA', colour: '#ff8c28', colours: ['#ff8c28', '#e5484d', '#7c3aed'], remaining: 520, initial: 1000, low: false, use_first: false, location: 'Shelf B'};
const ans = (cmd, r) => { const m = [...__t.sent].reverse().find(x => x.type === 'cmd' && x.cmd === cmd); if (m) __t.handler({type: 'reply', id: m.id, result: r}); };
await sleep(50);
ans('spools', {spools: [{id: 7, name: 'Matte Black', vendor: 'Generic', material: 'PLA', colour: '#111111', remaining: 640, initial: 1000}, SUNSET, {id: 11, name: 'Cobalt Blue', vendor: 'Acme', material: 'PETG', colour: '#2850a8', remaining: 40, initial: 1000, low: true}]});
ans('stock', {spooler: {state: 'active', text: '', version: '0.20.1'}, stock: {state: 'ok', code: 'ok', text: '', key: 's:1', ts: Date.now() / 1000 - 30,
  rows: [SUNSET, {id: 7, name: 'Matte Black', vendor: 'Generic', material: 'PLA', colour: '#111111', colours: [], remaining: 640, initial: 1000, low: false, use_first: true, location: 'Shelf A'},
         {id: 11, name: 'Cobalt Blue', vendor: 'Acme', material: 'PETG', colour: '#2850a8', colours: [], remaining: 40, initial: 1000, low: true, use_first: false, location: 'Dry box'}]},
  same_spoolman: true, usage: 'kobracontrol', bindings: {'2': 12, '3': 7}, available: true, reason: null});
ans('device', {sent: true, assist: true});
ans('usage', STORE ? {pending: [], unconfirmed: [], acknowledged: [], acknowledged_total: 0, save_error: '', restore_notice: ''} : {pending: [{file: 'gcodes/benchy.gcode', printer: '192.168.1.50', grams: {'3': 12.5}}], unconfirmed: [{id: 'a', at: Date.now() / 1000 - 7200, spool: 7, grams: 8.4, slot: 4, file: 'gcodes/desk_organiser.gcode', error: 'Spoolman timed out', job: 'j', printer: '192.168.1.50', printer_name: 'Bench Kobra'}],
  acknowledged: [], acknowledged_total: 0, save_error: '', restore_notice: ''});
if (SCN === 'offline') { __t.handler({type: 'status', data: {...VIEW, connected: false}}); __t.handler({type: 'offline', error: 'printer not reachable at 192.168.1.50', retry_at: Date.now() / 1000 + 24}); }
if (SCN === 'stale') { const real = Date.now; Date.now = () => real() + 4 * 60000; await sleep(1100); }
if (SCN === 'usage') { await sleep(50); document.querySelector('[data-test="usage-review"]')?.click(); }
if (SCENE === 'store-status') { document.querySelector('[data-test="camera"]').click(); await sleep(100); __t.handler({type: 'frame', image: FRAME}); }
if (SCN === 'camera') { document.querySelector('[data-test="camera"]').click(); await sleep(100); __t.handler({type: 'camera_error', error: 'x', reason: 'no_ffmpeg'}); }
// videos, videos-empty, videos-error, videos-delete: the Files tab's Time-lapses section in each of its states.
const TAB = SCN.startsWith('videos') ? 'files' : SCN === 'needs' ? 'settings' : SCN;
if (TAB === 'settings' || TAB === 'files') { document.querySelector('[data-tab="' + TAB + '"]').click(); await sleep(300); }
if (TAB === 'files') {
  ans('files', {files: [{name: 'desk_organiser_plate_1.gcode', size: 4200000, timestamp: Date.now()/1000 - 3600}, {name: 'benchy.gcode', size: 900000, timestamp: Date.now()/1000 - 86400},
    {name: 'cable_clips_x12.gcode', size: 1300000, timestamp: Date.now()/1000 - 3 * 86400}]});
  const video = (name, stamp, n, ago, duration, size) => ({filename: name + '-' + stamp + '_' + n + '.mp4', name, created: Date.now()/1000 - ago, duration, size, empty: !duration});
  const asked = [...__t.sent].reverse().find(x => x.type === 'cmd' && x.cmd === 'videos');
  if (SCN === 'videos-error') __t.handler({type: 'reply', id: asked.id, error: 'the printer did not answer the time-lapse list'});
  else ans('videos', {videos: SCN === 'videos-empty' ? [] : [video('desk_organiser_plate_1', '20261116215053', 8, 5400, 83, 14109048), video('benchy', '20261115101010', 7, 90000, 41, 6209048),
    video('cable_clips_x12', '20261114181500', 6, 2 * 86400, 0, 156), video('vase_spiral_tall', '20261110090000', 5, 6 * 86400, 3725, 1310000000)]});
  await sleep(100);
}
if (SCN === 'videos-delete') { const del = document.querySelector('[data-empty] [data-video-delete]'); del.focus(); del.click(); await until(() => document.querySelector('.p-dialog')); }
if (SCN === 'files') {
  document.querySelector('[data-print]').click(); await sleep(100);
  ans('file_details', {name: 'desk_organiser_plate_1.gcode', thumbnail: STORE ? THUMB : 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="160" height="120"><rect width="160" height="120" fill="%23888"/></svg>',
    info: {estimated_s: 25816, layers: 380, filament_g: 102.9, layer_height: 0.2, nozzle_temp: 220, bed_temp: 60, nozzle: 0.4, printer_model: 'Anycubic Kobra X', model_ok: true},
    materials: [{paint_index: 0, material: 'PLA', colour: '#111111', grams: 84.1, slot: 3, slot_type: 'PLA', slot_colour: '#E5484D', check: 'ok'},
      {paint_index: 1, material: 'PETG', colour: '#2850a8', grams: 18.8, slot: 4, slot_type: 'ABS', slot_colour: '#141414', check: 'differs'}]});
}
if (SCN === 'assist') { const sw = document.querySelector('#assist-remain'); sw.scrollIntoView({block: 'center'}); sw.click(); await until(() => document.querySelector('.p-dialog')); }
// toasts: what commands answered, bottom-left (an info, a success and an error that stays); needs: Settings' requirements.
if (SCN === 'toasts') { __t.handler({type: 'notice', text: 'Kobra Control found the printer at 192.168.1.50.'}); __t.handler({type: 'reply', id: 987654, error: 'Spoolman timed out'});
  document.querySelector('[data-test="pause"]')?.click(); await sleep(50); }
if (SCN === 'needs') { document.querySelector('.oui-settings-link[data-section="needs-h"]').click(); await sleep(200); }
if (SCN === 'dialog') { document.querySelector('[data-test="stop"]').focus(); document.querySelector('[data-test="stop"]').click(); await until(() => document.querySelector('.p-dialog')); }
await sleep(400);
// once the page has settled: the Filament panel just under the app bar
if (SCENE === 'store-ace') { scrollTo({top: document.querySelector('[data-test="ace-card"]').getBoundingClientRect().top + scrollY - 64, behavior: 'instant'}); await sleep(200); }
`;
// store-*: the same states under their own names. THUMB stands in for the plate picture a sliced file carries.
const STORE_AS = { 'store-dash': 'dash', 'store-status': 'dash', 'store-lan': 'settings', 'store-ace': 'idle', 'store-files': 'files' };
const THUMB = 'data:image/svg+xml;utf8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="12 -8 136 136"><rect x="12" y="-8" width="136" height="136" fill="#24203d"/>'
  + '<path d="M22 86 80 104 138 86 80 68Z" fill="#332d55"/><path d="M40 48v30l40 13V61Z" fill="#6240c8"/><path d="M120 48v30L80 91V61Z" fill="#4e33a0"/>'
  + '<path d="M40 48 80 35 120 48 80 61Z" fill="#c0acff"/><path d="M52 48 80 39 108 48 80 57Z" fill="#392c6a"/></svg>');
const FRAME = process.env.FRAME ? 'data:image/jpeg;base64,' + (await readFile(process.env.FRAME)).toString('base64') : '';
// The plate picture in the print dialog scenes: any PNG does (the plugin sends Metadata/plate_<n>.png).
const THUMB_PNG = (await readFile(new URL('../../../src/kobracontrol/ui/icon.png', import.meta.url))).toString('base64');
const SCENES = (process.env.SCENES ? JSON.parse(process.env.SCENES) : [
  // scene, theme, lang, width, height
  ['dash', 'dark', 'en', 1900, 1000], ['dash', 'light', 'en', 1900, 1000], ['dash', 'dark', 'en', 1280, 720], ['dash', 'light', 'en', 1280, 720],
  ['dash', 'dark', 'pt_BR', 1280, 720], ['dash', 'light', 'pt_BR', 1900, 1000], ['dash', 'dark', 'en', 720, 1000], ['dash', 'light', 'pt_BR', 720, 1000],
  ['dash', 'light', 'en', 1280, 2200], ['dash', 'dark', 'pt_BR', 720, 3400], ['dash', 'dark', 'en', 400, 3600],
  ['offline', 'dark', 'en', 1280, 720], ['offline', 'light', 'en', 1900, 1000], ['offline', 'dark', 'en', 720, 1000], ['stale', 'dark', 'en', 1280, 720],
  ['notarget', 'dark', 'en', 1900, 1000], ['notarget', 'light', 'en', 1280, 720], ['notarget', 'dark', 'pt_BR', 1280, 720], ['notarget', 'light', 'en', 720, 1000],
  ['different', 'dark', 'en', 1280, 720], ['nocert', 'light', 'en', 1280, 720], ['nocert', 'dark', 'pt_BR', 720, 1000],
  ['settings', 'dark', 'en', 1900, 1000], ['settings', 'light', 'en', 1280, 720], ['settings', 'dark', 'en', 720, 1000], ['settings', 'dark', 'pt_BR', 1280, 720],
  ['settings', 'light', 'pt_BR', 720, 1000],
  ['files', 'light', 'en', 1280, 720], ['files', 'dark', 'pt_BR', 1900, 1000], ['files', 'dark', 'en', 720, 1000],
  ['videos', 'dark', 'en', 1280, 900], ['videos', 'light', 'pt_BR', 1280, 900], ['videos', 'dark', 'en', 400, 1300], ['videos-empty', 'light', 'en', 1280, 900],
  ['videos-error', 'dark', 'en', 1280, 900], ['videos-delete', 'dark', 'pt_BR', 1280, 900],
  ['idle', 'light', 'en', 1280, 2200], ['idle', 'dark', 'en', 1900, 1400], ['idle', 'dark', 'pt_BR', 1280, 2200], ['idle', 'light', 'en', 720, 3600],
  ['idle', 'dark', 'en', 400, 4400], ['dash', 'dark', 'en', 1280, 2200], ['assist', 'dark', 'en', 1280, 900], ['assist', 'light', 'pt_BR', 1280, 900],
  ['toasts', 'light', 'en', 1280, 720], ['toasts', 'dark', 'en', 1280, 720], ['toasts', 'dark', 'en', 380, 900], ['needs', 'light', 'en', 1280, 720], ['needs', 'dark', 'pt_BR', 720, 1000],
  ['camera', 'light', 'en', 1280, 720], ['usage', 'light', 'en', 1280, 720], ['usage', 'dark', 'pt_BR', 1280, 720], ['dialog', 'dark', 'pt_BR', 1280, 720],
]);
const dir = await mkdtemp(join(tmpdir(), 'kobra-shots-'));
const browser = await launch();
const metrics = [];
try {
  for (const [scn, theme, lang, width, height, scale = 1] of SCENES) {
    const file = join(dir, `${scn}.html`);
    // print / print-warn / print-pick: the print dialog (print-pick: its slot picker open) (boot mode "print"), with a material warning in print-warn.
    const dialog = scn.startsWith('print') ? { mode: 'print', data: { ...PRINT_DATA, job: { ...PRINT_DATA.job, thumbnail: THUMB_PNG },
      trays: scn === 'print-warn' ? { '0': 4, '2': 7 } : PRINT_DATA.trays } } : {};
    await writeFile(file, preparePage(page, { version: '0.1.0', lang, ...dialog }));
    const p = await browser.newPage();
    await p.size(width, height, scale);
    await p.init(MOCK_HOST);
    await p.goto(pathToFileURL(file).href + '?theme=' + theme);
    const m = await p.evaluate(`(async () => { ${HELPERS} const SCENE = ${JSON.stringify(scn)}; const STORE = SCENE.startsWith('store-'); const SCN = ${JSON.stringify(STORE_AS[scn] ?? scn)};
      const THUMB = ${JSON.stringify(THUMB)}; const FRAME = ${JSON.stringify(scn === 'store-status' ? FRAME : '')};
      await until(() => document.querySelector('#app > *'));
      ${scn.startsWith('print') ? 'await settle();' + (scn === 'print-pick' ? "document.querySelector('[data-test=slot-0]').click(); await until(() => document.querySelector('.p-popover [role=radio]')); await sleep(400);" : '') : STATE}
      const over = [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > innerWidth + 1 && getComputedStyle(e).position !== 'fixed'; })
        .slice(0, 5).map(e => e.tagName + '.' + String(e.className).slice(0, 40));
      // Text cut inside its own box (a button, tab, chip or cell narrower than its words), which page overflow misses.
      const clipped = [...document.querySelectorAll('button, [role=tab], th, td, label, .p-tag, .p-button-label, .oui-chip, .p-select-label')]
        .filter(e => e.offsetParent && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible')
        .slice(0, 8).map(e => e.tagName + '.' + String(e.className).slice(0, 30) + ' ' + JSON.stringify((e.textContent || '').trim().slice(0, 30)));
      const b = document.querySelector('.p-button'); const cs = b ? getComputedStyle(b) : null;
      return { overflowX: document.documentElement.scrollWidth > innerWidth, clipped, scrollWidth: document.documentElement.scrollWidth, innerWidth, overflowing: over,
        dom: document.getElementsByTagName('*').length, lang: document.documentElement.lang, dark: document.documentElement.classList.contains('orca-dark'),
        bodyFont: getComputedStyle(document.body).fontSize, buttonRadius: cs && cs.borderRadius, buttonFont: cs && cs.fontSize,
        violations: __t.violations, errors: __t.errors, rejections: __t.rejections }; })()`);
    const name = `kobra-${scn}-${theme}-${lang}-${width}x${height}.png`;
    await writeFile(join(OUT, name), await p.screenshot());
    metrics.push({ name, ...m });
    console.log(name, JSON.stringify({ overflowX: m.overflowX, overflowing: m.overflowing, clipped: m.clipped, dom: m.dom, lang: m.lang, dark: m.dark }));
    await p.close();
  }
} finally { await browser.close(); await rm(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); }
await writeFile(join(OUT, 'metrics-kobracontrol.json'), JSON.stringify(metrics, null, 2));
if (metrics.some(m => m.overflowX || m.violations.length || m.errors.length || m.rejections.length)) { console.log('PROBLEMS'); process.exit(1); }
console.log('OK');
