// MOCK evidence: the built page in owned headless Chrome (CSP, scripted bridge), screenshots in light/dark,
// en/pt-BR and several widths, with overflow and DOM measurements. Not a substitute for OrcaSlicer.
//   OUT=<dir> PAGE=<page with icons> node tests/page/shots.mjs
import { writeFile, mkdtemp, rm, readFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { launch, MOCK_HOST, HELPERS, preparePage } from './cdp.mjs';

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
  slots: [slot(0, -1, 0, {type: 'PETG', color: [62, 99, 221]}), slot(1, -1, 1, {status: 0, type: ''}), slot(2, -1, 2, {color: [244, 207, 120], type: 'PLA+'}),
    slot(3, 0, 0, {activity: 'loaded', spool_id: 7}), slot(4, 0, 1, {type: 'ABS', color: [20, 20, 20]}), slot(5, 0, 2, {status: 0, type: ''}), slot(6, 0, 3, {activity: 'loading', color: [120, 207, 213]})],
  loaded_slot: 3, ace_units: [{id: 0, auto_feed: true, drying: {status: 1, target_temp: 50, duration: 240, remain_time: 130, humidity: 28, current_temp: 47.5}}],
  can: {pause: true, resume: false, stop: true, move: false, heat: true, feed: false, print: false},
  features: {flow_calibration_support: true, camera_timelapse_support: true}, mac: 'A4:7D:9F:12:6C:3E',
  stats: {print_minutes: 37230, print_count: 214, filament_g: 18420}, assist: {'0': true, '1': false, '3': true, '4': true, '5': false}};
if (SCN === 'idle' || SCN === 'assist') Object.assign(VIEW, {state: 'idle', kobra_state: 'free', filename: '', progress: 0, layer: 0, total_layers: 0, elapsed_s: 0, remaining_s: 0,
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
__t.handler(CONFIG);
await settle();
const ans = (cmd, r) => { const m = [...__t.sent].reverse().find(x => x.type === 'cmd' && x.cmd === cmd); if (m) __t.handler({type: 'reply', id: m.id, result: r}); };
await sleep(50);
ans('spools', {spools: [{id: 7, name: 'Matte Black', vendor: 'Generic', material: 'PLA', colour: '#111111', remaining: 640, initial: 1000}, {id: 11, name: 'Cobalt Blue', vendor: 'Acme', material: 'PETG', colour: '#2850a8', remaining: 40, initial: 1000, low: true}]});
ans('stock', {spooler: {state: 'active', text: '', version: '0.20.1'}, stock: {state: 'ok', code: 'ok', text: '', key: 's:1', ts: Date.now() / 1000 - 30,
  rows: [{id: 7, name: 'Matte Black', vendor: 'Generic', material: 'PLA', colour: '#111111', colours: [], remaining: 640, initial: 1000, low: false, use_first: true, location: 'Shelf A'},
         {id: 11, name: 'Cobalt Blue', vendor: 'Acme', material: 'PETG', colour: '#2850a8', colours: [], remaining: 40, initial: 1000, low: true, use_first: false, location: 'Dry box'}]},
  same_spoolman: true, usage: 'kobracontrol', bindings: {'3': 7}, available: true, reason: null});
ans('device', {sent: true, assist: true});
ans('usage', {pending: [{file: 'gcodes/benchy.gcode', printer: '192.168.1.50', grams: {'3': 12.5}}], unconfirmed: [{id: 'a', at: Date.now() / 1000 - 7200, spool: 7, grams: 8.4, slot: 4, file: 'gcodes/desk_organiser.gcode', error: 'Spoolman timed out', job: 'j', printer: '192.168.1.50', printer_name: 'Bench Kobra'}],
  acknowledged: [], acknowledged_total: 0, save_error: '', restore_notice: ''});
if (SCN === 'offline') { __t.handler({type: 'status', data: {...VIEW, connected: false}}); __t.handler({type: 'offline', error: 'printer not reachable at 192.168.1.50', retry_at: Date.now() / 1000 + 24}); }
if (SCN === 'stale') { const real = Date.now; Date.now = () => real() + 4 * 60000; await sleep(1100); }
if (SCN === 'usage') { await sleep(50); document.querySelector('[data-test="usage-review"]')?.click(); }
if (SCN === 'camera') { document.querySelector('[data-test="camera"]').click(); await sleep(100); __t.handler({type: 'camera_error', error: 'x', reason: 'no_ffmpeg'}); }
// videos, videos-empty, videos-error, videos-delete: the Files tab's Time-lapses section in each of its states.
const TAB = SCN.startsWith('videos') ? 'files' : SCN;
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
  ans('file_details', {name: 'desk_organiser_plate_1.gcode', thumbnail: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="160" height="120"><rect width="160" height="120" fill="%23888"/></svg>',
    info: {estimated_s: 25816, layers: 380, filament_g: 102.9, layer_height: 0.2, nozzle_temp: 220, bed_temp: 60, nozzle: 0.4, printer_model: 'Anycubic Kobra X', model_ok: true},
    materials: [{paint_index: 0, material: 'PLA', colour: '#111111', grams: 84.1, slot: 3, slot_type: 'PLA', slot_colour: '#E5484D', check: 'ok'},
      {paint_index: 1, material: 'PETG', colour: '#2850a8', grams: 18.8, slot: 4, slot_type: 'ABS', slot_colour: '#141414', check: 'differs'}]});
}
if (SCN === 'assist') { const sw = document.querySelector('#assist-remain'); sw.scrollIntoView({block: 'center'}); sw.click(); await until(() => document.querySelector('.p-dialog')); }
if (SCN === 'dialog') { document.querySelector('[data-test="stop"]').focus(); document.querySelector('[data-test="stop"]').click(); await until(() => document.querySelector('.p-dialog')); }
await sleep(400);
`;
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
  ['camera', 'light', 'en', 1280, 720], ['usage', 'light', 'en', 1280, 720], ['usage', 'dark', 'pt_BR', 1280, 720], ['dialog', 'dark', 'pt_BR', 1280, 720],
]);
const dir = await mkdtemp(join(tmpdir(), 'kobra-shots-'));
const browser = await launch();
const metrics = [];
try {
  for (const [scn, theme, lang, width, height] of SCENES) {
    const file = join(dir, `${scn}.html`);
    await writeFile(file, preparePage(page, { version: '0.1.0', lang }));
    const p = await browser.newPage();
    await p.size(width, height, 1);
    await p.init(MOCK_HOST);
    await p.goto(pathToFileURL(file).href + '?theme=' + theme);
    const m = await p.evaluate(`(async () => { ${HELPERS} const SCN = ${JSON.stringify(scn)};
      await until(() => document.querySelector('#app > *'));
      ${STATE}
      const over = [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > innerWidth + 1 && getComputedStyle(e).position !== 'fixed'; })
        .slice(0, 5).map(e => e.tagName + '.' + String(e.className).slice(0, 40));
      const b = document.querySelector('.p-button'); const cs = b ? getComputedStyle(b) : null;
      return { overflowX: document.documentElement.scrollWidth > innerWidth, scrollWidth: document.documentElement.scrollWidth, innerWidth, overflowing: over,
        dom: document.getElementsByTagName('*').length, lang: document.documentElement.lang, dark: document.documentElement.classList.contains('orca-dark'),
        bodyFont: getComputedStyle(document.body).fontSize, buttonRadius: cs && cs.borderRadius, buttonFont: cs && cs.fontSize,
        violations: __t.violations, errors: __t.errors, rejections: __t.rejections }; })()`);
    const name = `kobra-${scn}-${theme}-${lang}-${width}x${height}.png`;
    await writeFile(join(OUT, name), await p.screenshot());
    metrics.push({ name, ...m });
    console.log(name, JSON.stringify({ overflowX: m.overflowX, overflowing: m.overflowing, dom: m.dom, lang: m.lang, dark: m.dark }));
    await p.close();
  }
} finally { await browser.close(); await rm(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); }
await writeFile(join(OUT, 'metrics-kobracontrol.json'), JSON.stringify(metrics, null, 2));
if (metrics.some(m => m.overflowX || m.violations.length || m.errors.length || m.rejections.length)) { console.log('PROBLEMS'); process.exit(1); }
console.log('OK');
