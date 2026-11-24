// Behaviour tests of the built Kobra Control page (src/kobracontrol/ui/app.html), in owned headless Chrome under a
// host-like CSP, with a scripted OrcaSlicer bridge. Each scenario gets a fresh page.
//   node tests/page/run.mjs [name-filter]          PAGE=<page with icons> is set by tests/test_ui_page.py
import { readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { launch, MOCK_HOST, HELPERS, preparePage } from './cdp.mjs';
import { PRINT_DATA } from './print-data.mjs';
import { es } from '../../src/core/locales/es.ts';
import { de } from '../../src/core/locales/de.ts';
import { zhCN } from '../../src/core/locales/zh-CN.ts';
import { pl } from '../../src/core/locales/pl.ts';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../../..');

async function pageWithIcons() {
  if (process.env.PAGE) return readFile(process.env.PAGE, 'utf8');
  return execFileSync('python3', ['-c', 'import sys; sys.path.insert(0, "scripts"); import build; sys.stdout.write(build.page_html("app.html"))'],
    { cwd: repo, encoding: 'utf8', maxBuffer: 64 << 20 });
}

const PRELUDE = `
const DRY0 = {status: 0, target_temp: 0, duration: 0, remain_time: 0, humidity: null, current_temp: null};
const slot = (g, box, i, o) => ({global_index: g, box_id: box, box_pos: box < 0 ? 0 : box + 1, index: i, status: 5, type: 'PLA', color: [229, 72, 77], rfid: null, sku: null,
  activity: '', tray: g, usable: true, spool_id: null, ...o});
const SLOTS = () => [slot(0, -1, 0, {type: 'PETG', color: [62, 99, 221]}), slot(1, -1, 1, {status: 0, type: '', color: [255, 255, 255]}), slot(2, -1, 2),
  slot(3, 0, 0, {activity: 'loaded'}), slot(4, 0, 1, {type: 'ABS', color: [20, 20, 20]}), slot(5, 0, 2, {status: 0, type: ''}), slot(6, 0, 3, {activity: 'loading'})];
const VIEW = extra => ({connected: true, state: 'idle', preparing: false, kobra_state: 'free', printer_name: 'Bench Kobra', model: 'Kobra X', firmware: '1.0',
  filename: '', progress: 0, layer: 0, total_layers: 0, elapsed_s: 0, remaining_s: 0, task_id: '', nozzle_temp: 25, nozzle_target: 0, bed_temp: 24, bed_target: 0,
  fan_pct: 30, light_on: false, speed_mode: 2, storage: {}, skipped_objects: [], pause_reason: null, last_error: null,
  box_set_failed: false, updated_at: 1700000000, mode: 'ace_hub', slots: SLOTS(), loaded_slot: 3,
  ace_units: [{id: 0, auto_feed: false, drying: DRY0}], can: {pause: false, resume: false, stop: false, move: true, heat: true, feed: true, print: true}, ...extra});
const PRINTING = extra => VIEW({state: 'printing', kobra_state: 'printing', filename: 'benchy.gcode', progress: 37, layer: 142, total_layers: 380, elapsed_s: 4100, remaining_s: 7000,
  nozzle_temp: 219.6, nozzle_target: 220, bed_temp: 59.8, bed_target: 60, can: {pause: true, resume: false, stop: true, move: false, heat: true, feed: false, print: false}, ...extra});
const ASSIST = {'0': true, '3': false, '4': true, '5': false};
const CERT = {found: true, source: 'Anycubic Slicer Next'};
const SETTINGS = {host: '', printer_name: 'Bench Kobra', ui_language: 'auto', ffmpeg_path: '', camera_enabled: false, auto_leveling: true, vibration_compensation: true,
  spoolman_url: 'http://box:7912', spoolman_auto: true, spoolman_report_usage: true, spooler_hint_dismissed: false};
const CONFIG = extra => ({type: 'config', settings: SETTINGS, certificate: CERT, spooler: {installed: true, url: 'https://example.org/spooler', dismissed: false}, version: '0.1.0',
  limits: {nozzle_max: 300, bed_max: 100}, ...extra});
const REQS = (o) => ({type: 'requirements', checking: false, items: [{id: 'ffmpeg', state: 'missing', details: ''},
  {id: 'anycubic_slicer', state: 'missing', details: ''}, {id: 'printer_agents', state: 'missing', details: ''},
  {id: 'spoolman', state: 'ok', details: 'http://box:7912'}, {id: 'certificate', state: 'ok', details: 'bundled'},
  {id: 'spooler', state: 'ok', details: ''}].map(i => ({...i, ...((o || {})[i.id] || {})}))});
async function connect(gen) {
  await until(() => last('hello'), 'hello sent');
  await reply(last('hello'), {address: '192.168.1.50', printer: 'Bench Kobra', generation: gen || 1});
}
async function ready(view, gen) { await connect(gen); await post(CONFIG()); await post({type: 'status', data: view || VIEW()}); }
async function tab(name) { await click(q('[data-tab="' + name + '"]')); }
async function pick(root, label) {
  assert(root, 'select to open'); await reveal(root); root.click(); await until(() => q('.p-select-overlay') && !q('.p-select-overlay[class*="enter-active"]'), 'select overlay open');
  // the overlay is positioned when the option stops moving (a filtered list shifts while it focuses its search field)
  const first = qa('.p-select-overlay [role=option]')[0];
  let at = '', steady = 0;
  await until(() => { const r = first.getBoundingClientRect(), now = r.top + ':' + r.left; steady = now === at ? steady + 1 : 0; at = now; return steady >= 5; }, 'overlay in place');
  const opt = qa('.p-select-overlay [role=option]').find(o => text(o) === label);
  assert(opt, 'option ' + label + ' in ' + qa('.p-select-overlay [role=option]').map(text).join('|'));
  opt.click(); await settle(); await until(() => !q('.p-select-overlay'), 'overlay closed'); await settle();
}
// Errors: banners in an alert region and error toasts (role=alert). What commands answered is a toast, bottom-left.
const toastText = el => [text(q('.oui-toast-text > strong', el)), text(q('.oui-toast-body', el))].filter(Boolean).join(' ');
const alerts = () => [...qa('[role=alert] .oui-banner').map(text), ...qa('.oui-toast[role=alert]').map(toastText)].join(' | ');
const toasts = () => qa('.oui-toast').map(toastText).join(' | ');
// The job's state chip, then what the printer is doing in it (phase, pause or error reason).
const statusText = () => [text(q('[data-test="state"]')), text(q('[data-test="state-detail"]'))].filter(Boolean).join(' · ');
const ROWS = [{id: 7, filament_id: 70, name: 'Matte Black', vendor: 'Generic', material: 'ABS', colour: '#111111', colours: [], remaining: 500, initial: 1000, low: false, use_first: false, location: 'Shelf A'},
  {id: 11, filament_id: 110, name: 'White', vendor: 'Acme', material: 'PETG', colour: '#FAFAFA', colours: [], remaining: 40, initial: 1000, low: true, use_first: true, location: ''}];
const STOCK = extra => ({spooler: {state: 'active', text: 'Spooler is running', detail: '', version: '0.21.0'},
  stock: {state: 'ok', code: 'ok', text: '', rows: ROWS, key: 's1:3', ts: Date.now() / 1000}, same_spoolman: true, usage: 'kobracontrol', bindings: {},
  available: true, reason: null, ...extra});
const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
const ENTRY = {id: 'abc', at: null, spool: 7, grams: 12.5, slot: 4, file: 'gcodes/benchy.gcode', error: 'Spoolman timeout', job: 'j1', printer: '192.168.1.50', printer_name: 'Bench Kobra', spoolman: 'http://box:7912'};
const USAGE = extra => ({pending: [], unconfirmed: [], acknowledged: [], acknowledged_total: 0, save_error: '', restore_notice: '', ...extra});
const DETAILS = extra => ({name: 'benchy.gcode', thumbnail: PNG,
  info: {estimated_s: 25816, layers: 1875, filament_g: 102.99, layer_height: 0.16, nozzle_temp: 205, bed_temp: 60, nozzle: 0.4, printer_model: 'Anycubic Kobra X', model_ok: true},
  materials: [{paint_index: 0, material: 'PETG', colour: '#3E63DD', grams: 84.11, slot: 0, slot_type: 'PETG', slot_colour: '#3E63DD', check: 'ok'},
    {paint_index: 4, material: 'PLA', colour: '#E10600', grams: 18.88, slot: 4, slot_type: 'ABS', slot_colour: '#141414', check: 'differs'}], ...extra});
async function openDetails(details) {
  await ready(VIEW());
  await tab('files');
  await reply(last('cmd', 'files'), {files: [{name: 'benchy.gcode', size: 4200000, timestamp: 1700000000}]});
  await click(fileRow('benchy.gcode'));
  await reply(last('cmd', 'file_details'), details);
  await until(() => q('.oui-files-preview img'), 'file details shown');
}
// The Files tab is the shared file browser over a storage that only lists and deletes (the Kobra X has no folders), so
// it has no folder tree: rows carry data-file,
// the switch between the printer's two lists carries data-list, and the bar over the table holds
// the count and, with a selection, Clear and Delete. Its own confirmation answers to data-dlg="confirm" / "cancel".
const fileRow = name => q('[data-view="files"] [data-file="' + name + '"]');
const fileNames = () => qa('[data-view="files"] [data-file]').map(e => e.getAttribute('data-file'));
const filesBar = () => q('[data-view="files"] .oui-files-bar');
const filesCount = () => text(q('[data-view="files"] .oui-files-bar [aria-live]'));
const check = name => click(q('.oui-files-check input', fileRow(name)));
const CUBE = 'cube-20261107101500_1.mp4';
const VIDEOS = () => [{filename: 'benchy-20261116215053_8.mp4', name: 'benchy', created: 1794838471, duration: 83, size: 4109048, empty: false},
  {filename: CUBE, name: 'cube', created: 1794000000, duration: 0, size: 156, empty: true}];
const videoRow = name => fileRow(name);
async function openVideos(videos, view) {
  await ready(view || VIEW());
  await tab('files');
  eq(cmds('videos'), [], 'the time-lapses are not asked for until their list is opened');
  await click(q('[data-list="videos"]'));
  await until(() => last('cmd', 'videos'), 'videos asked');
  await reply(last('cmd', 'videos'), {videos: videos || VIDEOS()});
}
// After a delete the keyboard stays in the list (a row, or the list itself when it is empty), never on <body>.
const focusInList = () => { const list = q('[data-view="files"] .oui-files-list'); return !!list && list.contains(document.activeElement); };
// Shown to the user: in the page and not display: none (a hidden tab's content is neither).
const visible = el => !!el && !!el.offsetParent;
`;

const scenarios = [];
const test = (name, body, opts = {}) => scenarios.push({ name, body, ...opts });

// ------------------------------------------------------------------ connect and status
test('connect: hello first, the status renders, blank numbers are not zero', `
  await until(() => last('hello'), 'hello sent');
  assert(text(byTest('link')).includes('Connecting'), 'connecting pill: ' + text(byTest('link')));
  await connect();
  await post(CONFIG());
  assert(text(byTest('link')) === 'Connected', 'connected pill');
  assert(text(byTest('printer-head')).includes('Bench Kobra') && text(byTest('printer-head')).includes('192.168.1.50'), 'printer and address in the page header: ' + text(byTest('printer-head')));
  assert(!text(q('.oui-appbar')).includes('192.168.1.50'), 'the app bar holds the state only');
  await post({type: 'status', data: VIEW({updated_at: 0, nozzle_temp: 0, bed_temp: 0, nozzle_target: 0, bed_target: 0, fan_pct: 0})});
  assert(text(q('[data-heater-row="nozzle"] .kc-heat-read')).includes('—'), 'no report yet: nozzle is a dash, not 0: ' + text(q('[data-heater-row="nozzle"] .kc-heat-read')));
  await post({type: 'status', data: PRINTING()});
  eq(statusText(), 'Printing', 'state');
  const job = text(byTest('job-card'));
  assert(job.includes('benchy.gcode') && job.includes('37%'), 'file and progress: ' + job);
  assert(job.includes('Layer 142 / 380'), 'layers');
  assert(job.includes('1 h 8 min') && job.includes('1 h 56 min'), 'elapsed and remaining: ' + job);
  assert(text(q('[data-heater-row="nozzle"] .kc-heat-read')).includes('219.6') && text(q('[data-heater-row="bed"] .kc-heat-read')).includes('59.8'), 'temperatures');
  eq(q('[data-test="job-card"] [role=progressbar]').getAttribute('aria-valuenow'), '37', 'progress bar');
`);

test('requests carry the printer generation', `
  await ready(PRINTING(), 7);
  await click(q('[data-test="pause"]'));
  eq(cmds('pause').map(m => m.gen), [7], 'pause for generation 7');
`);

test('preparation phases read as printing with the phase named; pause says why', `
  await ready(VIEW({state: 'printing', preparing: true, kobra_state: 'auto_leveling', filename: 'x.gcode', can: {pause: false, resume: false, stop: true, move: false, heat: true, feed: false, print: false}}));
  eq(statusText(), 'Printing · auto-leveling', 'phase named');
  assert(q('[data-test="pause"]').disabled, 'pause off while preparing');
  eq(q('[data-test="pause"]').getAttribute('aria-describedby'), 'kc-busy', 'it points at the page banner');
  assert(text(byTest('busy-banner')).includes('Pause: Available once the print has finished preparing'), 'which says why: ' + text(byTest('busy-banner')));
  assert(!q('[data-test="stop"]').disabled, 'stop allowed');
  await post({type: 'status', data: VIEW({state: 'printing', preparing: true, kobra_state: 'nozzle_heating', can: {pause: false, resume: false, stop: true, move: false, heat: true, feed: false, print: false}})});
  eq(statusText(), 'Printing · heating the nozzle', 'phase follows');
  await post({type: 'status', data: VIEW({state: 'printing', preparing: true, kobra_state: 'ace_filament_unfeeding', can: {pause: false, resume: false, stop: true, move: false, heat: true, feed: false, print: false}})});
  eq(statusText(), 'Printing · retracting filament', 'mid-print ACE phase named');
  assert(!q('[data-test="stop"]').disabled, 'stop stays allowed through every phase');
  await post({type: 'status', data: VIEW({state: 'printing', preparing: true, kobra_state: 'ace_filament_feeding', phase_unit: 1, phase_channel: 2, can: {pause: false, resume: false, stop: true, move: false, heat: true, feed: false, print: false}})});
  eq(statusText(), 'Printing · feeding filament · ACE 1 · Slot 2', 'the slot being worked on is named');
  await post({type: 'status', data: VIEW({state: 'printing', preparing: true, kobra_state: 'nozzle_heating', phase_unit: null, phase_channel: null, can: {pause: false, resume: false, stop: true, move: false, heat: true, feed: false, print: false}})});
  eq(statusText(), 'Printing · heating the nozzle', 'no slot when the report carries none');
`);

test('only the print actions that apply are shown: none when idle, Pause while printing, Resume while paused', `
  await ready(VIEW());
  for (const k of ['pause', 'resume', 'stop', 'skip-open']) assert(!byTest(k), k + ' is not shown with no print');
  assert(text(byTest('job-card')).includes('No print is running'), 'the block says so: ' + text(byTest('job-card')));
  assert(!q('[data-test="job-card"] [role=progressbar]').offsetParent, 'no progress bar without a print');
  await post({type: 'status', data: PRINTING()});
  assert(!q('[data-test="pause"]').disabled && !byTest('resume') && !q('[data-test="stop"]').disabled, 'printing: Pause and Stop, no Resume');
  assert(q('[data-test="stop"]').classList.contains('p-button-outlined') && q('[data-test="stop"]').classList.contains('p-button-danger'), 'Stop is outlined red, not solid');
  await post({type: 'status', data: PRINTING({state: 'paused', can: {pause: false, resume: true, stop: true, move: true, heat: true, feed: true, print: false}})});
  assert(!byTest('pause') && !q('[data-test="resume"]').disabled, 'paused: Resume takes its place');
  await click(q('[data-test="resume"]'));
  eq(cmds('resume').length, 1, 'resume sent without asking');
`);

test('pending commands show what is awaited; errors persist with the reason', `
  await ready(PRINTING());
  await click(q('[data-test="pause"]'));
  assert(text(q('.notices')).includes('Pause: waiting for the printer'), 'awaiting: ' + text(q('.notices')));
  assert(q('[data-test="pause"]').disabled, 'no double send');
  await fail(last('cmd', 'pause'), 'printer refused the pause');
  assert(alerts().includes('Pause failed: printer refused the pause'), 'error shown: ' + alerts());
  await post({type: 'status', data: PRINTING()});
  assert(alerts().includes('printer refused'), 'error persists across status updates');
  await click(q('.oui-toast[role=alert] .oui-toast-close'));
  await until(() => !alerts(), 'closed by the user');
`);

// ------------------------------------------------------------------ protected actions
test('stop asks first: cancel sends nothing, confirm sends stop', `
  await ready(PRINTING(), 3);
  await click(q('[data-test="stop"]'));
  assert(dialogOpen() && dialogText().includes('Bench Kobra'), 'asks, naming the printer: ' + dialogText());
  await no();
  eq(cmds('stop'), [], 'cancel sends nothing');
  await click(q('[data-test="stop"]'));
  await yes();
  eq(cmds('stop').map(m => [m.args, m.gen]), [[{}, 3]], 'confirmed stop for generation 3');
  await reply(last('cmd', 'stop'), true);
  await until(() => toasts().includes('Stop sent'), 'result shown');
`);

test('dialog keeps focus inside and returns it', `
  await ready(PRINTING());
  q('[data-test="stop"]').focus();
  await press('Enter');
  await until(dialogOpen, 'stop asks');
  await until(() => dialogEl().contains(document.activeElement), 'focus moves into the dialog');
  for (let i = 0; i < 4; i++) { await press('Tab'); assert(dialogEl().contains(document.activeElement), 'Tab stays inside the dialog'); }
  await press('Tab', true);
  assert(dialogEl().contains(document.activeElement), 'Shift+Tab stays inside');
  eq(dialogEl().getAttribute('role'), 'dialog', 'role'); eq(dialogEl().getAttribute('aria-modal'), 'true', 'modal');
  await press('Escape');
  await until(() => !dialogOpen(), 'Escape cancels');
  await until(() => document.activeElement === q('[data-test="stop"]'), 'focus returns to the Stop button');
  eq(cmds('stop'), [], 'cancel sends nothing');
`);

test('heating asks first; blank never sends 0; limits come from config; Off needs no question', `
  await ready(VIEW());
  assert(q('[data-set="nozzle"]').disabled, 'Set disabled while blank');
  await type(q('#temp-nozzle'), '220');
  await click(q('[data-set="nozzle"]'));
  assert(dialogOpen() && dialogText().includes('220') && dialogText().includes('Bench Kobra'), 'names value and printer: ' + dialogText());
  assert(text(q('[data-dlg="yes"]')).includes('220'), 'the confirm button names the value');
  await no();
  eq(cmds('set_temp'), [], 'cancel sends nothing');
  await click(q('[data-set="nozzle"]'));
  await yes();
  eq(cmds('set_temp').map(m => m.args), [{nozzle: 220}], 'confirmed heat');
  await reply(last('cmd', 'set_temp'), true);
  await type(q('#temp-bed'), '60');
  await click(q('[data-set="bed"]'));
  await yes();
  eq(cmds('set_temp').map(m => m.args), [{nozzle: 220}, {bed: 60}], 'bed on its own');
  await reply(last('cmd', 'set_temp'), true);
  await click(q('[data-off="nozzle"]'));
  assert(!dialogOpen(), 'Off needs no confirmation');
  eq(cmds('set_temp').map(m => m.args)[2], {nozzle: 0}, 'off sends 0');
  await type(q('#temp-nozzle'), '999');
  assert(q('[data-set="nozzle"]').disabled, '999 refused before sending');
  assert(text(q('#temp-why-nozzle')).includes('300'), 'says the real limit from config: ' + text(q('#temp-why-nozzle')));
  await type(q('#temp-bed'), '101');
  assert(text(q('#temp-why-bed')).includes('100'), 'bed limit: ' + text(q('#temp-why-bed')));
  await type(q('#temp-nozzle'), '');
  assert(q('[data-set="nozzle"]').disabled, 'emptied: still no Set');
  eq(cmds('set_temp').length, 3, 'no command from blank or invalid fields');
`);

test('heat is refused by the page when the printer does not allow it', `
  await ready(VIEW({can: {pause: false, resume: false, stop: false, move: false, heat: false, feed: false, print: false}}));
  assert(q('#temp-nozzle').disabled && q('[data-off="nozzle"]').disabled, 'heating off');
  // said once for the panel, and the disabled field points at it
  assert(text(byTest('busy-banner')).includes('doesn’t allow heating'), 'says why: ' + text(byTest('busy-banner')));
  eq(qa('[data-view="dash"] .oui-banner').length, 1, 'in the page’s one banner');
  eq(q('#temp-nozzle').getAttribute('aria-describedby'), 'kc-busy', 'the field points at the reason');
`);

test('confirmed:false shows "sent, waiting"; confirmed:true shows success; a second home while one runs shows the error', `
  await ready(PRINTING());
  await click(q('[data-test="pause"]'));
  await reply(last('cmd', 'pause'), {confirmed: false});
  assert(toasts().includes('Pause sent; waiting for the printer'), 'waiting text: ' + toasts());
  assert(!qa('.oui-toast[data-toast-tone="success"]').length, 'not shown as success');
  await post({type: 'status', data: PRINTING({state: 'paused', can: {pause: false, resume: true, stop: true, move: true, heat: true, feed: true, print: false}})});
  await click(q('[data-test="resume"]'));
  await reply(last('cmd', 'resume'), {confirmed: true});
  assert(toasts().includes('Resume sent.') && qa('.oui-toast[data-toast-tone="success"]').length === 1, 'confirmed: plain success: ' + toasts());
  await click(q('[data-move="x+"]'));
  await reply(last('cmd', 'move'), {confirmed: false});
  assert(toasts().includes('Move sent; waiting'), 'move waits');
  await click(q('[data-home="z"]')); await yes();
  await reply(last('cmd', 'home'), {confirmed: false});
  assert(toasts().includes('Home sent; waiting'), 'home waits');
  await click(q('[data-home="xy"]')); await yes();
  await fail(last('cmd', 'home'), 'home is already running; try again when it ends');
  assert(alerts().includes('home is already running'), 'error persists: ' + alerts());
`);

test('motion: moves, step choice, home and motors off ask where they must', `
  await ready(VIEW());
  await click(q('[data-move="x+"]'));
  eq(cmds('move').map(m => m.args), [{axis: 'x', distance: 10}], 'default 10 mm step');
  await reply(last('cmd', 'move'), true);
  await click(q('[data-step="1"]'));
  await click(q('[data-move="z-"]'));
  eq(cmds('move').map(m => m.args)[1], {axis: 'z', distance: -1}, 'signed distance');
  await reply(last('cmd', 'move'), true);
  await click(q('[data-home="xyz"]'));
  assert(dialogOpen(), 'home asks'); await no();
  eq(cmds('home'), [], 'cancel homes nothing');
  await click(q('[data-home="xy"]')); await yes();
  eq(cmds('home').map(m => m.args), [{axes: 'xy'}], 'home xy');
  await reply(last('cmd', 'home'), true);
  await click(q('[data-test="motors-off"]'));
  assert(dialogOpen() && dialogText().includes('home'), 'motors off asks, and says homing is needed: ' + dialogText()); await yes();
  eq(cmds('motors_off').length, 1, 'motors off');
  await post({type: 'status', data: PRINTING()});
  assert(q('[data-move="x+"]').disabled && q('[data-home="z"]').disabled && q('[data-test="motors-off"]').disabled, 'moves off while printing');
  assert(text(byTest('busy-banner')).includes('idle or paused'), 'the page banner says why: ' + text(byTest('busy-banner')));
  eq(q('[data-move="x+"]').getAttribute('aria-describedby'), 'kc-busy', 'and the buttons point at it');
`);

test('object skip: the objects command runs when the section opens; list, confirm, skip, error path', `
  await ready(PRINTING());
  assert(!byTest('skip-body') && cmds('objects').length === 0, 'closed: nothing asked yet');
  await click(byTest('skip-open'));
  eq(cmds('objects').map(m => m.args), [{}], 'objects asked when the section opens');
  assert(text(byTest('skip-body')).includes('Asking the printer'), 'loading state: ' + text(byTest('skip-body')));
  await reply(last('cmd', 'objects'), {filename: 'benchy.gcode', objects: ['cube_1', 'cube_2', 'cube_3'], skipped: ['cube_3']});
  eq(qa('[data-object]').map(e => e.getAttribute('data-object')), ['cube_1', 'cube_2'], 'objects minus skipped');
  assert(byTest('skip').disabled, 'nothing chosen: disabled');
  await click(q('#obj-1'));
  await click(byTest('skip'));
  assert(dialogOpen() && dialogText().includes('cube_2'), 'asks, naming the object: ' + dialogText()); await no();
  eq(cmds('skip_objects'), [], 'cancel skips nothing');
  await click(byTest('skip')); await yes();
  eq(cmds('skip_objects').map(m => m.args), [{names: ['cube_2']}], 'skip sent');
  await reply(last('cmd', 'skip_objects'), true);
  await until(() => cmds('objects').length === 2, 'list asked again after a skip');
  await reply(last('cmd', 'objects'), {filename: 'benchy.gcode', objects: ['cube_1', 'cube_2', 'cube_3'], skipped: ['cube_3', 'cube_2']});
  eq(qa('[data-object]').map(e => e.getAttribute('data-object')), ['cube_1'], 'list refreshed');
`);

test('object skip: an error is shown with a retry; an empty list says so; the section closes with the print', `
  await ready(PRINTING());
  await click(byTest('skip-open'));
  await fail(last('cmd', 'objects'), 'no print is running');
  assert(text(byTest('skip-error')).includes('no print is running'), 'error: ' + text(byTest('skip-error')));
  await click(byTest('skip-retry'));
  eq(cmds('objects').length, 2, 'retry asks again');
  await reply(last('cmd', 'objects'), {filename: 'benchy.gcode', objects: [], skipped: []});
  assert(text(byTest('skip-body')).includes('no objects that can be skipped'), 'empty: ' + text(byTest('skip-body')));
  await post({type: 'status', data: VIEW()});
  assert(!byTest('skip-body'), 'closed when the print ends');
  assert(!byTest('skip-open'), 'nothing to skip with no print: the action is gone');
`);

test('fan, light and speed mode', `
  await ready(PRINTING());
  assert(q('[data-focus-key="fan"]').disabled, 'no Set for a blank fan field');
  await type(q('#fan'), '60');
  await click(q('[data-focus-key="fan"]'));
  eq(cmds('set_fan').map(m => m.args), [{pct: 60}], 'fan');
  await reply(last('cmd', 'set_fan'), true);
  await click(q('#light'));
  eq(cmds('set_light').map(m => m.args), [{on: true}], 'light on');
  await reply(last('cmd', 'set_light'), true);
  await pick(byTest('speed'), 'Sport');
  await click(btn('Apply', byTest('temps')));
  eq(cmds('set_speed').map(m => m.args), [{mode: 3}], 'speed mode number');
  await post({type: 'status', data: VIEW()});
  assert(text(byTest('speed-why')).includes('No print is running'), 'speed needs a print, and says so');
`);

// ------------------------------------------------------------------ ACE
test('ACE card: units, slots, loaded slot, empty slot, activity', `
  await ready(VIEW());
  assert(text(byTest('ace-mode')).includes('Spool holder and ACE together'), 'mode: ' + text(byTest('ace-mode')));
  eq(qa('.ace-g').map(text), ['ACE 1', 'Spool holder'], 'groups: the ACE, then the spool holder');
  eq(qa('[data-slot]').length, 7, 'one tile per slot');
  eq([qa('.kc-group[data-box="0"] [data-slot]').length, qa('.kc-group[data-box="-1"] [data-slot]').length], [4, 3], '4 ACE slots and 3 holder positions');
  assert(text(q('.kc-group[data-box="-1"] [data-slot="0"]')).includes('PETG'), 'a holder position shows its filament');
  assert(text(q('[data-slot="3"]')).includes('Loaded in the print head') && text(q('[data-slot="3"]')).includes('Slot 1'), 'loaded slot: ' + text(q('[data-slot="3"]')));
  assert(text(q('[data-slot="1"]')).includes('Empty'), 'empty slot');
  assert(text(q('[data-slot="6"]')).includes('Loading'), 'activity: ' + text(q('[data-slot="6"]')));
  assert(text(q('[data-slot="4"]')).includes('ABS'), 'material');
  assert(q('[data-feed="1"]').disabled && text(q('[data-slot="1"]')).includes('No filament in this slot'), 'feed refused on an empty slot, with the reason');
  assert(!/toolhead|\\bT[1-4]\\b/i.test(text(byTest('ace-card'))), 'no U1 wording');
`);

test('slot cards: the OrcaSlicer preset the Device tab reports, its score and reasons; Change remembers another', `
  await ready(VIEW());
  await until(() => last('preset_matches'), 'the cards ask for the presets once the slots are known');
  const ask = last('preset_matches');
  const choices = [{name: 'Generic PLA', score: 25, reasons: [['material', 'PLA'], ['generic', '']]},
                   {name: 'Polymaker PLA', score: 20, reasons: [['material', 'PLA']]}];
  const row = {slot: 2, name: 'Generic PLA', source: 'generic', score: 25, reasons: choices[0].reasons, confident: false, candidates: choices, remembered_key: ''};
  await reply(ask, {matches: [row]});
  await until(() => q('[data-match="2"]'), 'slot 3 shows its preset');
  const card = q('[data-match="2"]');
  assert(text(card).includes('Generic PLA') && text(card).includes('material PLA') && text(card).includes('Score 25'), 'name, reasons, score: ' + text(card));
  assert(q('.oui-status[data-state="warn"]', card), 'a close call is marked');
  assert(!q('[data-match="1"]'), 'an empty slot has no preset line');
  await click(q('.oui-match-change', card));
  await until(() => qa('.oui-match-option', card).length === 2, 'the candidates');
  await click(qa('.oui-match-option', card)[1]);
  const pick = last('preset_pick');
  eq([pick.slot, pick.name], [2, 'Polymaker PLA'], 'remembered for that slot');
  await reply(pick, {matches: [{...row, name: 'Polymaker PLA', source: 'remembered', score: 20, reasons: choices[1].reasons, confident: true, remembered_key: 'mat:|pla|'}]});
  await until(() => text(q('[data-match="2"]')).includes('Picked by hand'), 'the new pick, marked as picked by hand');
  await click(q('.oui-match-change', q('[data-match="2"]')));
  const auto = () => qa('.oui-match-option', q('[data-match="2"]')).find(b => text(b).includes('Automatic'));
  await until(auto, 'Automatic offered');
  await click(auto());
  eq(last('preset_pick').name, null, 'Automatic forgets the pick');
`);

test('slot cards: Change stays inside its card at four ACE columns and three holder columns', `
  await ready(VIEW({slots: SLOTS().map(s => ({...s, status: 5, type: s.type || 'PLA', color: s.type ? s.color : [229, 72, 77]}))}));   // all seven sources filled: the empty ones draw no preset line
  await until(() => last('preset_matches'), 'the cards ask for the presets');
  const c = [{name: 'Generic PLA', score: 25, reasons: [['material', 'PLA']]}];
  await reply(last('preset_matches'), {matches: [0, 1, 2, 3, 4, 5, 6].map(n => ({slot: n, name: 'Polymaker PLA Matte @Anycubic Kobra X', source: 'generic', score: 25, reasons: c[0].reasons, confident: false, candidates: c, remembered_key: ''}))});
  await until(() => qa('.sl-match').length === 7, 'every slot shows its preset');
  const cols = {};
  for (const width of ['', '1400px', '1200px', '1100px', '1000px', '900px']) {
    q('#app').style.width = width; q('#app').style.maxWidth = width || '';
    await settle();
    for (const box of ['0', '-1']) {
      const all = qa('.kc-group[data-box="' + box + '"] .oui-slot');
      cols[box] = Math.max(cols[box] || 0, new Set(all.map(t => Math.round(t.getBoundingClientRect().left))).size);
      for (const tile of all.filter(t => q('.sl-match', t))) {
        const t = tile.getBoundingClientRect(), chg = q('.oui-match-change', tile).getBoundingClientRect();
        assert(chg.left >= t.left - 1 && chg.right <= t.right + 1, 'Change inside its card (box ' + box + ', ' + (width || 'wide') + '): ' + [t.left, t.right, chg.left, chg.right]);
      }
    }
  }
  eq([cols['0'], cols['-1']], [4, 3], 'the widths reached four ACE columns and three holder columns');
  q('#app').style.width = ''; q('#app').style.maxWidth = '';
`);

test('slot cards: opening Change floats over the dashboard without growing it, stays in view above or below, and keyboard picks that preset', `
  await ready(VIEW({slots: SLOTS().map(s => ({...s, status: 5, type: s.type || 'PLA', color: s.type ? s.color : [229, 72, 77]}))}));
  await until(() => last('preset_matches'), 'the cards ask for the presets');
  const many = Array.from({length: 12}, (_, n) => ({name: 'Candidate PLA ' + n + ' @Anycubic Kobra X', score: 25 - n, reasons: [['material', 'PLA']]}));
  await reply(last('preset_matches'), {matches: [0, 1, 2, 3, 4, 5, 6].map(n => ({slot: n, name: many[0].name, source: 'generic', score: 25, reasons: many[0].reasons, confident: false, candidates: many, remembered_key: ''}))});
  await until(() => qa('.sl-match').length === 7, 'every slot shows its preset');
  const tile = q('[data-slot="4"]'), grid = tile.closest('.kc-group');
  const size = () => { const t = tile.getBoundingClientRect(), g = grid.getBoundingClientRect(); return [t.height, t.width, g.height, document.documentElement.scrollHeight]; };
  // Both placements: the card at the top of the view (list opens below) and at the bottom of it (list opens above).
  for (const edge of ['start', 'end']) {
    tile.scrollIntoView({block: edge}); await settle();
    const before = size();
    await click(q('.oui-match-change', tile));
    await until(() => qa('.oui-match-option', tile).length === 12, 'all twelve candidates are rendered (' + edge + ')');
    await settle();
    eq(size(), before, 'the card, its group and the page keep their size while the list is open (' + edge + ')');
    const list = q('.oui-match-list', tile), r = list.getBoundingClientRect(), opts = qa('.oui-match-option', tile);
    eq(getComputedStyle(list).position, 'absolute', 'the list floats (' + edge + ')');
    assert(r.top >= 0 && r.bottom <= innerHeight, 'the list is inside the viewport (' + edge + '): ' + [r.top, r.bottom, innerHeight]);
    const top = opts[0].getBoundingClientRect(), hit = document.elementFromPoint(top.left + top.width / 2, top.top + top.height / 2);
    assert(hit && opts[0].contains(hit), 'the first option is not covered or clipped by the dashboard (' + edge + ')');
    assert(opts.every(o => o.tabIndex >= 0 && !o.disabled), 'every option is a focusable button (' + edge + ')');
    await click(q('.oui-match-change', tile));
    await until(() => !q('.oui-match-list', tile), 'Change closes the list (' + edge + ')');
  }
  tile.scrollIntoView({block: 'end'}); await settle();
  await click(q('.oui-match-change', tile));
  await until(() => qa('.oui-match-option', tile).length === 12, 'the list reopens');
  const opt = qa('.oui-match-option', tile)[3];
  opt.focus(); eq(document.activeElement === opt, true, 'an option takes keyboard focus');
  await press('Enter');
  const pick = last('preset_pick');
  eq([pick.slot, pick.name], [4, many[3].name], 'Enter on an option remembers that candidate for that slot');
  await until(() => !q('.oui-match-list', tile), 'the list closes after a pick');
`, {size: [1280, 560]});

test('slot reports: brand, material name, percent and weight from the printer; box humidity when not drying', `
  await ready(VIEW({slots: SLOTS().map(s => (s.global_index === 4 ? {...s, brand: 'Acme', material_name: 'ABS Pro', percent: 40, weight: 400} : s)),
    ace_units: [{id: 0, auto_feed: false, humidity: 32, temp: 45, drying: DRY0}]}));
  const t = text(q('[data-slot="4"]'));
  assert(t.includes('Acme ABS Pro') && t.includes('40%') && t.includes('400 g'), 'slot details: ' + t);
  eq(q('[data-slot="4"] .oui-spool').dataset.level, '5', 'the spool is drawn at the ACE percentage (40%)');
  const unknown = q('[data-slot="2"] .oui-spool');
  eq([unknown.dataset.level, unknown.hasAttribute('data-unknown'), unknown.querySelector('.oui-spool-unknown')?.textContent], ['1', true, '?'],
    'loaded, no Spoolman spool and no percentage: the full reel in its colour with the unknown badge, never a made-up level');
  const empty = q('[data-slot="1"] .oui-spool');
  assert(empty.dataset.level === '8' && !empty.hasAttribute('data-unknown') && !empty.querySelector('.oui-spool-unknown'), 'an empty slot is the bare reel');
  assert(text(byTest('unit-humidity')).includes('32'), 'box humidity: ' + text(q('[data-unit="0"]')));
  await post({type: 'status', data: VIEW({ace_units: [{id: 0, auto_feed: true, humidity: 30, temp: 44, drying: {status: 1, target_temp: 50, duration: 86400, remain_time: 901, humidity: null, current_temp: null}}]})});
  const d = text(byTest('drying'));
  assert(d.includes('15 h 1 min left') && d.includes('Humidity 30 %') && d.includes('44'), 'drying uses box readings and remain_time minutes: ' + d);
  assert(!d.includes('86400') && !d.includes('24 h'), 'the constant duration is never shown');
`);

test('toolhead-only printer: only the print head group, no unit controls', `
  await ready(VIEW({mode: 'toolhead', slots: SLOTS().slice(0, 3), ace_units: [], loaded_slot: 0}));
  eq(qa('.ace-g').map(text), ['Spool holder'], 'one group');
  assert(!q('[data-unit]'), 'no auto-feed or drying without an ACE');
  assert(text(byTest('ace-mode')).includes('no ACE'), 'mode text');
`);

test('slot edit sends slot_set with the global index and #RRGGBB; the form survives status refreshes', `
  await ready(VIEW());
  await click(q('[data-edit="4"]'));
  const colour = q('#e4-c');
  assert(colour && q('label[for="e4-c"]'), 'labelled colour field');
  assert(colour.value === '#141414', 'starts from the slot colour: ' + colour.value);
  colour.value = '#00ff00'; colour.dispatchEvent(new Event('input', {bubbles: true})); await settle();
  await post({type: 'status', data: VIEW()});
  eq(q('#e4-c').value, '#00ff00', 'the edit survives a refresh');
  await click(btn('Save', q('.sl-form')));
  eq(cmds('slot_set').map(m => m.args), [{slot: 4, type: 'ABS', colour: '#00ff00'}], 'slot_set');
  assert(!dialogOpen(), 'no confirmation for an edit');
  await reply(last('cmd', 'slot_set'), true);
  await until(() => !q('.sl-form'), 'form closed after success');
`);

test('slot edit: the material can be changed', `
  await ready(VIEW());
  await click(q('[data-edit="3"]'));
  await pick(q('[data-edit-type="3"]'), 'PETG');
  await click(btn('Save', q('.sl-form')));
  eq(cmds('slot_set').map(m => m.args.type), ['PETG'], 'material');
`);

test('feed and retract ask first and send the slot', `
  await ready(VIEW());
  await click(q('[data-feed="4"]'));
  assert(dialogOpen() && dialogText().includes('ACE 1 · Slot 2') && dialogText().includes('Bench Kobra'), 'asks, naming slot and printer: ' + dialogText()); await no();
  eq(cmds('slot_feed'), [], 'cancel feeds nothing');
  await click(q('[data-feed="4"]')); await yes();
  eq(cmds('slot_feed').map(m => m.args), [{slot: 4}], 'feed');
  await reply(last('cmd', 'slot_feed'), true);
  assert(q('[data-retract="4"]').disabled && q('[data-retract="4"]').getAttribute('aria-describedby') === 'slot-other-4',
    'slot 3 is loaded: the printer would unload it, so slot 4 offers no Retract');
  await click(q('[data-retract="3"]')); await yes();
  eq(cmds('slot_retract').map(m => m.args), [{slot: 3}], 'retract');
  await reply(last('cmd', 'slot_retract'), true);
  await post({type: 'status', data: PRINTING()});
  assert(q('[data-feed="4"]').disabled && q('[data-retract="4"]').disabled, 'refused while printing (can.feed)');
`);

test('auto-feed switch per unit', `
  await ready(VIEW());
  await click(q('#auto-0'));
  eq(cmds('auto_feed').map(m => m.args), [{ace: 0, on: true}], 'auto_feed');
`);

test('drying: start with temperature and time asks first; invalid values are refused', `
  await ready(VIEW());
  assert(q('[data-dry-start="0"]').disabled, 'no start without values');
  await type(q('#dry-m-0'), '120');
  await type(q('#dry-t-0'), '90');
  assert(q('[data-dry-start="0"]').disabled, '90 °C refused');
  await type(q('#dry-t-0'), '50');
  assert(!q('[data-dry-start="0"]').disabled, 'valid');
  await click(q('[data-dry-start="0"]'));
  assert(dialogOpen() && dialogText().includes('50 °C') && dialogText().includes('2 h'), 'asks with the values: ' + dialogText()); await no();
  eq(cmds('dry_start'), [], 'cancel starts nothing');
  await click(q('[data-dry-start="0"]')); await yes();
  eq(cmds('dry_start').map(m => m.args), [{aces: [0], temp: 50, minutes: 120}], 'dry_start');
`);

test('drying: running unit shows remaining time, humidity and temperature; stop needs no question', `
  const drying = {status: 1, target_temp: 55, duration: 240, remain_time: 90, humidity: 31, current_temp: 52.4};
  await ready(VIEW({ace_units: [{id: 0, auto_feed: true, drying}]}));
  const t = text(byTest('drying'));
  assert(t.includes('Drying at 55 °C') && t.includes('1 h 30 min left') && t.includes('Humidity 31 %') && t.includes('52.4'), 'drying details: ' + t);
  assert(!q('[data-dry-start]'), 'no start form while drying');
  await click(q('[data-dry-stop="0"]'));
  assert(!dialogOpen(), 'stop asks nothing');
  eq(cmds('dry_stop').map(m => m.args), [{aces: [0]}], 'dry_stop');
  await post({type: 'status', data: VIEW({ace_units: [{id: 0, auto_feed: false, drying: {...DRY0, status: 1, target_temp: 45, remain_time: 30}}]})});
  assert(!text(byTest('drying')).includes('Humidity'), 'blank humidity is not shown as 0');
`);

// ------------------------------------------------------------------ Spoolman and stock
test('Spoolman: bind per slot asks first; unbind too', `
  await ready(VIEW({slots: SLOTS().map(s => (s.global_index === 3 ? {...s, spool_id: 7} : s))}));
  await reply(last('cmd', 'spools'), {spools: ROWS, bindings: {}, via: 'direct'});
  eq(qa('[data-pick]').filter(visible).length, 7, 'one picker per slot, on the Dashboard');
  await tab('stock');
  assert(visible(byTest('spool-source')) && text(byTest('spool-source')).includes('2 spools'), 'source line in the Stock tab\u2019s header: ' + text(byTest('spool-source')));
  await tab('dash');
  await pick(q('[data-pick="4"]'), '#11 Acme White · PETG · 40 g');
  assert(dialogOpen() && dialogText().includes('#11'), 'bind asks: ' + dialogText()); await yes();
  eq(cmds('bind').map(m => m.args), [{slot: 4, spool_id: 11}], 'bind');
  await reply(last('cmd', 'bind'), {});
  await pick(q('[data-pick="3"]'), 'No spool (unlink)');
  assert(dialogOpen(), 'unbind asks'); await yes();
  eq(cmds('unbind').map(m => m.args), [{slot: 3}], 'unbind');
`);

test('Spoolman: the spool picker search is fuzzy over brand, name and material; an id finds only that spool', `
  await ready(VIEW());
  const row = (id, vendor, name, material) => ({...ROWS[0], id, filament_id: id * 10, vendor, name, material});
  await reply(last('cmd', 'spools'), {spools: [row(1, 'Prusament', 'Rosé Verde', 'PLA'), row(11, 'Acme', 'White', 'PETG'), row(110, 'Polymaker', 'Marine', 'PLA'), row(7, '3D Fuel', 'Wood 1', 'PLA')], bindings: {}, via: 'direct'});
  const root = q('[data-pick="4"]'); await reveal(root); root.click();
  await until(() => q('.p-select-overlay .p-select-filter'), 'the search field');
  const ids = () => qa('.p-select-overlay [role=option]').map(o => (/^#(\\d+)/.exec(text(o)) || [0, 'none'])[1]).join(',');
  // typed with real key events, like a user: the search field is Vue-controlled, a set value and a fake event would not reach its model
  const found = async query => { await type(q('.p-select-overlay .p-select-filter'), query); await settle(); return ids(); };
  eq(await found('prus'), '1', 'a brand');
  eq(await found('ROSE'), '1', 'a name, any case and without the accent');
  eq(await found('pmk'), '110', 'the letters in order');
  eq(await found('PETG'), '11', 'a material');
  eq(await found('aew'), '11', 'the letters in order across brand and name');
  eq(await found('1'), '1', 'a plain id is that spool only: not #11, #110 or "3D Fuel Wood 1"');
  eq(await found('3'), '', 'a plain id no spool has finds nothing, though "3D Fuel" has the digit');
  eq(await found('#11'), '11', '#id is that spool only, not #110');
  eq(await found('zzz'), '', 'nothing matches');
  eq(cmds('bind').length, 0, 'filtering books nothing');
`);

test('status: a long file name wraps after _ - . first, two lines at most, full name in the tooltip', `
  await ready(PRINTING({filename: 'desk_organiser_plate-1.gcode'}));
  const n = byTest('job-name');
  eq(text(n), 'desk_organiser_plate-1.gcode', 'whole name shown');
  eq(n.getAttribute('title'), 'desk_organiser_plate-1.gcode', 'tooltip');
  eq(n.querySelectorAll('wbr').length, 4, 'a break opportunity after each _ - .');
  eq(getComputedStyle(n).webkitLineClamp, '2', 'two lines at most');
  eq(qa('[data-test="job-card"] .oui-job-name, [data-test="job-card"] .kc-job-name').filter(e => e.offsetParent).length, 1, 'the name is shown once');
`);

test('status: the photo spools are the print head slots, coloured like their slot cards; Spoolman first, then the ACE', `
  const MULTI = {id: 12, name: 'Rainbow', vendor: 'Acme', material: 'PLA', colour: '#ff0000', colours: ['#ff0000', '#00ff00', '#0000ff'], remaining: 250, initial: 1000};
  const HEAD = () => SLOTS().map(s => (s.global_index === 0 ? {...s, color: [250, 250, 250], spool_id: 11} : s.global_index === 2 ? {...s, spool_id: 12} : s));
  await ready(VIEW({slots: HEAD(), loaded_slot: 0}));
  const fig = () => q('[data-test="printer-figure"]');
  const spool = n => q('[data-test="printer-figure"] [data-figure-slot="' + n + '"]');
  const colours = () => [1, 2, 3, 4].map(n => spool(n).getAttribute('data-colors') || '');
  assert(fig() && fig().getAttribute('role') === 'img', 'photo in the status card');
  const box = fig().closest('.oui-job-thumb').getBoundingClientRect(), pic = fig().getBoundingClientRect();
  eq([box.width, box.height], [72, 72], 'in the status block’s fixed 72 px picture box');
  assert(pic.height <= 72 && pic.width <= 72, 'the photo fits it: ' + pic.width + 'x' + pic.height);
  eq(colours(), ['#fafafa', '', '#e5484d', ''], 'before Spoolman answers: the ACE colours of the print head slots');
  await reply(last('cmd', 'spools'), {spools: [...ROWS, MULTI], bindings: {}, via: 'direct'});
  eq(colours(), ['#fafafa', '', '#ff0000 #00ff00 #0000ff', ''], 'Spoolman colours, one band per colour');
  // each spool is painted like its slot card on the same page
  for (const n of [1, 2, 3]) {
    // the 4 px strip across the top of the slot card; an empty slot has none
    const head = q('[data-slot="' + (n - 1) + '"] .oui-slot-strip');
    const bands = qa('[data-test="printer-figure"] [data-figure-slot="' + n + '"] .kx-band').map(r => getComputedStyle(r).fill);
    if (!head) { assert(spool(n).hasAttribute('data-empty') && !bands.length, 'slot ' + n + ': empty card, empty reel'); continue; }
    const card = getComputedStyle(head);
    if (bands.length === 1) eq(bands[0], card.backgroundColor, 'slot ' + n + ' colour matches its card');
    else assert(bands.every(c => card.backgroundImage.includes(c)), 'slot ' + n + ' bands ' + bands.join() + ' in the card ' + card.backgroundImage);
  }
  assert(spool(4).hasAttribute('data-empty'), 'the fourth spool is empty: the head reports three slots next to an ACE');
  assert(spool(1).hasAttribute('data-active') && !spool(3).hasAttribute('data-active'), 'loaded slot marked');
  eq(text(byTest('figure-digit')), '1', 'toolhead shows the feeding slot');
  eq(fig().getAttribute('aria-label'), 'The printer and its spools: Slot 1 white PETG (feeding), Slot 2 empty, Slot 3 multicolour PLA, Slot 4 empty', 'label');
  await post({type: 'status', data: PRINTING({slots: HEAD(), loaded_slot: 2})});
  assert(byTest('figure-tube-active'), 'the feeding tube glows');
  eq(fig().getAttribute('data-tone'), 'busy', 'printing tone');
  eq(text(byTest('figure-digit')), '3', 'feeding slot 3');
  assert(fig().getAttribute('aria-label').includes('Slot 3 multicolour PLA (feeding)'), 'label follows the feeding slot');
  await post({type: 'status', data: PRINTING({slots: HEAD(), loaded_slot: 3})});
  assert(!byTest('figure-digit') && !byTest('figure-tube-active'), 'an ACE slot feeding: none of the four is marked');
`);

test('Spoolman without an address says where to set it', `
  await connect();
  await post(CONFIG({settings: {...SETTINGS, spoolman_url: ''}}));
  await post({type: 'status', data: VIEW()});
  await until(() => last('cmd', 'spools'), 'spools asked');
  await fail(last('cmd', 'spools'), 'Spoolman: no address set: enter one under Settings, or use Spooler with Spoolman');
  eq(qa('[data-pick]').length, 0, 'no spool chooser in the slot cards without Spoolman');
  await tab('stock');
  assert(visible(byTest('spool-source')), 'the Stock tab says it');
  eq(text(byTest('spool-source')), 'No Spoolman address', 'one short line, not the error three times');
  assert(visible(byTest('spoolman-card')) && text(byTest('spoolman-card')).includes('Set a Spoolman address under Settings'), 'where to set it: ' + text(byTest('spoolman-card')));
  await click(btn('Open Settings', byTest('spoolman-card')));
  assert(visible(q('#sm-s-h')), 'and its button opens Settings > Spoolman');
`);

test('Spoolman: the address Spooler uses is taken when none is set here, and Settings says so', `
  await connect();
  await post(CONFIG({settings: {...SETTINGS, spoolman_url: ''}, located: {address: '10.0.0.5', source: 'discovered', preset_host: '', preset_agent: '',
    spoolman_url: 'http://box:7912', spoolman_source: 'spooler'}}));
  await post({type: 'status', data: VIEW()});
  await reply(last('cmd', 'spools'), {spools: ROWS, bindings: {}});
  eq(qa('[data-pick]').filter(visible).length, 7, 'the slot pickers work from the Spoolman of Spooler');
  await tab('stock');
  eq(text(byTest('spool-source')), '2 spools in Spoolman', 'and the Stock tab counts its spools');
  assert(!text(q('[data-view="stock"]')).includes('Set a Spoolman address'), 'no contradiction: nothing asks for an address');
  await tab('settings');
  assert(text(byTest('sm-from')).includes('Spooler’s Spoolman is used: http://box:7912'), 'source: ' + text(byTest('sm-from')));
`);

test('stock tab: choose the slot once on the left, then one Link per row; it asks first', `
  await ready(VIEW());
  await reply(last('cmd', 'stock'), STOCK());
  await reply(last('cmd', 'spools'), {spools: ROWS, bindings: {}});
  await until(() => byTest('stock-card'), 'stock list');
  assert(!q('[data-view="dash"] [data-stock]') && !q('[data-view="dash"] [data-test="stock-card"]'), 'the stock is not on the dashboard');
  assert(text(q('[data-tab="stock"]')).includes('Stock') && text(q('[data-tab="stock"]')).includes('2'), 'its own tab, with the spool count: ' + text(q('[data-tab="stock"]')));
  await tab('stock');
  assert(byTest('stock-card').offsetParent, 'shown');
  eq(qa('[data-stock]').length, 2, 'two spools listed');
  const targets = qa('[data-stock-target]');
  eq(targets.map(b => b.getAttribute('data-stock-target')), ['3', '4', '5', '6', '0', '1', '2'], 'every slot is a place a spool can go, the ACE first, then the spool holder');
  eq(q('[data-test="stock-slot"]').getAttribute('role'), 'radiogroup', 'one of them is chosen');
  eq(targets.filter(b => b.getAttribute('aria-checked') === 'true').map(b => b.getAttribute('data-stock-target')), ['3'], 'the first one to start with');
  assert(text(q('[data-stock-target="1"]')).includes('Empty'), 'an empty slot says so: ' + text(q('[data-stock-target="1"]')));
  await click(q('[data-stock-target="4"]'));
  eq(q('[data-stock-target="4"]').getAttribute('aria-checked'), 'true', 'ACE 1 · Slot 2 chosen');
  eq(text(q('[data-stock="11"]')), 'Link to Slot 2', 'the row action names the chosen slot');
  eq(q('[data-stock="11"]').getAttribute('aria-label'), 'Link spool #11 Acme White to ACE 1 · Slot 2', 'in full for a screen reader');
  await click(q('[data-stock="11"]'));
  assert(dialogOpen() && dialogText().includes('ACE 1 · Slot 2') && dialogText().includes('#11'), 'asks: ' + dialogText()); await no();
  eq(cmds('stock_assign'), [], 'cancel links nothing');
  await click(q('[data-stock="11"]')); await yes();
  eq(cmds('stock_assign').map(m => m.args), [{slot: 4, spool_id: 11, key: 's1:3'}], 'stock_assign');
`);

test('stock tab: inventory grouping by material, manufacturer or location keeps totals, search and linking', `
  const mk = (id, name, vendor, material, location, remaining, initial) => ({id, filament_id: id * 10, name, vendor, material, colour: '#336699', colours: [], remaining, initial, low: false, use_first: false, location});
  const GROWS = [mk(1, 'Red', 'Acme', 'PLA', 'Shelf A', 500, 1000), mk(2, 'Blue', 'Acme', 'PLA', 'Shelf A', 250, 1000), mk(3, 'Grey', 'Bolt', 'PETG', '', 100, 1000),
    mk(4, 'Mystery', '', '', '', null, null), mk(5, 'Odd', 'Acme', 'No material', '', 10, 100)];
  await ready(VIEW());
  await reply(last('cmd', 'stock'), STOCK({stock: {...STOCK().stock, rows: GROWS}}));
  await reply(last('cmd', 'spools'), {spools: GROWS, bindings: {}});
  await until(() => byTest('stock-card'), 'stock list');
  await tab('stock');
  const ids = () => qa('[data-view="stock"] [data-spool]').map(r => r.dataset.spool);
  const heads = () => qa('[data-view="stock"] .sc-ghead');
  const head = label => heads().find(h => text(q('strong', h)) === label);
  // default: the flat list as before, no headers
  eq(text(q('[data-test="stock-group"]')).includes('No grouping'), true, 'default is no grouping: ' + text(q('[data-test="stock-group"]')));
  eq(ids(), ['1', '2', '3', '4', '5'], 'flat list');
  eq(heads().length, 0, 'no group headers by default');
  // material: a missing material and a material literally named "No material" are two groups
  await pick(q('[data-test="stock-group"]'), 'Group by material');
  await until(() => heads().length === 4, 'four material groups');
  eq(heads().map(h => text(q('strong', h))), ['No material', 'No material', 'PETG', 'PLA'], 'alphabetical, the two No material apart');
  const pla = head('PLA');
  assert(text(pla).includes('2 spools') && text(pla).includes('750 g'), 'PLA count and summed grams: ' + text(pla));
  assert(text(head('PETG')).includes('1 spool') && text(head('PETG')).includes('100 g'), 'PETG: ' + text(head('PETG')));
  eq(heads().map(h => h.getAttribute('aria-expanded')), ['true', 'true', 'true', 'true'], 'all open');
  eq(ids().length, 5, 'every spool still listed');
  // collapse hides only that group's rows; the header stays
  const before = cmds('stock_assign').length;
  await click(pla);
  eq(cmds('stock_assign').length, before, 'a header click links nothing');
  eq(head('PLA').getAttribute('aria-expanded'), 'false', 'PLA closed');
  eq(ids().sort(), ['3', '4', '5'], 'PLA rows hidden');
  assert(q('[data-stock="3"]') && !q('[data-stock="1"]'), 'other rows keep their Link buttons');
  // the closed group is per mode and value: another mode starts open, back again it is still closed
  await pick(q('[data-test="stock-group"]'), 'Group by manufacturer');
  await until(() => head('Acme'), 'manufacturer groups');
  eq(heads().map(h => text(q('strong', h))), ['Acme', 'Bolt', 'No manufacturer'], 'manufacturer groups');
  assert(text(head('Acme')).includes('3 spools') && text(head('Acme')).includes('760 g'), 'Acme: ' + text(head('Acme')));
  eq(ids().length, 5, 'nothing closed in this mode');
  await pick(q('[data-test="stock-group"]'), 'Group by location');
  await until(() => head('Shelf A'), 'location groups');
  eq(heads().map(h => text(q('strong', h))), ['No location', 'Shelf A'], 'location groups');
  assert(text(head('No location')).includes('3 spools'), 'No location: ' + text(head('No location')));
  await pick(q('[data-test="stock-group"]'), 'Group by material');
  await until(() => head('PLA'), 'material again');
  eq(head('PLA').getAttribute('aria-expanded'), 'false', 'PLA is still closed');
  await click(head('PLA'));
  eq(ids().length, 5, 'opened again');
  // search narrows the groups; their totals follow
  await type(q('[data-view="stock"] input[type=search]'), 'blue');
  await until(() => ids().length === 1, 'filtered');
  eq(heads().map(h => text(q('strong', h))), ['PLA'], 'only the matching group stays');
  assert(text(head('PLA')).includes('1 spool') && text(head('PLA')).includes('250 g'), 'totals of what is shown: ' + text(head('PLA')));
  await type(q('[data-view="stock"] input[type=search]'), '');
  await until(() => ids().length === 5, 'cleared');
  // linking is unchanged: it asks first, the header does nothing
  await click(q('[data-stock="3"]'));
  assert(dialogOpen() && dialogText().includes('#3'), 'asks: ' + dialogText()); await no();
  eq(cmds('stock_assign'), [], 'cancel links nothing');
  await click(q('[data-stock="3"]')); await yes();
  eq(cmds('stock_assign').map(m => m.args), [{slot: 3, spool_id: 3, key: 's1:3'}], 'stock_assign');
  // back to the flat list
  await pick(q('[data-test="stock-group"]'), 'No grouping');
  await until(() => heads().length === 0, 'headers gone');
  eq(ids(), ['1', '2', '3', '4', '5'], 'flat again');
`);

test('stock tab: rows say which slot holds them, and the spool in the chosen slot reads Linked', `
  await ready(VIEW());
  await reply(last('cmd', 'stock'), STOCK({stock: {...STOCK().stock, rows: [{...ROWS[0], bound_slot: 3}, {...ROWS[1], bound_slot: null}]}}));
  await until(() => byTest('stock-card'), 'stock list');
  await tab('stock');
  eq(text(q('[data-spool="7"] [data-test="stock-in"]')), 'ACE 1 · Slot 1', 'where it is loaded');
  assert(!q('[data-spool="11"] [data-test="stock-in"]'), 'a spool in no slot has no chip');
  await click(q('[data-stock-target="0"]'));
  assert(q('[data-stock="7"]') && !q('[data-linked]'), 'another slot is chosen: it can be linked there');
  await click(q('[data-stock-target="3"]'));
  eq(text(q('[data-linked="7"]')), 'Linked', 'already in the chosen slot');
  assert(!q('[data-stock="7"]') && q('[data-stock="11"]'), 'no Link button for it, one for the other');
  // level bars: green, amber when low, red when almost empty
  eq(q('[data-spool="7"] .oui-level').getAttribute('data-tone'), 'normal', '500 of 1000 g');
  eq(q('[data-spool="11"] .oui-level').getAttribute('data-tone'), 'critical', '40 of 1000 g is almost empty');
  assert(text(q('[data-spool="11"]')).includes('low'), 'and said in words: ' + text(q('[data-spool="11"]')));
`);

test('stock tab: search, material and same-material filters; Refresh reads Spoolman and the stock again', `
  await ready(VIEW());
  await reply(last('cmd', 'stock'), STOCK());
  await reply(last('cmd', 'spools'), {spools: ROWS, bindings: {}});
  await until(() => byTest('stock-card'), 'stock list');
  await tab('stock');
  const ids = () => qa('[data-view="stock"] [data-spool]').map(r => r.dataset.spool);
  eq(ids(), ['7', '11'], 'both spools');
  assert(text(byTest('stock-head')).includes('2 spools in Spoolman (the same one Spooler uses)') && text(byTest('stock-head')).includes('Spooler 0.21.0'), 'source and age in the page header: ' + text(byTest('stock-head')));
  await type(q('[data-view="stock"] input[type=search]'), 'shelf a');
  await until(() => ids().length === 1, 'filtered');
  eq(ids(), ['7'], 'search finds a location');
  assert(text(q('[data-view="stock"] .oui-toolbar')).includes('1 of 2 spools'), 'count: ' + text(q('[data-view="stock"] .oui-toolbar')));
  await type(q('[data-view="stock"] input[type=search]'), '');
  await until(() => ids().length === 2, 'cleared');
  await click(q('[data-stock-target="0"]'));
  await click(q('#stock-fit'));
  eq(ids(), ['11'], 'same material as the chosen slot (Spool holder · Slot 1 holds PETG)');
  await click(q('[data-stock-target="4"]'));
  eq(ids(), ['7'], 'follows the chosen slot (ACE 1 · Slot 2 holds ABS)');
  await click(q('[data-stock-target="1"]'));
  eq(ids(), ['7', '11'], 'an empty slot fits any material');
  const stock = cmds('stock').length, spools = cmds('spools').length;
  await click(byTest('stock-refresh'));
  await until(() => cmds('spools').length === spools + 1 && cmds('stock').length > stock, 'both asked again');
  assert(cmds('stock').some(m => m.args.refresh === true), 'the stock with refresh: ' + JSON.stringify(cmds('stock').map(m => m.args)));
`);

test('stock tab lists only a usable list; the lease flag follows; Settings says what is missing', `
  await ready(VIEW());
  await reply(last('cmd', 'stock'), STOCK());
  await until(() => byTest('stock-card'), 'usable list: shown');
  await until(() => last('lease').stock === true, 'lease: stock on', 15000);
  const states = [
    ['Spooler absent', STOCK({available: false, reason: 'absent', spooler: {state: 'absent', text: '', version: ''}})],
    ['Spooler without a list for this plugin', STOCK({available: false, reason: 'unsupported', stock: {state: 'missing', code: 'no_origin', text: 'none', rows: [], key: ''}})],
    ['Spooler waiting for its first list', STOCK({available: false, reason: 'waiting'})],
    ['stale list', STOCK({available: false, reason: 'stale', stock: {...STOCK().stock, state: 'stale'}})],
    ['unreadable list', STOCK({available: false, reason: 'unreadable', stock: {...STOCK().stock, state: 'error', code: 'unreadable'}})],
  ];
  for (const [what, view] of states) {
    const n = cmds('stock').length;
    await until(() => cmds('stock').length > n, 'the page asks for the stock again', 8000);   // every 5 s
    await reply(last('cmd', 'stock'), view);
    assert(!byTest('stock-card') && !q('[data-stock]'), what + ': no list');
    assert(byTest('spoolman-card'), what + ': the Stock tab keeps its place and says why');
    assert(!/[0-9]/.test(text(q('[data-tab="stock"]'))), what + ': no count on the tab: ' + text(q('[data-tab="stock"]')));
  }
  await until(() => last('lease').stock === false, 'lease: stock off when there is no usable list (renewed every 2 s)');
  await tab('settings');
  assert(text(byTest('spooler-no-stock')).includes('needs a Spooler version that supports Kobra Control'), 'Settings says why: ' + text(q('.sv')));
`);

test('stock without Spooler\'s list: Kobra Control\'s own Spoolman list, never an endless wait', `
  await ready(VIEW());
  await tab('stock');
  const own = STOCK({same_spoolman: null, spooler_reason: 'waiting', stock: {...STOCK().stock, code: 'own', source: 'spoolman', key: 'spoolman:http://box:7912', ts: null}});
  await reply(last('cmd', 'stock'), own);
  await until(() => byTest('stock-card') && q('[data-stock="7"]'), 'the own list is shown');
  assert(text(byTest('stock-head')).includes('From Spoolman · 2 spools'), 'says where the list comes from: ' + text(byTest('stock-head')));
  assert(!text(byTest('stock-head')).includes('Spooler 0.21.0'), 'no Spooler version for a list Spooler did not make');
  assert(text(byTest('stock-own')).includes('comes straight from Spoolman'), 'says why: ' + text(byTest('stock-own')));
  const n = cmds('stock').length;
  await until(() => cmds('stock').length > n, 'asked again', 8000);
  await reply(last('cmd', 'stock'), STOCK({available: false, reason: 'unsupported', stock: {state: 'missing', code: 'waiting', text: 'Waiting for Spooler\\u2019s stock list…', rows: [], key: ''}}));
  await until(() => byTest('spoolman-card'), 'no list');
  assert(text(byTest('spoolman-card')).includes('doesn’t share its stock with Kobra Control'), 'no endless wait: ' + text(byTest('spoolman-card')));
  assert(qa('[data-test="spoolman-card"] button').length === 1, 'with the way to Settings');
`);

test('same printer: a selection_changed keeps the Spoolman spools (they used to vanish until the next refresh)', `
  await ready(VIEW());
  await until(() => last('cmd', 'spools'), 'spools asked');
  const first = last('cmd', 'spools');
  await post({type: 'selection_changed'});
  await until(() => sent().filter(m => m.type === 'hello').length === 2, 'hello again');
  await reply(last('hello'), {address: '192.168.1.50', printer: 'Bench Kobra', generation: 1});
  await post({type: 'status', data: VIEW()});
  await reply(first, {spools: ROWS, bindings: {}});
  await tab('stock');
  await until(() => text(byTest('spool-source')).includes('2 spools'), 'the spools stay: ' + text(byTest('spool-source')));
  await post({type: 'selection_changed'});
  await reply(last('hello'), {address: '192.0.2.60', printer: 'Other Kobra', generation: 2});
  await until(() => !text(byTest('spool-source')).includes('2 spools'), 'another printer: read again, not shown from the old one');
`);

test('setup hints: an OctoPrint physical printer is called out; the agent steps until kobracontrol is the agent', `
  await connect();
  await post(CONFIG({setup: {kobra: true, agent: '', host_type: 'octoprint', host: '192.0.2.88'}}));
  await post({type: 'status', data: VIEW()});
  await until(() => byTest('setup-octoprint'), 'OctoPrint warning');
  assert(text(byTest('setup-octoprint')).includes('192.0.2.88') && text(byTest('setup-octoprint')).includes('no OctoPrint server'), text(byTest('setup-octoprint')));
  assert(!byTest('setup-steps'), 'one hint at a time');
  await click(byTest('setup-octo-bridge'));
  await until(() => byTest('bridge-address'), 'the OctoPrint notice opens the upload bridge settings');
  await tab('dash');
  await post(CONFIG({setup: {kobra: true, agent: '', host_type: 'octoprint', host: ''}}));
  await until(() => byTest('setup-steps') && !byTest('setup-octoprint'), 'no print host: the steps');
  assert(text(byTest('setup-steps')).includes('Printer Agent to kobracontrol'), text(byTest('setup-steps')));
  await click(byTest('setup-dismiss'));
  eq(last('save_settings').settings, {setup_hint_dismissed: true}, 'Don\\'t show again is saved');
  await post(CONFIG({setup: {kobra: true, agent: 'kobracontrol', host_type: 'octoprint', host: '192.0.2.88'}}));
  await until(() => !byTest('setup-steps') && !byTest('setup-octoprint'), 'with the kobracontrol agent: nothing to say');
  await post(CONFIG({setup: {kobra: false, agent: '', host_type: 'octoprint', host: '192.0.2.9'}}));
  await until(() => !byTest('setup-octoprint'), 'not a Kobra X preset: nothing to say');
`);

// ------------------------------------------------------------------ filament use
test('filament use: nothing pending shows no card, and the page asked for it', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'), 'usage asked');
  eq(last('cmd', 'usage').args, {}, 'no arguments');
  await reply(last('cmd', 'usage'), USAGE());
  assert(!byTest('usage-card')?.checkVisibility(), 'no empty card');
  await post({type: 'status', data: VIEW()});
  assert(!byTest('usage-card')?.checkVisibility(), 'still none');
`);

test('filament use: a pending booking is shown with its slots and grams, and goes when it is booked', `
  await ready(PRINTING());
  await until(() => last('cmd', 'usage'));
  await reply(last('cmd', 'usage'), USAGE({pending: [{file: 'gcodes/benchy.gcode', printer: '192.168.1.50', grams: {'3': 12.5, '4': 3}}]}));
  const card = byTest('usage-card');
  assert(card, 'card shown for a pending booking');
  const t = text(card);
  for (const s of ['1 print is waiting to be booked', 'benchy.gcode', 'ACE 1 · Slot 1: 12.5 g', 'ACE 1 · Slot 2: 3.0 g']) assert(t.includes(s), 'shows ' + s + ': ' + t);
  assert(!q('[data-ack]'), 'nothing to acknowledge yet');
  assert(!q('.oui-banner[data-tone="warn"]', card), 'not a warning');
`);

test('filament use: a failed booking lists its identity and reason; marking it checked is local and asks first', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'));
  await reply(last('cmd', 'usage'), USAGE({unconfirmed: [ENTRY], restore_notice: '2 unreadable unconfirmed entries were skipped'}));
  const card = byTest('usage-card');
  assert(card, 'card shown');
  assert(text(byTest('usage-banner')).includes('1 filament use is not confirmed in Spoolman'), 'one banner says it: ' + text(byTest('usage-banner')));
  assert(!q('[data-ack]'), 'the list is behind Review');
  await click(byTest('usage-review'));
  const t = text(card);
  for (const s of ['1 unconfirmed use', 'benchy.gcode', 'Bench Kobra', 'ACE 1 · Slot 2', '12.5', '#7', 'time unknown', 'Spoolman timeout', 'never sends them again', 'unreadable'])
    assert(t.includes(s), 'shows ' + s + ': ' + t);
  const before = sent().length;
  await click(btn('Mark the use on ACE 1 · Slot 2 of benchy.gcode as checked'));
  assert(dialogText().includes('nothing is sent to Spoolman'), 'says nothing is booked: ' + dialogText());
  await no();
  eq(cmds('usage_ack'), [], 'cancel changes nothing');
  await click(btn('Mark the use on ACE 1 · Slot 2 of benchy.gcode as checked'));
  await yes();
  eq(cmds('usage_ack').map(m => m.args), [{id: 'abc'}], 'only the local acknowledgement');
  assert(!sent().slice(before).some(m => m.type === 'cmd' && !['usage_ack', 'usage', 'stock', 'spools'].includes(m.cmd)), 'no booking command');
  await reply(last('cmd', 'usage_ack'), USAGE({acknowledged: [{...ENTRY, acknowledged_at: 1794300000}], acknowledged_total: 1}));
  assert(!byTest('usage-card')?.checkVisibility(), 'nothing left to show once checked: no empty card');
`);

test('filament use: a failed acknowledgement keeps the entry and says why', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'));
  await reply(last('cmd', 'usage'), USAGE({unconfirmed: [{...ENTRY, spool: null, at: 1794300000}]}));
  assert(text(byTest('usage-card')).includes('none linked'), 'unlinked spool said, not hidden');
  await click(byTest('usage-review'));
  await click(btn('Mark the use on ACE 1 · Slot 2 of benchy.gcode as checked')); await yes();
  await fail(last('cmd', 'usage_ack'), "can't save the print ledger (disk full)");
  assert(alerts().includes('disk full') && text(byTest('usage-card')).includes('benchy.gcode'), 'entry kept, error shown: ' + alerts());
`);

test('filament use: the error path of usage is shown with the reason; a ledger that cannot be saved too', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'));
  await fail(last('cmd', 'usage'), 'ledger unreadable');
  assert(byTest('usage-card') && text(byTest('usage-card')).includes('Couldn’t read the filament-use ledger: ledger unreadable'), 'load error shown: ' + text(byTest('usage-card')));
  const n = cmds('usage').length;
  await until(() => cmds('usage').length > n, 'asked again later', 20000);   // every 10 s while the Dashboard is on screen
  await reply(last('cmd', 'usage'), USAGE({save_error: 'disk full'}));
  assert(text(byTest('usage-card')).includes('The ledger can’t be saved: disk full') && !text(byTest('usage-card')).includes('Couldn’t read'), 'recovers, and shows the save error');
`);

test('filament use: pt-BR', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'));
  await reply(last('cmd', 'usage'), USAGE({unconfirmed: [ENTRY]}));
  assert(text(byTest('usage-review')) === 'Conferir', 'Review in Portuguese');
  await click(byTest('usage-review'));
  const t = text(byTest('usage-card'));
  assert(t.includes('Consumo de filamento no Spoolman') && t.includes('1 consumo não confirmado') && t.includes('Já conferi no Spoolman'), 'Portuguese: ' + t);
`, { lang: 'pt-BR' });

// ------------------------------------------------------------------ camera
test('camera: off by default in a box that keeps its size; frames are acknowledged; leases follow it', `
  await ready(VIEW());
  const off = q('.cam-card .oui-camera[data-state="off"]');
  assert(off && !q('.cam-view'), 'off: the picture box says so, with Turn on');
  const was = off.getBoundingClientRect(), wasY = scrollY;   // page positions: focus may scroll the page to the camera
  assert(Math.abs(was.width / was.height - 16 / 9) < 0.02, 'a 16:9 box: ' + was.width + 'x' + was.height);
  assert(last('lease').camera === false, 'lease: camera off');
  await click(byTest('camera'));
  assert(last('lease').camera === true, 'lease: camera on');
  await post({type: 'frame', image: PNG});
  await until(() => q('.cam-view img'), 'frame shown');
  await until(() => last('frame_ack'), 'frame acknowledged');
  const now = q('.cam-view').getBoundingClientRect();
  assert(Math.abs(now.height - was.height) < 1 && Math.abs(now.top + scrollY - was.top - wasY) < 1, 'turning it on does not move the page: ' + was.height + ' -> ' + now.height);
  assert(text(q('.cam-view .oui-camera-overlay')).includes('Live'), 'marked live');
  await tab('settings');
  await until(() => last('lease').camera === false, 'lease drops when the Dashboard is not on screen (the lease is renewed every 2 s)');
`);

test('camera errors: a plain explanation per reason', `
  await ready(VIEW());
  await click(byTest('camera'));
  await post({type: 'camera_error', error: 'ffmpeg not found', reason: 'no_ffmpeg'});
  assert(text(q('.cam-empty')).includes('ffmpeg is not installed') && text(q('.cam-empty')).includes('Settings > Camera'), 'no_ffmpeg: ' + text(q('.cam-empty')));
  await click(byTest('cam-settings'));
  assert(q('#c-ffmpeg') && !q('#cam-s-h').hidden, 'the button leads to the ffmpeg path field');
  await tab('dash');
  await post({type: 'camera_error', error: 'no rtsp', reason: 'no_stream'});
  assert(text(q('.cam-empty')).includes('isn’t sending a camera stream'), 'no_stream: ' + text(q('.cam-empty')));
  assert(!byTest('cam-settings'), 'no ffmpeg button for another reason');
  await post({type: 'camera_error', error: 'exit 1', reason: 'failed'});
  assert(text(q('.cam-empty')).includes('The camera stopped: exit 1'), 'failed: ' + text(q('.cam-empty')));
  await post({type: 'frame', image: PNG});
  await until(() => q('.cam-view img'), 'recovers when frames come back');
`);

// The printer's real stream (tests/kobra_x_camera.flv, 3.5 s from a Kobra X) remuxed by fmp4.py, as Relay sends it.
const CAMERA = JSON.parse(execFileSync('python3', ['-c', `import base64, json, sys
sys.path.insert(0, "src/kobracontrol")
import fmp4
ev = fmp4.Remuxer().feed(open("tests/kobra_x_camera.flv", "rb").read())
b = lambda x: base64.b64encode(x).decode()
print(json.dumps({"codec": ev[0][1], "init": b(ev[0][2]), "media": [b(e[1]) for e in ev[1:]], "keys": [e[2] for e in ev[1:]]}))`], { cwd: repo, encoding: 'utf8', maxBuffer: 64 << 20 }));

test('camera: the page plays the printer stream itself (no ffmpeg) and says it can in the lease', `
  await ready(VIEW());
  await click(byTest('camera'));
  assert(last('lease').mse === true, 'lease: this page plays H.264');
  const cam = ${JSON.stringify(CAMERA)};
  await until(() => last('video_reset'), 'the attached player asks for the stream init');
  await post({type: 'video', data: cam.media[0], key: true});
  assert(sent().filter(m => m.type === 'video_reset').length >= 1 && q('.cam-empty'), 'data without init: not shown, init asked for');
  await post({type: 'video', codec: cam.codec, init: cam.init});
  assert(q('.cam-empty'), 'still "starting" until frames actually play');
  for (let i = 0; i < cam.media.length; i++) await post({type: 'video', data: cam.media[i], key: cam.keys[i]});
  eq(sent().filter(m => m.type === 'video_ack').length, cam.media.length + 1, 'every fragment acknowledged (Relay backpressure)');
  const v = q('[data-test="cam-video"]');
  await until(() => v.videoWidth === 1280 && v.videoHeight === 720 && v.currentTime > 0, 'the stream plays: ' + v.videoWidth + 'x' + v.videoHeight + ' t=' + v.currentTime + ' err=' + (v.error && v.error.message));
  await until(() => !q('.cam-empty') && !v.classList.contains('cam-hidden'), 'shown once playing');
  assert(!q('.cam-view img'), 'no JPEG');
  await post({type: 'camera_error', error: 'gone', reason: 'failed'});
  assert(q('.cam-empty') && v.classList.contains('cam-hidden'), 'an error replaces the picture');
`);

test('camera: a stream the page cannot decode is handed back to the plugin (video_error)', `
  await ready(VIEW());
  await click(byTest('camera'));
  await until(() => last('video_reset'), 'player attached');
  const cam = ${JSON.stringify(CAMERA)};
  await post({type: 'video', codec: 'avc1.ffffff', init: cam.init});
  await until(() => last('video_error'), 'an unplayable codec reports video_error');
  assert(q('.cam-empty'), 'nothing shown as playing');
  await post({type: 'video', codec: cam.codec, init: cam.init});   // the next stream (or a retry) plays again
  for (let i = 0; i < cam.media.length; i++) await post({type: 'video', data: cam.media[i], key: cam.keys[i]});
  const v = q('[data-test="cam-video"]');
  await until(() => v.videoWidth === 1280 && !q('.cam-empty'), 'recovers on a new init');
`);

test('camera: delta frames before a keyframe are skipped, and a long burst still plays', `
  await ready(VIEW());
  await click(byTest('camera'));
  await until(() => last('video_reset'), 'player attached');
  const cam = ${JSON.stringify(CAMERA)};
  await post({type: 'video', codec: cam.codec, init: cam.init});
  for (let i = 1; i < 10; i++) await post({type: 'video', data: cam.media[i], key: false});   // mid-GOP: unusable
  for (let r = 0; r < 3; r++) for (let i = 0; i < cam.media.length; i++) await post({type: 'video', data: cam.media[i], key: cam.keys[i]});
  const v = q('[data-test="cam-video"]');
  await until(() => v.videoWidth === 1280 && !v.error, 'plays from the first keyframe: err=' + (v.error && v.error.message));
  assert(!last('video_error'), 'no failure reported');
`);

test('the camera starts on only when the saved setting says so', `
  await connect();
  await post(CONFIG({settings: {...SETTINGS, camera_enabled: true}}));
  await post({type: 'status', data: VIEW()});
  assert(q('.cam-view') && last('lease').camera === true, 'camera on from the setting');
`);

// ------------------------------------------------------------------ requirements
test('requirements: no ffmpeg keeps the built-in player; a page without it turns the camera off with one reason', `
  await connect();
  await post(CONFIG({settings: {...SETTINGS, camera_enabled: true}}));
  await post({type: 'status', data: VIEW()});
  await post(REQS());
  assert(q('.cam-view') && last('lease').mse === true, 'the built-in player needs no ffmpeg');
  await post({type: 'status', data: VIEW({camera_url: 'rtsp://192.168.1.50/live'})});   // only ffmpeg plays RTSP
  assert(!q('.cam-view'), 'no camera picture area without ffmpeg');
  assert(text(byTest('cam-why')).includes('ffmpeg isn’t installed'), 'one-line reason: ' + text(byTest('cam-why')));
  assert(!byTest('camera'), 'nothing to turn on: one row with the reason');
  await post({...REQS(), checking: true});
  assert(text(byTest('cam-why')).includes('Looking for ffmpeg'), 'a re-check says so: ' + text(byTest('cam-why')));
  await post(REQS());
  await click(byTest('cam-req'));
  assert(q('[data-need="ffmpeg"]') && !q('#needs-h').hidden, 'the button leads to Settings > Requirements');
  assert(text(q('[data-need="ffmpeg"]')).includes('Not found') && !text(q('[data-need="ffmpeg"]')).includes('optional'), 'needed for RTSP, so not optional: ' + text(q('[data-need="ffmpeg"]')));
  await post(REQS({ffmpeg: {state: 'ok', details: '/opt/homebrew/bin/ffmpeg'}}));
  await tab('dash');
  await until(() => q('.cam-view'), 'found again: the camera is back on');
`);

test('requirements: before the first check the camera can be turned on and says it is starting', `
  await ready(VIEW());
  await post({type: 'requirements', checking: true, items: [{id: 'ffmpeg', state: 'unknown', details: ''}]});
  assert(!byTest('camera').disabled, 'not off without a reason');
  assert(text(q('.cam-card')).includes('Looking for ffmpeg'), 'says it is checking: ' + text(q('.cam-card')));
  await click(byTest('camera'));
  assert(text(q('.cam-empty')).length > 0 && q('.cam-view'), 'starting, with its text: ' + text(q('.cam-empty')));
`);

test('requirements: Settings lists each one with its state, why and how; Check again asks the plugin', `
  await ready(VIEW());
  await post(REQS());
  await tab('settings');
  await click(q('.oui-settings-link[data-section="needs-h"]'));
  const row = id => q('[data-need="' + id + '"]');
  const state = id => q('.oui-status', row(id));
  eq(qa('[data-need]').map(r => r.dataset.need), ['certificate', 'ffmpeg', 'anycubic_slicer', 'printer_agents', 'spoolman', 'spooler'], 'one row each, one section');
  eq(qa('[data-test="requirements"]').length, 1, 'one Requirements section');
  eq(text(state('ffmpeg')), 'Not installed (optional)', 'ffmpeg missing: optional, the page plays the camera itself');
  assert(text(row('ffmpeg')).includes('brew install ffmpeg') && text(row('ffmpeg')).includes('winget install Gyan.FFmpeg')
    && text(row('ffmpeg')).includes('sudo apt install ffmpeg') && text(row('ffmpeg')).includes('ffmpeg path'), 'install help per OS: ' + text(row('ffmpeg')));
  eq(q('a', row('ffmpeg')).getAttribute('href'), 'https://ffmpeg.org/download.html', 'official link');
  assert(text(row('anycubic_slicer')).includes('optional') && text(row('anycubic_slicer')).includes('bundled certificate stops working'), 'slicer optional');
  eq(text(state('printer_agents')), 'Not detected', 'agents: warn, not error');
  assert(text(row('printer_agents')).includes('Use printer agents instead of print hosts') && text(row('printer_agents')).includes('restart OrcaSlicer'), 'agent steps');
  eq(text(state('spoolman')), 'Configured', 'spoolman');
  assert(text(row('spoolman')).includes('http://box:7912'), 'says which Spoolman: ' + text(row('spoolman')));
  assert(!q('a', row('spoolman')), 'no install help once there');
  assert(text(row('certificate')).includes('Found') && text(row('certificate')).includes('built in'), 'certificate: ' + text(row('certificate')));
  assert(text(row('spooler')).includes('Found'), 'Spooler: ' + text(row('spooler')));
  await post(REQS({printer_agents: {state: 'unknown'}, ffmpeg: {state: 'ok', details: '/usr/bin/ffmpeg'}}));
  eq(text(state('printer_agents')), 'Not checked yet', 'unknown is not a warning');
  eq(state('printer_agents').dataset.state, 'idle', 'no warn badge');
  assert(text(row('ffmpeg')).includes('/usr/bin/ffmpeg'), 'says where: ' + text(row('ffmpeg')));
  const navWarn = () => !!q('.oui-settings-link[data-section="needs-h"][data-state="warn"]');
  assert(!navWarn(), 'no warning on the nav either');
  await post(REQS());
  eq(state('printer_agents').dataset.state, 'warn', 'not detected warns');
  assert(navWarn(), 'and the nav says so');
  await click(q('.oui-req-check', row('ffmpeg')));
  assert(last('check_requirements'), 'Check again sent');
  assert(text(state('ffmpeg')).includes('Checking'), 'checking: ' + text(state('ffmpeg')));
  assert(q('.oui-req-check', row('ffmpeg')).disabled, 'no second check while one runs');
  await post({...REQS(), checking: true});
  eq(text(state('ffmpeg')), 'Checking…', 'checking');
  await post(REQS());
  await until(() => last('cmd', 'spools'), 'spools asked on connect');
  await reply(last('cmd', 'spools'), {spools: []});
  await until(() => text(row('spoolman')).includes('0 spools'), 'the count from Spoolman: ' + text(row('spoolman')));
  const spools = cmds('spools').length;
  await click(q('.oui-req-check', row('spoolman')));
  eq(cmds('spools').length, spools + 1, 'Spoolman: Check again also loads the spools');
`);

test('requirements: no Anycubic Slicer Next turns off the default search only; a typed path still searches', `
  await ready(VIEW());
  await post(REQS());
  await tab('settings');
  await click(q('[data-test="cert-advanced"] summary'));
  assert(byTest('find-cert').disabled, 'Find certificate off without an install');
  assert(text(q('#set-cert-why')).includes('isn’t in its usual folder'), 'says why: ' + text(q('#set-cert-why')));
  await type(q('#set-cert-path'), '/opt/anycubic');
  assert(!byTest('find-cert').disabled, 'a typed path can be searched');
  await click(byTest('find-cert'));
  eq(cmds('find_certificate').map(m => m.args), [{path: '/opt/anycubic'}], 'path sent');
`);

test('requirements: without Spoolman, refreshing and linking spools are off', `
  await connect();
  await post(CONFIG({settings: {...SETTINGS, spoolman_url: ''}}));
  await post({type: 'status', data: VIEW()});
  await tab('stock');
  assert(visible(byTest('stock-refresh')) && byTest('stock-refresh').disabled, 'Refresh is off on the Stock tab');
  await tab('settings');
  const refresh = qa('button', q('#sm-s-h').closest('section')).find(b => text(b).includes('Refresh spools'));
  assert(refresh && refresh.disabled, 'Refresh spools off in Settings');
  assert(text(q('#sm-s-h').closest('section')).includes('No Spoolman address'), 'says why');
`);

test('settings: Open Filament Database is off by default; on and saved, its list line and Read again', `
  await connect();
  await post(CONFIG());
  await tab('settings');
  await until(() => q('.oui-settings-link[data-section="sm-s-h"]'), 'settings shown');
  await click(q('.oui-settings-link[data-section="sm-s-h"]'));
  await until(() => q('#ofd-on'), 'the OFD row');
  assert(!q('#ofd-on').checked && !byTest('ofd-state'), 'off by default, nothing more shown');
  await click(q('#ofd-on'));
  await until(() => byTest('ofd-state'), 'turned on');
  assert(text(byTest('ofd-state')).includes('Save to turn it on') && text(byTest('ofd-state')).includes('MIT'), 'saved first; the licence is named: ' + text(byTest('ofd-state')));
  assert(!last('ofd'), 'nothing asked before the save');
  await click(byTest('save-top'));
  eq(last('save_settings').settings.ofd_enabled, true, 'saved on');
  await reply(last('save_settings'), {saved: true});
  await post(CONFIG({settings: {...SETTINGS, ofd_enabled: true}}));
  await until(() => last('ofd'), 'once saved on, the line asks for the kept list');
  await reply(last('ofd'), {on: true, fetched: 1795371399, version: '2026.11.22', count: 2133, stale: false, error: ''});
  await until(() => text(byTest('ofd-state')).includes('2133'), 'the list line: ' + text(byTest('ofd-state')));
  await click(byTest('ofd-refresh'));
  eq(last('ofd').refresh, true, 'Read again asks OFD now');
`);
test('slot cards: an Open Filament Database proposal is marked untuned; picking it installs it by its id', `
  await ready(VIEW());
  await until(() => last('preset_matches'), 'asked');
  await reply(last('preset_matches'), {matches: [{slot: 2, name: 'Generic PLA', source: 'generic', score: 25, reasons: [['material', 'PLA']], confident: true, remembered_key: '',
    candidates: [{name: 'Generic PLA', score: 25, reasons: [['material', 'PLA']]}],
    ofd: [{id: 'f667', inherits: 'Generic PLA @System', name: 'Polymaker Panchroma Matte PLA (OFD)', score: 58, reasons: [['material', 'PLA'], ['vendor', 'Polymaker']]}]}]});
  await until(() => q('[data-match="2"]'), 'slot 3 line');
  await click(q('.oui-match-change', q('[data-match="2"]')));
  await until(() => qa('.oui-match-option', q('[data-match="2"]')).length === 2, 'the candidate and the proposal');
  const ofdRow = qa('.oui-match-option', q('[data-match="2"]'))[1];
  assert(text(ofdRow).includes('OFD, untuned') && !ofdRow.disabled, 'marked and pickable: ' + text(ofdRow));
  await click(ofdRow);
  eq([last('preset_pick').slot, last('preset_pick').ofd, last('preset_pick').inherits], [2, 'f667', 'Generic PLA @System'], 'installed by its OFD id and parent');
  await reply(last('preset_pick'), {matches: [], note: 'Installed; the Device tab reports it once OrcaSlicer lists it'});
  await until(() => document.body.textContent.includes('Device tab reports it'), 'the note is shown');
`);

// ------------------------------------------------------------------ first-run, offline, stale
test('first run: no certificate is one clear task, and Find certificate recovers', `
  await until(() => last('hello'));
  await fail(last('hello'), 'no Anycubic certificate', {no_certificate: true});
  const box = byTest('first-run-cert');
  assert(box, 'certificate panel');
  const t = text(box);
  assert(t.includes('only accepts the certificate carried by Anycubic Slicer Next') && t.includes('has that certificate built in, but here it did not load'), 'explains: ' + t);
  assert(!q('[data-test="pause"]') && !byTest('ace-card'), 'no empty cards');
  assert(text(byTest('link')) === 'No certificate', 'pill');
  await click(byTest('find-cert'));
  eq(cmds('find_certificate').map(m => m.args), [{}], 'looks in the usual places');
  assert(text(q('.notices')).includes('Find certificate: waiting'), 'awaited: ' + text(q('.notices')));
  await reply(last('cmd', 'find_certificate'), {found: true, source: 'AnycubicSlicerNext.app'});
  await until(() => sent().filter(m => m.type === 'hello').length === 2, 'reconnects after finding it');
  assert(toasts().includes('Certificate found'), 'success shown');
  await reply(last('hello'), {address: 'x', printer: 'Bench Kobra', generation: 1});
  await post({type: 'status', data: VIEW()});
  assert(byTest('ace-card'), 'the dashboard is back');
`);

test('first run: a typed path goes with Find certificate; not found explains', `
  await until(() => last('hello'));
  await fail(last('hello'), 'no cert', {no_certificate: true});
  await type(q('#fr-cert-path'), '/Applications/Anycubic');
  await click(byTest('find-cert'));
  eq(cmds('find_certificate').map(m => m.args), [{path: '/Applications/Anycubic'}], 'path sent');
  await reply(last('cmd', 'find_certificate'), {found: false, source: ''});
  assert(text(q('#fr-cert-why')).includes('No Anycubic certificate was found there'), 'explains: ' + text(q('#fr-cert-why')));
  eq(sent().filter(m => m.type === 'hello').length, 1, 'no reconnect without a certificate');
`);

test('first run: a failed search shows the error and keeps the form', `
  await until(() => last('hello'));
  await fail(last('hello'), 'no cert', {no_certificate: true});
  await click(byTest('find-cert'));
  await fail(last('cmd', 'find_certificate'), 'permission denied');
  assert(alerts().includes('Find certificate failed: permission denied'), 'error persists: ' + alerts());
  assert(byTest('find-cert') && !byTest('find-cert').disabled, 'can try again');
`);

test('first run: no usable printer says how to select one', `
  await until(() => last('hello'));
  await fail(last('hello'), 'No Kobra X answered the network search. Enter the printer’s own address under Settings > Printer address', {no_target: true, candidates: []});
  const box = byTest('first-run-target');
  assert(box && text(box).includes('No Kobra X answered the network search') && text(box).includes('looks for the printer by itself'), 'explains: ' + text(box));
  assert(text(byTest('link')) === 'No printer found', 'pill');
  await click(btn('Open Settings', box));
  assert(q('#c-host') && !q('#conn-h').hidden, 'goes to the address field');
  await tab('files');
  assert(text(byTest('files-why')).includes('No Anycubic printer found yet'), 'Files says what is missing');
  eq(cmds('files'), [], 'no file request without a printer');
  await tab('dash');
  await click(byTest('search-again'));
  eq(cmds('search_printer').length, 1, 'Search again searches');
  await fail(last('cmd', 'search_printer'), 'still nothing', {no_target: true});
  await until(() => sent().filter(m => m.type === 'hello').length === 2, 'then says hello again');
`);

test('offline: unreachable printer, retry, and recovery when it answers again', `
  await until(() => last('hello'));
  await fail(last('hello'), 'printer not reachable at 192.168.1.50');
  assert(text(byTest('target-banner')).includes('unreachable') && text(byTest('target-banner')).includes('printer not reachable'), 'banner: ' + text(byTest('target-banner')));
  assert(text(byTest('link')) === 'Offline', 'pill');
  await click(btn('Try again', byTest('target-banner')));
  eq(sent().filter(m => m.type === 'hello').length, 2, 'retry');
  await reply(last('hello'), {address: 'x', printer: 'Bench Kobra', generation: 2});
  await post({type: 'status', data: PRINTING()});
  assert(!text(byTest('target-banner')).includes('unreachable'), 'cleared');
  await post({type: 'offline', error: 'mqtt lost'});
  assert(text(byTest('target-banner')).includes('mqtt lost'), 'offline message: ' + text(byTest('target-banner')));
  assert(q('[data-test="pause"]').disabled, 'controls off');
  eq(q('[data-test="pause"]').getAttribute('aria-describedby'), 'kc-why', 'they point at the one reason');
  assert(text(q('#kc-why')).includes('doesn’t answer'), 'which says the printer does not answer: ' + text(q('#kc-why')));
  await post({type: 'status', data: PRINTING()});
  assert(!q('[data-test="pause"]').disabled, 'a status brings controls back');
`);

test('cannot connect: statuses of a disconnected printer keep one steady error and never say hello again', `
  await until(() => last('hello'));
  eq(last('hello').retry, false, 'opening the tab is not a Retry');
  await fail(last('hello'), 'MQTT 192.168.1.50:9883: no answer on the printer\u2019s MQTT port');
  const banner = () => text(byTest('target-banner'));
  for (let i = 0; i < 5; i++) {   // the plugin publishes a status and an offline message every second
    await post({type: 'status', data: VIEW({connected: false})});
    assert(banner().includes('no answer on the printer'), 'steady error after status ' + i + ': ' + banner());
    await post({type: 'offline', error: 'MQTT 192.168.1.50:9883: no answer on the printer\u2019s MQTT port'});
    assert(banner().includes('no answer on the printer') && !banner().includes('Connecting'), 'no flicker: ' + banner());
  }
  eq(sent().filter(m => m.type === 'hello').length, 1, 'a disconnected status does not retry the connection');
  await click(btn('Try again', byTest('target-banner')));
  eq(sent().filter(m => m.type === 'hello').map(m => m.retry), [false, true], 'Retry asks for a retry');
  await post({type: 'offline', error: 'the old error'});
  assert(!banner().includes('the old error'), 'while retrying the old error stays out: ' + banner());
  await fail(last('hello'), 'MQTT 192.168.1.50:9883: the printer closed the connection during the TLS/MQTT login');
  assert(banner().includes('closed the connection during the TLS/MQTT login'), 'the new reason: ' + banner());
  await post({type: 'status', data: VIEW()});
  await until(() => sent().filter(m => m.type === 'hello').length === 3, 'a connected status says hello');
  eq(last('hello').retry, false, 'not a Retry');
`);

test('offline: badge, banner, Status card, camera and every control agree, and the next try is shown', `
  await connect();
  await post(CONFIG());
  await post({type: 'status', data: VIEW({connected: false, state: 'offline'})});
  await post({type: 'offline', error: 'Something answers at 192.0.2.41, but it is not a Kobra X in LAN mode', retry_at: Date.now() / 1000 + 32});
  eq(text(byTest('link')), 'Offline', 'badge');
  const banner = text(byTest('target-banner'));
  assert(banner.includes('unreachable') && banner.includes('not a Kobra X in LAN mode') && !banner.includes('Connecting'), 'banner: ' + banner);
  // Derived from retry_at and the time the message was posted, not a fixed window: the page's 1 s clock may lag.
  const n = +(/tries again by itself in ([0-9]+) s/.exec(text(byTest('retry-in'))) || [])[1];
  assert(n >= 1 && n <= 32, 'next try within retry_at: ' + text(byTest('retry-in')));
  eq(text(byTest('state')), 'Offline', 'Status card');
  assert(text(byTest('cam-why')).includes('doesn’t answer'), 'camera gives the same reason: ' + text(byTest('cam-why')));
  assert(!text(document.body).includes('Select a printer first'), 'no "no printer" text while one is selected');
  // every printer control in the printer's panels (job, temperatures, move, camera, filament) is off
  const roots = [byTest('dash-grid'), byTest('printer-head')];
  eq(roots.filter(Boolean).length, 2, 'the dashboard and the page header');
  assert(byTest('job-card') && byTest('ace-card') && byTest('temps') && byTest('move'), 'the printer widgets are on it');
  // (the (i) buttons explain; they are not printer controls)
  // (the console and Maximise are the page's own, not the printer's)
  const live = roots.flatMap(root => qa('button:not(.oui-hint-btn), input, [role="checkbox"]', root)).filter(el => !el.closest('[data-widget="console"]') && el.dataset.test !== 'widget-max' && !el.disabled && !el.closest('[data-p-disabled="true"]') && el.getAttribute('aria-disabled') !== 'true'
    && !el.closest('.p-disabled') && !el.closest('details:not([open])'));
  eq(live.map(el => (el.textContent || el.getAttribute('aria-label') || el.outerHTML).trim().slice(0, 60)), [], 'every printer control is off');
  for (const b of roots.flatMap(root => qa('button.p-button', root)).filter(el => !el.closest('[data-widget="console"]') && el.dataset.test !== 'widget-max')) {
    const st = getComputedStyle(b);
    assert(parseFloat(st.opacity) <= 0.7 || st.cursor === 'not-allowed', 'looks disabled: ' + text(b) + ' opacity ' + st.opacity);
  }
`);

test('a found printer is never used or allowed without a click (GUI test 2026-11-20)', `
  await until(() => last('hello'));
  await fail(last('hello'), 'Found Workshop KX (Anycubic Kobra X) at 10.0.0.41 on the network. Use it? Kobra Control connects only to a printer you choose.',
    {no_target: true, candidates: [{ip: '10.0.0.41', name: 'Workshop KX', model: 'Anycubic Kobra X', needs_allow: false, different: false}], pending: []});
  const box = byTest('first-run-target');
  await until(() => text(box).includes('Anycubic printer found'), 'one printer: the title says one');
  assert(!text(box).includes('Several'), 'not "several" for one: ' + text(box));
  await settle();
  eq(sent().filter(m => m.type === 'allow_hosts').length, 0, 'no OrcaSlicer dialog by itself');
  eq(cmds('choose_printer').length, 0, 'not used by itself');
  await click(q('[data-pick-ip="10.0.0.41"]'));
  eq(cmds('choose_printer').map(m => m.args), [{host: '10.0.0.41'}], 'used on the click');
`);

test('a found printer OrcaSlicer must allow first: the dialog comes only from Allow and use', `
  await until(() => last('hello'));
  await fail(last('hello'), 'Found a printer at 10.0.0.41. Choose “Allow and use” to let Kobra Control reach it.',
    {no_target: true, candidates: [{ip: '10.0.0.41', name: '', model: '', needs_allow: true, different: false}], pending: ['10.0.0.41']});
  await settle();
  eq(sent().filter(m => m.type === 'allow_hosts').length, 0, 'no dialog by itself, even with an old plugin naming it pending');
  await click(q('[data-pick-ip="10.0.0.41"]'));
  await until(() => last('allow_hosts'), 'asks the plugin to show the dialog');
  eq(last('allow_hosts').hosts, ['10.0.0.41'], 'that address');
  eq(last('allow_hosts').user, true, 'the user clicked');
  await reply(last('allow_hosts'), {allowed: ['10.0.0.41'], refused: []});
  await until(() => sent().filter(m => m.type === 'hello').length === 2, 'hello again after the Yes');
`);

test('a dialog that does not allow the printer leaves a clear next step, not a wait', `
  await until(() => last('hello'));
  await fail(last('hello'), 'Found a printer at 10.0.0.41.', {no_target: true, candidates: [{ip: '10.0.0.41', name: '', model: '', needs_allow: true}], pending: []});
  await click(q('[data-pick-ip="10.0.0.41"]'));
  await until(() => last('allow_hosts'));
  await reply(last('allow_hosts'), {allowed: [], refused: ['10.0.0.41']});
  await until(() => text(byTest('first-run-target')).includes('may not reach 10.0.0.41 yet'), 'what to do');
  assert(text(byTest('first-run-target')).includes('Search again'), 'with Search again');
`);

test('a different Kobra X is offered as a choice, and one OrcaSlicer must allow is allowed on the click', `
  await until(() => last('hello'));
  await fail(last('hello'), 'A different Kobra X answered at 10.0.0.3. Use it? Kobra Control does not switch to another printer by itself.',
    {no_target: true, candidates: [{ip: '10.0.0.3', name: 'Right KX', model: 'Anycubic Kobra X', needs_allow: false, different: true},
      {ip: '10.0.0.4', name: '', model: '', needs_allow: true, different: true}], pending: []});
  const box = byTest('first-run-target');
  assert(text(box).includes('A different Kobra X answered') && text(box).includes('does not switch to another printer by itself'), 'says so: ' + text(box));
  eq(sent().filter(m => m.type === 'allow_hosts').length, 0, 'no OrcaSlicer dialog by itself for a choice');
  await click(q('[data-pick-ip="10.0.0.4"]'));
  eq(last('allow_hosts').hosts, ['10.0.0.4'], 'allow on the click');
  eq(last('allow_hosts').user, true, 'the user chose it');
  await click(q('[data-pick-ip="10.0.0.3"]'));
  eq(cmds('choose_printer').map(m => m.args), [{host: '10.0.0.3'}], 'an explicit choice');
`);

test('a known printer lost and another one answering: the offer stays across hellos and statuses, and choosing it connects', `
  await connect(3);
  await post(CONFIG());
  await post({type: 'status', data: VIEW()});
  const offer = {no_target: true, pending: [], candidates: [{ip: '10.0.0.3', name: 'Right KX', model: 'Anycubic Kobra X', needs_allow: false, different: true}]};
  await post({type: 'selection_changed'});
  await until(() => sent().filter(m => m.type === 'hello').length === 2, 'hello again');
  await fail(last('hello'), 'printer not reachable at 10.0.0.2. A different Kobra X answered at 10.0.0.3. Use it? Kobra Control does not switch to another printer by itself.', offer);
  const card = () => text(byTest('first-run-target'));
  assert(card().includes('A different Kobra X answered') && card().includes('Right KX'), 'offer: ' + card());
  for (let i = 0; i < 3; i++) {
    await post({type: 'status', data: VIEW({connected: false, state: 'offline'})});
    await post({type: 'offline', error: 'printer not reachable at 10.0.0.2', retry_at: Date.now() / 1000 + 30});
    assert(card().includes('Use it?') || card().includes('Right KX'), 'still offered after status ' + i + ': ' + card());
  }
  await post({type: 'selection_changed'});
  await until(() => sent().filter(m => m.type === 'hello').length === 3, 'another hello');
  assert(card().includes('Right KX'), 'still offered while the plugin is asked again: ' + card());
  await fail(last('hello'), 'printer not reachable at 10.0.0.2. A different Kobra X answered at 10.0.0.3. Use it?', offer);
  await click(q('[data-pick-ip="10.0.0.3"]'));
  eq(cmds('choose_printer').map(m => m.args), [{host: '10.0.0.3'}], 'chosen');
  await reply(last('cmd', 'choose_printer'), {address: '10.0.0.3'});
  await until(() => sent().filter(m => m.type === 'hello').length === 4, 'connects to it');
  await reply(last('hello'), {address: '10.0.0.3', printer: 'Bench Kobra', generation: 4, source: 'chosen'});
  eq(text(byTest('link')), 'Connected', 'connected');
  assert(!byTest('first-run-target'), 'the offer is gone');
`);

test('first run: several printers found, pick one', `
  await until(() => last('hello'));
  await fail(last('hello'), '2 Kobra X printers answer on this network: choose one.', {no_target: true,
    candidates: [{ip: '10.0.0.2', name: 'Left KX', model: 'Anycubic Kobra X'}, {ip: '10.0.0.3', name: 'Right KX', model: 'Anycubic Kobra X'}]});
  const box = byTest('first-run-target');
  assert(text(box).includes('Several Anycubic printers found') && text(box).includes('Right KX') && text(box).includes('10.0.0.3'), 'picker: ' + text(box));
  await click(q('[data-pick-ip="10.0.0.3"]'));
  eq(cmds('choose_printer').map(m => m.args), [{host: '10.0.0.3'}], 'choice sent');
  await reply(last('cmd', 'choose_printer'), {address: '10.0.0.3'});
  await until(() => sent().filter(m => m.type === 'hello').length === 2, 'connects to it');
`);

test('settings: the address in use, how it was found, Search again, and the other printer agent', `
  await until(() => last('hello'));
  await post(CONFIG({located: {address: '', source: '', preset_host: '192.0.2.41', preset_agent: 'moonraker', spoolman_url: '', spoolman_source: ''}}));
  await reply(last('hello'), {address: '192.0.2.41', printer: 'Bench Kobra', generation: 1, source: 'discovered',
    note: 'The printer preset points to 192.0.2.41, which is not a Kobra X in LAN mode; found the Kobra X at 192.0.2.41 and using that.'});
  await post({type: 'status', data: VIEW()});
  assert(toasts().includes('points to 192.0.2.41'), 'one quiet line: ' + toasts());
  assert(toasts().includes('“moonraker” printer agent'), 'agent note once: ' + toasts());
  await tab('settings');
  eq(text(byTest('in-use')), 'In use: 192.0.2.41 (found on the network).', 'in use');
  assert(text(byTest('other-agent')).includes('Printer Agent > kobracontrol'), 'how to switch: ' + text(byTest('other-agent')));
  await click(byTest('search-again-settings'));
  eq(cmds('search_printer').length, 1, 'search again');
  await type(q('#c-host'), '192.0.2.50');
  assert(byTest('search-again-settings').disabled, 'no search while an address is typed here');
`);

test('stock table: thumbnails stay small and nothing overlaps, with many spools, at wide and narrow widths', `
  const many = Array.from({length: 55}, (_, i) => ({...ROWS[i % 2], id: 100 + i, name: 'Spool ' + i}));
  await ready(VIEW());
  await reply(last('cmd', 'stock'), STOCK({stock: {...STOCK().stock, rows: many}}));
  await until(() => byTest('stock-card'), 'stock list');
  await tab('stock');
  // the owner's web view drew each spool as a tall narrow strip; without aspect-ratio support it must still be a square
  const style = document.createElement('style'); style.textContent = '.oui-spool { aspect-ratio: auto !important; }'; document.head.appendChild(style);
  for (const width of ['', '380px']) {
    q('#app').style.width = width; q('#app').style.maxWidth = width || '';
    await settle();
    const wrap = q('[data-test="stock-card"] .sc-wrap');
    for (const fig of qa('.oui-spool', wrap).slice(0, 6)) {
      const r = fig.getBoundingClientRect();
      assert(Math.abs(r.width - 36) < 1 && Math.abs(r.height - 36) < 1, 'thumbnail 36x36 at ' + (width || 'wide') + ', got ' + r.width + 'x' + r.height);
    }
    const rows = qa('tbody tr', wrap).slice(0, 6).map(tr => tr.getBoundingClientRect().height);
    assert(Math.max(...rows) < 90, 'compact rows at ' + (width || 'wide') + ': ' + rows.join(','));
    const panel = wrap.closest('.oui-panel').getBoundingClientRect();
    assert(panel.height <= innerHeight - 100, 'the list is no taller than the window under the bars: ' + panel.height + ' of ' + innerHeight);
    assert(wrap.scrollHeight > wrap.clientHeight, 'many spools scroll inside');
    assert(document.documentElement.scrollWidth <= innerWidth, 'the page does not scroll sideways at ' + (width || 'wide'));
  }
  style.remove();
`);

test('stale status shows its age', `
  await ready(PRINTING());
  const real = Date.now;
  Date.now = () => real() + 30000;
  await until(() => text(byTest('target-banner')).includes('out of date'), 'stale banner', 15000);
  assert(text(byTest('target-banner')).includes('Last printer status'), 'says the age: ' + text(byTest('target-banner')));
  // the reasons the disabled controls point at stay on screen beside it: an old status does not hide them
  assert(q('[data-move="x+"]').disabled, 'moves are still off');
  assert(q('#kc-busy') && text(q('#kc-busy')).includes('idle or paused'), 'the busy banner is still there: ' + text(byTest('target-banner')));
  eq(q('[data-move="x+"]').getAttribute('aria-describedby'), 'kc-busy', 'and the control points at it');
  Date.now = real;
`);

test('stale selection: selection_changed cancels a question, clears data and asks again', `
  await ready(PRINTING(), 4);
  await click(q('[data-test="stop"]'));
  assert(dialogOpen(), 'asks');
  await post({type: 'selection_changed'});
  await until(() => !dialogOpen(), 'dialog closed on printer change');
  eq(cmds('stop'), [], 'nothing stopped');
  eq(sent().filter(m => m.type === 'hello').length, 2, 'hello again');
  eq(qa('[data-slot]').length, 0, 'old slots cleared');
  await reply(last('hello'), {address: 'y', printer: 'Other Kobra', generation: 5});
  await post({type: 'status', data: PRINTING()});
  await click(q('[data-test="pause"]'));
  eq(cmds('pause').map(m => m.gen), [5], 'the new generation is used');
`);

// ------------------------------------------------------------------ files
test('files: list, select a file for its details, the print options, print and cancel', `
  await ready(VIEW({storage: {total: 8000, used: 2000}}));
  await tab('files');
  await until(() => last('cmd', 'files'), 'files asked');
  await reply(last('cmd', 'files'), {files: [{name: 'cube.gcode', size: 900000, timestamp: 1699000000}, {name: 'benchy.gcode', size: 4200000, timestamp: 1700000000}]});
  eq(fileNames(), ['benchy.gcode', 'cube.gcode'], 'rows, newest first');
  eq(filesCount(), '2 files', 'count over the table');
  assert(text(byTest('disk')).includes('2 GB') && text(byTest('disk')).includes('8 GB'), 'storage: ' + text(byTest('disk')));
  assert(text(fileRow('benchy.gcode')).includes('G-code') && text(fileRow('benchy.gcode')).includes('4.2 MB'), 'kind and size: ' + text(fileRow('benchy.gcode')));
  assert(!byTest('print-panel') && cmds('file_details').length === 0, 'no details asked until a file is selected');
  await click(fileRow('benchy.gcode'));
  eq(fileRow('benchy.gcode').getAttribute('aria-selected'), 'true', 'selected');
  eq(cmds('file_details').map(m => m.args), [{name: 'benchy.gcode'}], 'details asked');
  await reply(last('cmd', 'file_details'), {name: 'benchy.gcode', thumbnail: PNG, objects: []});
  await until(() => q('.oui-files-preview img'), 'thumbnail');
  assert(q('img', fileRow('benchy.gcode')), 'and in its row');
  assert(q('#opt-level input, input#opt-level').checked !== false, 'auto-leveling starts on from the setting');
  await click(q('input#opt-vib'));
  assert(q('input#opt-flow') && !q('input#opt-flow').checked && q('input#opt-tl') && !q('input#opt-tl').checked, 'flow calibration and time-lapse start off');
  await click(q('input#opt-tl'));
  await click(byTest('print-start'));
  assert(dialogOpen() && dialogText().includes('benchy.gcode') && dialogText().includes('Bench Kobra'), 'asks: ' + dialogText());
  assert(dialogText().includes('Flow calibration: off') && dialogText().includes('Time-lapse: on'), 'the question names each option: ' + dialogText());
  await no();
  eq(cmds('file_print'), [], 'cancel prints nothing');
  await click(byTest('print-start')); await yes();
  eq(cmds('file_print').map(m => m.args), [{name: 'benchy.gcode', auto_leveling: true, vibration_compensation: false, flow_calibration: false, timelapse: true}],
    'file_print with each option');
  await reply(last('cmd', 'file_print'), true);
  await until(() => !byTest('print-panel'), 'panel closes when printing');
  eq(qa('[data-view="files"] [aria-selected="true"][data-file]').length, 0, 'nothing selected any more');
`);

test('files: flow calibration and time-lapse follow the printer features and the saved defaults', `
  await connect(); await post(CONFIG({settings: {...SETTINGS, flow_calibration: true, timelapse: true}}));
  await post({type: 'status', data: VIEW({features: {flow_calibration_support: true, camera_timelapse_support: false}})});
  await tab('files');
  await reply(last('cmd', 'files'), {files: [{name: 'benchy.gcode', size: 1, timestamp: 1700000000}]});
  await click(fileRow('benchy.gcode'));
  await reply(last('cmd', 'file_details'), {name: 'benchy.gcode', thumbnail: PNG, objects: []});
  await until(() => q('.oui-files-preview img'), 'panel');
  assert(q('input#opt-flow').checked, 'flow calibration on from the setting');
  assert(!q('input#opt-tl'), 'no time-lapse switch on a printer without it');
  await click(byTest('print-start')); await yes();
  eq(cmds('file_print').map(m => [m.args.flow_calibration, m.args.timelapse]), [[true, false]], 'time-lapse never sent where unsupported');
`);

// ------------------------------------------------------------------ the printer's details and Print Assist
test('printer panel: details are asked once the printer is idle, never during a print', `
  await ready(PRINTING());
  await sleep(300);
  eq(cmds('device'), [], 'nothing asked while printing');
  assert(text(byTest('assist-none')).includes('once it is idle'), 'says when: ' + text(byTest('assist-none')));
  await post({type: 'status', data: VIEW()});
  await until(() => last('cmd', 'device'), 'asked when idle');
  await post({type: 'status', data: PRINTING()}); await post({type: 'status', data: VIEW()}); await settle();
  eq(cmds('device').length, 1, 'once per connection');
`);

test('printer panel: a failed ask is made again the next time the printer is idle', `
  await ready(VIEW());
  await until(() => last('cmd', 'device'), 'asked');
  await fail(last('cmd', 'device'), 'reading the printer’s details is not possible while the printer is printing');
  await settle();
  eq(cmds('device').length, 1, 'no retry loop while nothing changed');
  await post({type: 'status', data: PRINTING()}); await post({type: 'status', data: VIEW()});
  await until(() => cmds('device').length === 2, 'asked again once idle');
  await reply(last('cmd', 'device'), {sent: true, assist: true});
  await post({type: 'status', data: PRINTING()}); await post({type: 'status', data: VIEW()}); await settle();
  eq(cmds('device').length, 2, 'a successful ask is not repeated');
`);

test('printer panel: details are asked on connect; only reported counters show', `
  await ready(VIEW());
  await until(() => last('cmd', 'device'), 'device asked after hello');
  eq(cmds('device').length, 1, 'once per connection');
  const panel = () => text(byTest('device'));
  assert(text(byTest('printer-head')).includes('Bench Kobra') && panel().includes('1.0'), 'the name in the page header, the firmware here: ' + panel());
  assert(!panel().includes('Network address') && !panel().includes('Prints') && !panel().includes('Total print time'), 'nothing unreported: ' + panel());
  await post({type: 'status', data: VIEW({mac: 'AA:BB:CC:00:11:22', stats: {print_count: 12, filament_g: 1520}})});
  assert(panel().includes('AA:BB:CC:00:11:22') && panel().includes('Prints') && panel().includes('12') && panel().includes('1.52 kg'), 'reported ones: ' + panel());
  assert(!panel().includes('Total print time'), 'a counter the firmware did not send stays hidden');
  await post({type: 'status', data: VIEW({stats: {print_minutes: 605}})});
  assert(panel().includes('10 h 5 min'), 'print time: ' + panel());
  assert(text(byTest('assist-none')).includes('Asking'), 'while the printer is asked: ' + text(byTest('assist-none')));
  await reply(last('cmd', 'device'), {sent: true, assist: false});
  await until(() => text(byTest('assist-none')).includes('did not report'), 'a firmware that does not answer says so');
  eq(qa('[data-assist]').map(e => e.getAttribute('data-assist')), ['autoFeed'], 'auto-feed is the ACE’s own and always there');
`);

test('printer panel: Print Assist switches ask first, then send; only reported ones show', `
  await ready(VIEW({assist: ASSIST}));
  eq(qa('[data-assist]').map(e => e.getAttribute('data-assist')), ['breakAlert', 'jamAlert', 'autoFeed', 'remain', 'belt'], 'reported switches, Anycubic’s order');
  assert(!q('#assist-breakAlert').checked && q('#assist-jamAlert').checked, 'values from the printer');
  await click(q('#assist-breakAlert'));
  assert(dialogOpen() && dialogText().includes('Turn on Filament break alert') && dialogText().includes('Bench Kobra'), 'asks: ' + dialogText());
  await no();
  eq(cmds('assist'), [], 'cancel sends nothing');
  assert(!q('#assist-breakAlert').checked, 'the switch stays as the printer says');
  await click(q('#assist-breakAlert')); await yes();
  eq(cmds('assist').map(m => m.args), [{option: 'breakAlert', on: true}], 'assist sent');
  await reply(last('cmd', 'assist'), {confirmed: true});
  await until(() => toasts().includes('Filament break alert is on'), 'result shown');
  await click(q('#assist-autoFeed')); await yes();
  eq(cmds('assist').map(m => m.args)[1], {option: 'autoFeed', on: true}, 'auto-feed for every ACE');
`);

test('printer panel: changes are refused while printing, with the reason', `
  await ready(PRINTING({assist: ASSIST}));
  assert(q('#assist-belt').disabled && byTest('rename').disabled, 'switches and rename off');
  assert(text(byTest('busy-banner')).includes('while it is idle'), 'the page banner says why: ' + text(byTest('busy-banner')));
  eq(q('#assist-belt').getAttribute('aria-describedby'), 'kc-busy', 'the reason is announced');
  eq(byTest('rename').getAttribute('aria-describedby'), 'kc-busy', 'for Rename too');
`);

test('printer panel: rename asks for the name and checks it', `
  await ready(VIEW());
  await click(byTest('rename'));
  assert(dialogOpen() && dialogText().includes('Rename the printer'), 'asks: ' + dialogText());
  await no();
  eq(cmds('rename'), [], 'cancel renames nothing');
  await click(byTest('rename'));
  const input = q('.p-dialog input');
  eq(input.value, 'Bench Kobra', 'starts from the current name');
  await type(input, 'Shop <X>'); await yes();
  eq(cmds('rename'), [], 'an invalid name is not sent');
  await until(() => toasts().includes('without quotes'), 'says why');
  await click(byTest('rename'));
  await type(q('.p-dialog input'), 'é'.repeat(17)); await yes();
  eq(cmds('rename'), [], '34 bytes is too long, as the plugin counts it');
  await until(() => toasts().includes('without quotes'), 'says why');
  await click(byTest('rename'));
  await type(q('.p-dialog input'), '  Shop   Kobra '); await yes();
  eq(cmds('rename').map(m => m.args), [{name: 'Shop Kobra'}], 'rename sent, spaces tidied');
`);

test('pt-BR: the printer panel is translated', `
  await ready(VIEW({assist: ASSIST, mac: 'AA:BB', stats: {print_count: 3}}));
  const panel = text(byTest('device'));
  for (const w of ['Impressora', 'Endereço de rede', 'Impressões', 'Assistente de impressão', 'Alerta de filamento rompido', 'Detecção de correia'])
    assert(panel.includes(w), w + ' in ' + panel);
  eq(text(byTest('rename')), 'Renomear', 'Rename, in the page header');
  // what each switch does is behind the group's (i), not under every row
  assert(text(q('[data-test="device"] .oui-hint-bubble')).includes('Pausa a impressão quando o filamento rompe'), 'help in the hint: ' + text(q('[data-test="device"] .oui-hint-bubble')));
`, { lang: 'pt-BR' });

test('files: print is refused while the printer cannot start, with the reason', `
  await ready(PRINTING());
  await tab('files');
  await reply(last('cmd', 'files'), {files: [{name: 'a.gcode', size: 1, timestamp: 1700000000}]});
  await click(fileRow('a.gcode'));
  assert(byTest('print-start').disabled, 'start disabled');
  assert(text(byTest('busy-banner')).includes('can’t start a print right now'), 'the page banner says why: ' + text(byTest('busy-banner')));
  eq(byTest('print-start').getAttribute('aria-describedby'), 'kc-busy', 'and the button points at it');
  assert(!text(byTest('busy-banner')).includes('Moves'), 'only what this tab is about');
`);

test('files: select several, delete asks once with the count and the names, and sends one batch', `
  await ready(VIEW());
  await tab('files');
  const F = n => ({name: n + '.gcode', size: 1000, timestamp: 1700000000 + n.charCodeAt(0)});
  await reply(last('cmd', 'files'), {files: ['a', 'b', 'c'].map(F)});
  eq(fileNames(), ['c.gcode', 'b.gcode', 'a.gcode'], 'listed');
  assert(!btn('Delete', filesBar()), 'no Delete with nothing selected');
  await check('a.gcode'); await check('c.gcode');
  eq(filesCount(), '2 selected', 'the bar counts the selection');
  eq(qa('[data-view="files"] [data-file][aria-selected="true"]').length, 2, 'both rows marked');
  assert(text(q('[data-view="files"] .oui-files-detail')).includes('2 selected') && !byTest('print-panel'), 'the detail lists them; nothing to print');
  eq(cmds('file_details').map(m => m.args.name), ['a.gcode'], 'details were asked for the first while it was alone, not for the pair');
  assert(btn('Delete', filesBar()).classList.contains('p-button-outlined'), 'Delete is outlined red in the page');
  await click(btn('Delete', filesBar()));
  assert(dialogOpen() && dialogText().includes('Delete 2 files?') && dialogText().includes('a.gcode') && dialogText().includes('c.gcode'), 'asks, with the count and the names: ' + dialogText());
  assert(q('[data-dlg="confirm"]').classList.contains('p-button-danger') && !q('[data-dlg="confirm"]').classList.contains('p-button-outlined'), 'the confirm button is the solid red');
  await answer('cancel');
  eq(cmds('file_delete'), [], 'going back deletes nothing');
  eq(filesCount(), '2 selected', 'and keeps the selection');
  await click(btn('Delete', filesBar())); await answer('confirm');
  eq(cmds('file_delete').map(m => m.args), [{names: ['a.gcode', 'c.gcode']}], 'one file_delete with both names');
  await reply(last('cmd', 'file_delete'), true);
  await until(() => cmds('files').length === 2, 'list refreshed');
  await reply(last('cmd', 'files'), {files: [F('b')]});
  assert(toasts().includes('2 files deleted.'), 'says so: ' + toasts());
  eq(fileNames(), ['b.gcode'], 'the rest stays');
  eq(filesCount(), '1 file', 'selection cleared');
  await until(focusInList, 'the keyboard stays in the list, not lost');
  // the keyboard: Delete on the focused row asks at the first press, with nothing selected before
  fileRow('b.gcode').focus();
  await press('Delete');
  assert(dialogOpen() && dialogText().includes('Delete 1 file?') && dialogText().includes('b.gcode'), 'Delete key asks: ' + dialogText());
  await answer('confirm');
  eq(cmds('file_delete').map(m => m.args)[1], {names: ['b.gcode']}, 'deleted from the keyboard');
  await reply(last('cmd', 'file_delete'), true);
  await until(() => cmds('files').length === 3, 'list refreshed');
  await reply(last('cmd', 'files'), {files: []});
  assert(text(q('[data-view="files"] .oui-files-scroll')).includes('No files on the printer'), 'empty state');
  assert(toasts().includes('File deleted.'), 'one file: ' + toasts());
`);

test('files: the Kobra X has no folders, so no folder tree and no Move; a refused delete reads the list again', `
  await ready(VIEW());
  await tab('files');
  await reply(last('cmd', 'files'), {files: [{name: 'a.gcode', size: 1, timestamp: 1700000000}, {name: 'b.gcode', size: 1, timestamp: 1700000001}]});
  // no folder tree, no breadcrumb, no "Move to": the storage only lists and deletes, so the browser offers nothing else
  const files = q('[data-view="files"]');
  eq(qa('.oui-files-rail, .oui-files-path, .oui-files-move, [data-folder], [role=treeitem]', files).length, 0, 'none of it is in the page');
  assert(q('.oui-files-grid', files).hasAttribute('data-flat'), 'the browser is in its no-folder layout');
  eq(qa('style').filter(st => /\.kc-files\s+\.oui-files-/.test(st.textContent)).length, 0, 'and the page has no style rule reaching into the browser');
  eq(qa('[data-list]', files).map(b => [b.dataset.list, text(b), b.getAttribute('aria-pressed')]), [['local', 'Print files', 'true'], ['videos', 'Time-lapses', 'false']], 'the two lists');
  const list = q('.oui-files-list', files).getBoundingClientRect(), box = q('.oui-files-grid', files).getBoundingClientRect();
  assert(Math.abs(list.left - box.left) < 1.5, 'the list starts at the browser\u2019s edge: no empty column where the tree was (' + list.left + ' / ' + box.left + ')');
  await click(q('.oui-files-table thead input'));
  eq(filesCount(), '2 selected', 'select all');
  // A drag with the real mouse (trusted pointer events, as in OrcaSlicer's web views) does nothing: no file follows the
  // pointer, no place takes a drop, the release leaves the selection as it was.
  await mdown(fileRow('a.gcode')); await mmove(q('[data-list="videos"]'));
  eq(qa('.oui-files-ghost, [data-drop], [data-refused], [data-dragged]').length, 0, 'nothing is dragged');
  assert(!document.documentElement.dataset.ouiDrag, 'the cursor is not a drag cursor');
  await mup(q('[data-list="videos"]'));
  await settle();
  eq(qa('[data-folder], [data-files-mkdir], [data-files-newname]', files).length, 0, 'no folder can be made either');
  eq(fileNames().sort(), ['a.gcode', 'b.gcode'], 'nothing moved');
  eq(sent().filter(m => m.type === 'cmd' && /move|rename|mkdir/.test(m.cmd)), [], 'and no such command exists');
  await click(btn('Delete', filesBar())); await answer('confirm');
  await fail(last('cmd', 'file_delete'), 'the printer refused the delete (code 10112): busy');
  assert(alerts().includes('Delete failed') && alerts().includes('10112'), 'the reason stays on screen: ' + alerts());
  await until(() => cmds('files').length === 2, 'the list is read again: it shows what is on the printer');
  await reply(last('cmd', 'files'), {files: [{name: 'a.gcode', size: 1, timestamp: 1700000000}, {name: 'b.gcode', size: 1, timestamp: 1700000001}]});
  eq(fileNames().length, 2, 'both still there');
  assert(!toasts().includes('files deleted'), 'not reported as deleted');
`);

for (const [width, height] of [[420, 900], [720, 560]]) {
  test(`files (${width} x ${height}): the details go under the list and never squeeze it away`, `
  await ready(VIEW());
  await tab('files');
  await reply(last('cmd', 'files'), {files: ['a', 'b', 'c', 'd', 'e', 'f'].map((n, i) => ({name: n + '.gcode', size: 1000, timestamp: 1700000000 + i}))});
  await click(fileRow('f.gcode'));
  await reply(last('cmd', 'file_details'), DETAILS({name: 'f.gcode'}));
  await until(() => byTest('mat-warn'), 'details shown');
  const files = q('[data-view="files"]'), box = q('.oui-files-grid', files).getBoundingClientRect();
  const scroll = q('.oui-files-scroll', files).getBoundingClientRect(), detail = q('.oui-files-detail', files), d = detail.getBoundingClientRect();
  assert(d.top >= scroll.bottom - 0.5, 'the details are under the list: ' + d.top + ' / ' + scroll.bottom);
  const row = fileRow('f.gcode').getBoundingClientRect();
  assert(scroll.height >= 44 && row.top >= scroll.top - 0.5 && row.bottom <= scroll.bottom + 0.5, 'the selected file is still on screen in the list: list ' + scroll.height + ' px, row ' + row.top + '-' + row.bottom + ' in ' + scroll.top + '-' + scroll.bottom);
  assert(d.bottom <= box.bottom + 0.5 && d.height <= box.height * 0.6, 'the details keep to their share of the browser: ' + d.height + ' of ' + box.height);
  assert(detail.scrollHeight > detail.clientHeight, 'and scroll inside it');
  const q0 = byTest('files-q').getBoundingClientRect();
  assert(q0.height > 20 && q0.bottom <= scroll.top + 0.5, 'the search field is whole, above the table: ' + q0.bottom + ' / ' + scroll.top);
  byTest('print-start').scrollIntoView({block: 'nearest'}); await settle();
  const start = byTest('print-start').getBoundingClientRect(), now = detail.getBoundingClientRect();
  assert(start.top >= now.top - 0.5 && start.bottom <= now.bottom + 0.5, 'Start printing can be reached by scrolling the details');
`, { size: [width, height] });
}

test('files: delete and select are off while the printer is away, pointing at the page banner', `
  await ready(VIEW());
  await tab('files');
  await reply(last('cmd', 'files'), {files: [{name: 'a.gcode', size: 1, timestamp: 1700000000}]});
  await check('a.gcode');
  await post({type: 'offline', error: 'mqtt lost'});
  const del = btn('Delete', filesBar());
  assert(del.disabled, 'Delete off');
  eq(del.getAttribute('aria-describedby'), 'kc-why', 'for the page’s one reason');
  assert(text(q('#kc-why')).includes('doesn’t answer'), 'which is on this tab too: ' + text(q('#kc-why')));
  fileRow('a.gcode').focus();
  await press('Delete');
  assert(!dialogOpen(), 'the Delete key asks nothing either');
  assert(byTest('print-start').disabled, 'and no print can start');
`);

test('files: a list error says so in place of the table and can be retried', `
  await ready(VIEW());
  await tab('files');
  await fail(last('cmd', 'files'), 'printer timed out');
  const area = () => q('[data-view="files"] .oui-files-scroll');
  assert(text(area()).includes('Couldn’t read the file list') && text(area()).includes('printer timed out'), 'error shown: ' + text(area()));
  assert(q('[role=alert]', area()), 'announced');
  eq(fileNames(), [], 'not shown as an empty list');
  assert(!text(area()).includes('No files on the printer'), 'a failed read is not "no files"');
  await click(btn('Try again', area()));
  eq(cmds('files').length, 2, 'retry');
  await reply(last('cmd', 'files'), {files: [{name: 'a.gcode', size: 1, timestamp: 1700000000}]});
  eq(fileNames(), ['a.gcode'], 'the list once it is read');
`);

// ------------------------------------------------------------------ time-lapses (Files tab)
test('time-lapses: a second list in the browser; each video shows its print, date, length and size; an empty one is marked; no download', `
  await openVideos();
  eq(qa('[data-list]').map(b => b.dataset.list), ['local', 'videos'], 'a second list beside the print files');
  eq([text(q('[data-list="videos"]')), q('[data-list="videos"]').getAttribute('aria-pressed'), q('[data-list="local"]').getAttribute('aria-pressed')], ['Time-lapses', 'true', 'false'], 'named, and open');
  eq(q('[data-test="files-lists"]').getAttribute('role'), 'group', 'the switch is one group');
  eq(filesCount(), '2 videos', 'count');
  eq(fileNames(), ['benchy-20261116215053_8.mp4', CUBE], 'newest first');
  const cells = qa('td', videoRow('benchy-20261116215053_8.mp4')).map(text);
  assert(cells[1].includes('benchy-20261116215053_8.mp4') && cells[1].includes('1:23'), 'file name and length: ' + cells[1]);
  eq(cells[2], '4.1 MB', 'size');
  assert(/\\d/.test(cells[3]), 'date: ' + cells[3]);
  eq(qa('[data-view="files"] thead th').map(text).slice(1), ['Name', 'Size', 'Recorded'], 'columns');
  const empty = videoRow(CUBE);
  assert(text(empty).includes('Empty') && !text(videoRow('benchy-20261116215053_8.mp4')).includes('Empty'), 'only the empty one is marked');
  await click(empty);
  const detail = text(q('[data-view="files"] .oui-files-detail'));
  assert(detail.includes('cube') && detail.includes('Nothing was recorded'), 'its print, and why it is empty: ' + detail);
  assert(!byTest('print-panel'), 'a video is not printed');
  assert(btn('Delete', filesBar()) && !btn('Delete', filesBar()).disabled, 'an empty one can be deleted');
  eq(qa('[data-view="files"] .oui-files-list img, [data-view="files"] .oui-files-detail img').length, 0, 'no cover picture is fetched');
  await click(q('[data-list="local"]'));
  await reply(last('cmd', 'files'), {files: [{name: 'a.gcode', size: 1, timestamp: 1700000000}]});
  eq([filesCount(), q('[data-list="local"]').getAttribute('aria-pressed')], ['1 file', 'true'], 'back to the print files, read again, with nothing selected');
  assert(text(byTest('videos-note')).includes('can’t be downloaded'), 'says why there is no download: ' + text(byTest('videos-note')));
  assert(!qa('button, a', q('[data-view="files"]')).some(b => /download/i.test(text(b))), 'no download control');
`);

test('time-lapses: delete asks first, sends each file name, refreshes the list and keeps the focus', `
  await openVideos();
  await click(videoRow(CUBE));
  btn('Delete', filesBar()).focus();
  await click(btn('Delete', filesBar()));
  assert(dialogOpen() && dialogText().includes('Delete 1 time-lapse?') && dialogText().includes(CUBE), 'asks, naming the video: ' + dialogText());
  eq(text(q('[data-dlg="confirm"]')), 'Delete', 'the action is named');
  assert(q('[data-dlg="confirm"]').classList.contains('p-button-danger'), 'destructive action is red');
  await until(() => document.activeElement === q('[data-dlg="cancel"]'), 'focus starts on the way back');
  await answer('cancel');
  eq(cmds('video_delete'), [], 'going back deletes nothing');
  await click(btn('Delete', filesBar())); await answer('confirm');
  eq(cmds('video_delete').map(m => m.args), [{name: CUBE}], 'video_delete with the file name');
  eq(cmds('videos').length, 1, 'the list waits for the delete');
  await reply(last('cmd', 'video_delete'), {deleted: CUBE});
  await until(() => cmds('videos').length === 2, 'list asked again');
  await reply(last('cmd', 'videos'), {videos: VIDEOS().slice(0, 1)});
  eq(fileNames(), ['benchy-20261116215053_8.mp4'], 'the deleted video is gone');
  eq(filesCount(), '1 video', 'count follows');
  assert(toasts().includes('Time-lapse deleted.'), 'says it is deleted: ' + toasts());
  await until(focusInList, 'the keyboard stays in the list, not lost');
  eq(cmds('file_delete'), [], 'never the file command');
`);

test('time-lapses: several are deleted one message each, in turn, behind one question; a failure says how many are left', `
  const V = (n, t) => ({filename: n + '.mp4', name: n, created: t, duration: 60, size: 1000, empty: false});
  await openVideos([V('a', 3), V('b', 2), V('c', 1)]);
  await click(q('.oui-files-table thead input'));
  eq(filesCount(), '3 selected', 'all three');
  await click(btn('Delete', filesBar()));
  assert(dialogText().includes('Delete 3 time-lapses?'), 'asks once for the three: ' + dialogText());
  await answer('confirm');
  await until(() => cmds('video_delete').length === 1, 'the first is sent');
  eq(cmds('video_delete').map(m => m.args), [{name: 'a.mp4'}], 'one video per message');
  assert(btn('Delete', filesBar()).disabled, 'no second delete while this one runs');
  await reply(last('cmd', 'video_delete'), {deleted: 'a.mp4'});
  await until(() => cmds('video_delete').length === 2, 'then the second');
  await fail(last('cmd', 'video_delete'), 'the printer refused the delete (code 10110): busy');
  await until(() => cmds('video_delete').length === 3, 'the third still goes');
  eq(cmds('videos').length, 1, 'the list waits for the last one');
  await reply(last('cmd', 'video_delete'), {deleted: 'c.mp4'});
  await until(() => cmds('videos').length === 2, 'the list is read once, at the end');
  await reply(last('cmd', 'videos'), {videos: [V('b', 2)]});
  assert(alerts().includes('Delete time-lapse failed') && alerts().includes('1 of 3 could not be deleted') && alerts().includes('10110'), 'says how many failed, and why: ' + alerts());
  assert(!toasts().includes('deleted.'), 'a partial delete is not reported as done: ' + toasts());
  eq(fileNames(), ['b.mp4'], 'what is left on the printer');
  eq(filesCount(), '1 selected', 'the one that could not be deleted is still selected, to try again');
  // all of them going is one line
  await click(btn('Delete', filesBar())); await answer('confirm');
  await reply(last('cmd', 'video_delete'), {deleted: 'b.mp4'});
  await until(() => cmds('videos').length === 3, 'read again');
  await reply(last('cmd', 'videos'), {videos: []});
  assert(toasts().includes('Time-lapse deleted.'), 'done: ' + toasts());
`);

test('time-lapses: the focus is kept when the printer answers before the dialog has closed', `
  await openVideos();
  await click(videoRow(CUBE));
  btn('Delete', filesBar()).focus();
  await click(btn('Delete', filesBar()));
  await until(dialogOpen, 'dialog');
  q('[data-dlg="confirm"]').click();   // no waiting for the dialog to leave: both answers arrive while it closes
  await until(() => last('cmd', 'video_delete'), 'delete sent');
  __t.handler({type: 'reply', id: last('cmd', 'video_delete').id, result: {deleted: CUBE}});
  await until(() => cmds('videos').length === 2, 'list asked again');
  __t.handler({type: 'reply', id: last('cmd', 'videos').id, result: {videos: VIDEOS().slice(0, 1)}});
  await until(() => !videoRow(CUBE) && !dialogOpen(), 'row gone and dialog closed');
  await until(focusInList, 'the keyboard is in the list, not lost');
`);

test('time-lapses: empty list, a list error with retry, and a refused delete reads the list again', `
  await openVideos([]);
  const area = () => q('[data-view="files"] .oui-files-scroll');
  assert(text(area()).includes('No time-lapses on the printer'), 'empty state: ' + text(area()));
  eq(filesCount(), '0 videos', 'none');
  await click(byTest('refresh'));
  eq(cmds('videos').length, 2, 'refresh asks again');
  eq(cmds('files').length, 1, 'only for the list that is open');
  await fail(last('cmd', 'videos'), 'the printer did not answer the time-lapse list');
  assert(text(area()).includes('Couldn’t read the time-lapses') && text(area()).includes('did not answer the time-lapse list'), 'error shown: ' + text(area()));
  assert(q('[role=alert]', area()), 'announced');
  await click(btn('Try again', area()));
  eq(cmds('videos').length, 3, 'retry');
  await reply(last('cmd', 'videos'), {videos: VIDEOS()});
  await click(videoRow(CUBE));
  await click(btn('Delete', filesBar())); await answer('confirm');
  await fail(last('cmd', 'video_delete'), 'the printer refused the delete (code 10110): busy');
  assert(alerts().includes('Delete time-lapse failed') && alerts().includes('10110'), 'the reason stays on screen: ' + alerts());
  await until(() => cmds('videos').length === 4, 'the list is read again: it shows what is on the printer');
  await reply(last('cmd', 'videos'), {videos: VIDEOS()});
  assert(videoRow(CUBE), 'the video stays and can be tried again');
  assert(!toasts().includes('Time-lapse deleted.'), 'not reported as deleted');
`);

test('time-lapses: offered only for a connected printer, also while it prints', `
  await until(() => last('hello'), 'hello sent');
  await tab('files');
  assert(!q('[data-list]'), 'no list to switch to before the printer answered');
  eq([cmds('videos'), cmds('files')], [[], []], 'nothing asked without a printer');
  await ready(PRINTING(), 4);
  await until(() => last('cmd', 'files'), 'the open list is read once connected');
  await click(q('[data-list="videos"]'));
  await until(() => last('cmd', 'videos'), 'asked when its list is opened');
  eq(last('cmd', 'videos').gen, 4, 'for this printer');
  await reply(last('cmd', 'videos'), {videos: VIDEOS()});
  await click(videoRow(CUBE));
  assert(!btn('Delete', filesBar()).disabled && !byTest('refresh').disabled, 'usable during a print');
  await click(btn('Delete', filesBar())); await answer('confirm');
  eq(cmds('video_delete').map(m => [m.args, m.gen]), [[{name: CUBE}, 4]], 'delete during a print, for this printer');
  await post({type: 'selection_changed'});
  assert(!q('[data-list="videos"]'), 'gone with the printer');
`);

test('pt-BR: the files browser and its time-lapses are translated', `
  await openVideos();
  eq(filesCount(), '2 vídeos', 'count');
  eq(qa('[data-view="files"] thead th').map(text).slice(1), ['Nome', 'Tamanho', 'Gravado'], 'columns');
  eq(qa('[data-list]').map(text), ['Arquivos de impressão', 'Time-lapses'], 'the two lists');
  eq(q('[data-test="files-lists"]').getAttribute('aria-label'), 'Na impressora', 'the switch is named');
  assert(text(videoRow(CUBE)).includes('Vazio'), 'empty: ' + text(videoRow(CUBE)));
  assert(text(byTest('videos-note')).includes('Ainda não é possível baixar'), 'note: ' + text(byTest('videos-note')));
  await click(videoRow(CUBE));
  assert(text(q('[data-view="files"] .oui-files-detail')).includes('Nada foi gravado'), 'why it is empty: ' + text(q('[data-view="files"] .oui-files-detail')));
  eq(filesCount(), '1 selecionado', 'selection');
  await click(btn('Excluir', filesBar()));
  assert(dialogText().includes('Excluir 1 time-lapse?') && dialogText().includes('não pode ser desfeita') && !dialogText().includes('Eles'), 'dialog: ' + dialogText());
  eq([text(q('[data-dlg="cancel"]')), text(q('[data-dlg="confirm"]'))], ['Voltar', 'Excluir'], 'both answers named');
  await answer('cancel');
  await click(btn('Limpar', filesBar()));
  eq(text(q('[data-view="files"] .oui-files-detail')), 'Nenhum arquivo selecionado', 'nothing selected');
`, { lang: 'pt-BR' });

test('files: the print panel shows what the file needs and which slot prints each filament', `
  await openDetails(DETAILS());
  const info = text(q('[data-view="files"] .oui-files-detail'));
  for (const want of ['benchy.gcode', '4.2 MB', '7 h 10 min', '1,875', '103 g', '0.16 mm', '205 / 60 °C']) assert(info.includes(want), want + ' in ' + info);
  eq(qa('[data-mat]').length, 2, 'one row per filament');
  assert(text(q('[data-mat="0"]')).includes('Spool holder · Slot 1') && text(q('[data-mat="0"]')).includes('PETG'), 'slot of filament 1: ' + text(q('[data-mat="0"]')));
  assert(text(byTest('mat-warn')).includes('ACE 1 · Slot 2') && text(byTest('mat-warn')).includes('ABS'), 'mismatch named: ' + text(byTest('mat-warn')));
  assert(!byTest('model-warn'), 'sliced for a Kobra X: no model warning');
  await click(byTest('print-start'));
  assert(dialogOpen() && dialogText().includes('ABS'), 'the confirmation repeats the mismatch: ' + dialogText());
  await no();
  eq(cmds('file_print'), [], 'nothing printed');
`);

test('files: a file sliced for another printer or with no loaded slot is flagged', `
  await openDetails(DETAILS({info: {...DETAILS().info, printer_model: 'Anycubic Kobra 3', model_ok: false},
    materials: [{paint_index: 7, material: 'PLA', colour: '#E10600', grams: 5, slot: null, slot_type: '', slot_colour: '', check: 'missing'}]}));
  assert(text(byTest('model-warn')).includes('Anycubic Kobra 3'), 'model named: ' + text(byTest('model-warn')));
  assert(text(byTest('mat-warn')).includes('Filament 8'), 'missing slot named: ' + text(byTest('mat-warn')));
`);

test('files: details without the new fields still show the panel', `
  await openDetails({name: 'benchy.gcode', thumbnail: PNG});
  eq(qa('[data-mat]').length, 0, 'no material rows');
  assert(!byTest('mat-warn') && !byTest('model-warn'), 'no warnings');
  await click(byTest('print-start'));
  assert(dialogOpen() && !dialogText().includes('Not as sliced'), 'plain confirmation');
  await no();
`);

test('files: fuzzy search, best match first; a grid of pictures, kept for next time; the menu only deletes', `
  await ready(VIEW());
  await tab('files');
  const names = ['my_bench_2.gcode', 'xbenchx.gcode', 'benchy_PLA.gcode', 'Bench.gcode', 'clip.gcode'];
  await reply(last('cmd', 'files'), {files: names.map((name, i) => ({name, size: 1000, timestamp: 1700000000 - i}))});
  await type(byTest('files-q'), 'bench');
  await until(() => fileNames().length === 4, 'filtered');
  eq(fileNames(), ['Bench.gcode', 'benchy_PLA.gcode', 'my_bench_2.gcode', 'xbenchx.gcode'], 'exact, prefix, word start, inside a word');
  eq(text(q('[data-view="files"] .oui-files-hit')), 'Bench', 'the match is marked');
  await type(byTest('files-q'), 'bnch pla');
  await until(() => fileNames().length === 1);
  eq(fileNames(), ['benchy_PLA.gcode'], 'letters in order, separators skipped, any case');
  await type(byTest('files-q'), '');
  await until(() => fileNames().length === 5, 'cleared');
  // The grid: the same files as cards, the choice kept for the plugin.
  await click(q('[data-view="files"] [data-files-view="grid"]'));
  eq([qa('[data-view="files"] .oui-files-card[data-file]').length, !!q('[data-view="files"] .oui-files-table')], [5, false], 'cards instead of the table');
  eq(localStorage.getItem('oui-files-view:' + location.pathname + ':kobracontrol'), 'grid', 'kept');
  await click(fileRow('clip.gcode'));
  eq(fileRow('clip.gcode').getAttribute('aria-selected'), 'true', 'a card is selected like a row');
  // The context menu: the Kobra X can only delete, so that is all it offers.
  fileRow('clip.gcode').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true, clientX: 10, clientY: 10}));
  await until(() => q('.oui-menu'), 'a menu');
  eq(qa('.oui-menu [role=menuitem]').map(text), ['Delete'], 'only Delete');
  await click(q('.oui-menu [role=menuitem]'));
  await answer('confirm');
  eq(last('cmd', 'file_delete').args, {names: ['clip.gcode']}, 'deletes after asking');
  await click(q('[data-view="files"] [data-files-view="list"]'));
`);

test('files: right-click on the empty list and on a time-lapse: only what the Kobra X can do', `
  await openVideos();
  const menuAt = (el, x, y) => el.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true, clientX: x, clientY: y}));
  const items = () => qa('.oui-menu [role=menuitem]').map(text);
  menuAt(videoRow(CUBE), 20, 20);
  await until(() => q('.oui-menu'), 'a time-lapse’s menu');
  eq(items(), ['Delete'], 'a time-lapse can only be deleted (the Kobra X does not give the file)');
  await press('Escape');
  await click(q('[data-list="local"]'));
  await until(() => last('cmd', 'files'));
  await reply(last('cmd', 'files'), {files: [{name: 'a.gcode', size: 1, timestamp: 1700000000}, {name: 'b.gcode', size: 1, timestamp: 1700000001}]});
  await until(() => fileNames().length === 2);
  const scroll = q('[data-view="files"] .oui-files-scroll'), r = scroll.getBoundingClientRect();
  menuAt(scroll, r.left + r.width / 2, r.bottom - 8);
  await until(() => q('.oui-menu'), 'a menu on the empty list');
  eq(items(), ['Select all files', 'Grid', 'Refresh'], 'no folders, so no New folder');
  await click(q('.oui-menu [data-menu="select-all"]'));
  eq(filesCount(), '2 selected', 'Select all');
  const asked = cmds('files').length;
  menuAt(scroll, r.left + r.width / 2, r.bottom - 8);
  await until(() => q('.oui-menu'));
  await click(q('.oui-menu [data-menu="refresh"]'));
  await until(() => cmds('files').length > asked, 'Refresh reads the list again');
  await reply(last('cmd', 'files'), {files: []});
`);

test('files: an empty list says 0 files (Portuguese puts 0 in the plural rule "one")', `
  await ready(VIEW());
  await tab('files');
  await reply(last('cmd', 'files'), {files: []});
  await until(() => filesCount());
  eq(filesCount(), '0 arquivos', 'not "1 arquivo"');
`, { lang: 'pt-BR' });

test('files: search and sort the list', `
  await ready(VIEW());
  await tab('files');
  await reply(last('cmd', 'files'), {files: [{name: 'benchy.gcode', size: 4200000, timestamp: 1700000000}, {name: 'cube.gcode', size: 900000, timestamp: 1699000000},
    {name: 'Arch.gcode', size: 9000000, timestamp: 1698000000}]});
  const names = fileNames;
  eq(names(), ['benchy.gcode', 'cube.gcode', 'Arch.gcode'], 'newest first by default');
  await type(byTest('files-q'), 'CU');
  await until(() => names().length === 1, 'filtered');
  eq(names(), ['cube.gcode'], 'search ignores case');
  eq(filesCount(), 'Showing 1 of 3 files', 'count');
  await type(byTest('files-q'), 'zzz');
  await until(() => !names().length, 'no match');
  assert(text(q('[data-view="files"] .oui-files-scroll')).includes('No file matches “zzz”'), 'says what found nothing: ' + text(q('[data-view="files"] .oui-files-scroll')));
  await type(byTest('files-q'), '');
  await until(() => names().length === 3, 'cleared');
  const head = label => btn(label, q('[data-view="files"] thead'));
  await click(head('Name'));
  eq(names(), ['Arch.gcode', 'benchy.gcode', 'cube.gcode'], 'by name');
  await click(head('Size'));
  eq(names(), ['Arch.gcode', 'benchy.gcode', 'cube.gcode'], 'largest first');
  await click(head('Added'));
  eq(names(), ['benchy.gcode', 'cube.gcode', 'Arch.gcode'], 'newest first');
  await click(head('Added'));
  eq(names(), ['Arch.gcode', 'cube.gcode', 'benchy.gcode'], 'oldest first');
`);

test('status: a running print says when it will finish', `
  const at = Math.floor(Date.now() / 1000);
  await ready(PRINTING({updated_at: at, remaining_s: 7000}));
  const want = new Intl.DateTimeFormat('en', {timeStyle: 'short'}).format(new Date((at + 7000) * 1000));
  assert(text(byTest('eta')).includes(want), 'finish time ' + want + ' in ' + text(byTest('eta')));
  await post({type: 'status', data: PRINTING({updated_at: at, remaining_s: 0})});
  assert(!byTest('eta'), 'no remaining time: no finish time');
  await post({type: 'status', data: PRINTING({updated_at: at, remaining_s: 7000, preparing: true, kobra_state: 'nozzle_heating'})});
  assert(!byTest('eta'), 'preparing: the printer reports no real remaining time yet');
`);

test('tls: a changed printer certificate is shown, the fingerprint is in Settings', `
  await ready(VIEW({tls: {fingerprint: 'ab'.repeat(32), changed_from: ''}}));
  assert(!byTest('tls-changed'), 'same certificate: no warning');
  await post({type: 'status', data: VIEW({tls: {fingerprint: 'ab'.repeat(32), changed_from: 'cd'.repeat(32)}})});
  await until(() => byTest('tls-changed'), 'warning');
  assert(text(byTest('tls-changed')).includes('certificate changed') && text(byTest('tls-changed')).includes('Bench Kobra'), 'warning: ' + text(byTest('tls-changed')));
  await tab('settings');
  assert(text(byTest('tls-fp')).includes('AB:AB:AB'), 'fingerprint: ' + text(byTest('tls-fp')));
  assert(text(byTest('tls-fp')).includes('CD:CD:CD'), 'previous fingerprint: ' + text(byTest('tls-fp')));
  assert(byTest('tls-changed'), 'the warning stays on every tab');
`);

// ------------------------------------------------------------------ notices
test('toasts: a command result appears bottom-left with a Close button and goes away when closed', `
  await ready(PRINTING());
  await click(q('[data-test="pause"]'));
  await fail(last('cmd', 'pause'), 'printer refused the pause');
  const t = q('.oui-toast[role=alert]');
  assert(t && toastText(t) === 'Pause failed: printer refused the pause', 'error toast: ' + toasts());
  eq(q('.oui-toasts').getAttribute('aria-label'), 'Notifications', 'the region is named');
  const r = t.getBoundingClientRect();
  assert(r.left < 40 && innerHeight - r.bottom < 40, 'bottom-left: ' + JSON.stringify(r));
  assert(!q('.notices .oui-banner'), 'not a banner under the app bar');
  const close = q('.oui-toast-close', t);
  eq(close.getAttribute('aria-label'), 'Close', 'close button named');
  await post({type: 'status', data: PRINTING()});
  assert(q('.oui-toast[role=alert]'), 'an error stays across status updates');
  await click(close);
  await until(() => !q('.oui-toast'), 'closed');
`);

test('banners: a closed banner stays closed while its condition lasts and comes back when it changes', `
  const tls = (fp, from) => VIEW({tls: {fingerprint: fp, changed_from: from}});
  await ready(tls('ab'.repeat(32), 'cd'.repeat(32)));
  await until(() => byTest('tls-changed'), 'warning');
  const close = q('.oui-banner-close', byTest('tls-changed'));
  eq(close.getAttribute('aria-label'), 'Close', 'close button named');
  await click(close);
  assert(!byTest('tls-changed'), 'closed');
  for (let i = 0; i < 3; i++) await post({type: 'status', data: tls('ab'.repeat(32), 'cd'.repeat(32))});
  await tab('files'); await tab('dash');
  assert(!byTest('tls-changed'), 'same certificate: stays closed across polls and re-renders');
  await post({type: 'status', data: tls('ef'.repeat(32), 'ab'.repeat(32))});
  await until(() => byTest('tls-changed'), 'another certificate: the warning is back');
`);

test('banners: the unconfirmed filament use banner can be closed and returns for another entry', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'));
  await reply(last('cmd', 'usage'), USAGE({unconfirmed: [ENTRY]}));
  await until(() => byTest('usage-banner'), 'banner');
  await click(q('.oui-banner-close', byTest('usage-banner')));
  assert(!byTest('usage-banner'), 'closed');
  for (const view of [USAGE({unconfirmed: [ENTRY]}), USAGE({unconfirmed: [ENTRY, {...ENTRY, id: 'def', file: 'gcodes/cube.gcode'}]})]) {
    const n = cmds('usage').length;
    await until(() => cmds('usage').length > n, 'the page polls the use again', 15000);   // every 10 s
    await reply(last('cmd', 'usage'), view);
    if (view.unconfirmed.length === 1) assert(!byTest('usage-banner'), 'same entry: stays closed');
  }
  await until(() => byTest('usage-banner'), 'another entry: the banner is back');
  assert(text(byTest('usage-banner')).includes('2 filament uses are not confirmed'), 'says both: ' + text(byTest('usage-banner')));
`);

test('banners: a closed banner shows again when its condition clears and the same entries come back', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'));
  await reply(last('cmd', 'usage'), USAGE({unconfirmed: [ENTRY]}));
  await until(() => byTest('usage-banner'), 'banner');
  await click(q('.oui-banner-close', byTest('usage-banner')));
  assert(!byTest('usage-banner'), 'closed');
  for (const view of [USAGE(), USAGE({unconfirmed: [ENTRY]})]) {
    const n = cmds('usage').length;
    await until(() => cmds('usage').length > n, 'the page polls the use again', 15000);   // every 10 s
    await reply(last('cmd', 'usage'), view);
    if (!view.unconfirmed.length) assert(!byTest('usage-banner') && !byTest('usage-card')?.checkVisibility(), 'cleared: nothing shown');
  }
  await until(() => byTest('usage-banner'), 'the same entry again: the banner is back');
`);

test('pt-BR: the new file, finish-time and certificate texts are translated', `
  const at = Math.floor(Date.now() / 1000);
  await ready(PRINTING({updated_at: at, remaining_s: 7000, tls: {fingerprint: 'ab'.repeat(32), changed_from: 'cd'.repeat(32)}}));
  assert(text(byTest('job-card')).includes('Termina') && byTest('eta'), 'eta: ' + text(byTest('job-card')));
  assert(text(byTest('tls-changed')).includes('certificado da impressora mudou'), 'tls: ' + text(byTest('tls-changed')));
  await post({type: 'status', data: VIEW()});
  await tab('files');
  await reply(last('cmd', 'files'), {files: [{name: 'benchy.gcode', size: 1, timestamp: 1700000000}, {name: 'cube.gcode', size: 1, timestamp: 1}]});
  await type(byTest('files-q'), 'cube');
  await until(() => qa('[data-file]').length === 1, 'filtered');
  eq(filesCount(), 'Mostrando 1 de 2 arquivos', 'count');
  await click(fileRow('cube.gcode'));
  await reply(last('cmd', 'file_details'), DETAILS({name: 'cube.gcode'}));
  await until(() => byTest('mat-warn'), 'details');
  assert(text(q('[data-view="files"] .oui-files-detail')).includes('Tempo estimado'), 'info: ' + text(q('[data-view="files"] .oui-files-detail')));
  assert(text(byTest('mat-warn')).includes('ABS'), 'mismatch: ' + text(byTest('mat-warn')));
`, { lang: 'pt-BR' });

// ------------------------------------------------------------------ settings
test('settings: connection fields save together; unsaved is flagged; Saved only after the answer', `
  await ready(VIEW());
  await tab('settings');
  assert(q('#c-host').value === '' && q('#c-name').value === 'Bench Kobra' && q('#c-ffmpeg').value === '', 'filled from config');
  assert(!text(q('.sv')).includes('Unsaved'), 'clean at first');
  await type(q('#c-host'), '192.168.1.60');
  await type(q('#c-ffmpeg'), '/opt/ffmpeg');
  await click(q('input#c-vib'));
  assert(text(q('.sv')).includes('Unsaved changes'), 'flagged');
  await post(CONFIG());
  eq(q('#c-host').value, '192.168.1.60', 'a config message does not wipe what is being edited');
  await click(byTest('save-top'));
  const m = last('save_settings');
  eq(m.settings, {host: '192.168.1.60', printer_name: 'Bench Kobra', ffmpeg_path: '/opt/ffmpeg', camera_enabled: false, auto_leveling: true, vibration_compensation: false,
    flow_calibration: false, timelapse: false, spoolman_url: 'http://box:7912', spoolman_auto: true, spoolman_report_usage: true, print_dialog: true, remember_print_options: true,
    bridge_enabled: false, bridge_port: 8765, cloud_enabled: false, cloud_printer: '', ofd_enabled: false}, 'every setting, by its name');
  assert(!toasts().includes('Settings saved'), 'not saved before the answer');
  await reply(m, {});
  assert(toasts().includes('Settings saved'), 'saved after the answer');
  await until(() => sent().filter(x => x.type === 'hello').length === 2, 'reconnects with the new address');
`);

test('settings: a failed save keeps the typed values and says why', `
  await ready(VIEW());
  await tab('settings');
  await type(q('#c-host'), '10.0.0.9');
  await click(byTest('save-top'));
  await fail(last('save_settings'), 'address is not valid');
  assert(alerts().includes('weren’t saved: address is not valid'), 'error stays: ' + alerts());
  eq(q('#c-host').value, '10.0.0.9', 'typed values stay');
`);

test('settings: a save that could not connect says so', `
  await ready(VIEW());
  await tab('settings');
  await type(q('#c-host'), '10.0.0.9');
  await click(byTest('save-top'));
  await reply(last('save_settings'), {connect_error: 'printer not reachable'});
  assert(alerts().includes('the printer didn’t connect: printer not reachable'), 'says so: ' + alerts());
`);

test('settings: certificate status and Find certificate', `
  await ready(VIEW());
  await tab('settings');
  eq(text(byTest('cert-status')), 'Certificate: built in.', 'the normal state');
  assert(text(q('#cert-h').closest('section')).includes('Anycubic Slicer Next is not needed'), 'no install needed');
  assert(!byTest('cert-advanced').open, 'reading the Anycubic install is an advanced, closed action');
  await post(CONFIG({certificate: {found: true, source: 'saved'}}));
  eq(text(byTest('cert-status')), 'Certificate: copied from your Anycubic Slicer Next install.', 'saved copy');
  await post(CONFIG({certificate: {found: false, source: ''}}));
  assert(text(byTest('cert-status')).includes('No certificate found yet'), 'missing: ' + text(byTest('cert-status')));
  await click(q('[data-test="cert-advanced"] summary'));
  await type(q('#set-cert-path'), '/opt/anycubic');
  await click(byTest('find-cert'));
  eq(cmds('find_certificate').map(m => m.args), [{path: '/opt/anycubic'}], 'optional path');
`);

test('settings: print defaults, camera default and Spoolman options are saved under the plugin names', `
  await ready(VIEW());
  await tab('settings');
  await click(byTest('cam-default').querySelector('input'));
  await click(byTest('def-leveling').querySelector('input'));
  await click(q('input#c-sm-usage'));
  await click(byTest('save-top'));
  const s = last('save_settings').settings;
  eq([s.camera_enabled, s.auto_leveling, s.spoolman_report_usage], [true, false, false], 'flags');
`);

test('settings: upload bridge is off by default; key, copy, new key and OrcaSlicer steps', `
  await ready(VIEW());
  await post(CONFIG({bridge: {enabled: false, running: false, port: 8765, host: '127.0.0.1', key: 'KEY-aaaaaaaaaaaaaaaaaaaaaa', error: ''}}));
  await tab('settings');
  eq(q('input#c-bridge').checked, false, 'off by default');
  eq(text(byTest('bridge-chip')), 'Off', 'chip');
  eq(byTest('bridge-key').value, 'KEY-aaaaaaaaaaaaaaaaaaaaaa', 'key shown');
  eq(byTest('bridge-address').value, '127.0.0.1:8765', 'address shown, to copy into the OctoPrint physical printer');
  assert(text(byTest('bridge-steps')).includes('OctoPrint') && text(byTest('bridge-steps')).includes('127.0.0.1:8765'), 'steps: ' + text(byTest('bridge-steps')));
  await click(q('input#c-bridge'));
  await click(byTest('save-top'));
  const m = last('save_settings');
  eq([m.settings.bridge_enabled, m.settings.bridge_port], [true, 8765], 'switch saved');
  assert(!('key' in m.settings), 'the key is never part of the settings');
  await reply(m, {});
  await post(CONFIG({settings: {...SETTINGS, bridge_enabled: true}, bridge: {enabled: true, running: true, port: 8765, host: '127.0.0.1', key: 'KEY-aaaaaaaaaaaaaaaaaaaaaa', error: ''}}));
  eq(text(byTest('bridge-state')), 'Listening on 127.0.0.1:8765', 'running');
  await click(byTest('bridge-new-key'));
  await until(() => last('bridge_new_key'), 'new key asked');
  await reply(last('bridge_new_key'), {renewed: true});
  await until(() => toasts().includes('old one no longer works'), 'new key said');
  await post(CONFIG({settings: {...SETTINGS, bridge_enabled: true}, bridge: {enabled: true, running: false, port: 8765, host: '127.0.0.1', key: 'k', error: 'port 8765 could not be opened (Address already in use)'}}));
  assert(text(byTest('bridge-state')).includes('Address already in use'), 'error shown: ' + text(byTest('bridge-state')));
`);
const CLOUD_JS = `
const CLOUD_ON = extra => CONFIG({settings: {...SETTINGS, cloud_enabled: true, cloud_printer: '', ...extra}});
const CLOUD_PRINTERS = [{id: '42', name: 'Garage K2', model: 'Kobra 2 Pro', online: true, printing: false},
  {id: '77', name: 'Office K2', model: 'Kobra 2 Max', online: false, printing: false}];
`;
test('anycubic cloud: off by default; turning it on and saving shows the sign-in', CLOUD_JS + `
  await ready(VIEW());
  await tab('settings');
  await click(q('.oui-settings-link[data-section="cloud-h"]'));
  eq(q('input#c-cloud').checked, false, 'off by default');
  eq(text(byTest('cloud-chip')), 'Off', 'chip');
  assert(text(q('#cloud-h')).includes('Kobra 2') && text(q('[data-test="cloud-more"]')).includes('cloud-universe.anycubic.com'), 'says who gets what');
  eq(byTest('cloud-sign-in'), null, 'no sign-in while off');
  eq(cmds('cloud_state'), [], 'nothing asked while off');
  await click(q('input#c-cloud'));
  assert(byTest('cloud-save-first'), 'asks to save first');
  await click(byTest('save-top'));
  const m = last('save_settings');
  eq([m.settings.cloud_enabled, m.settings.cloud_printer], [true, ''], 'switch saved');
  await reply(m, {});
  await post(CLOUD_ON());
  await until(() => last('cmd', 'cloud_state'), 'state asked once on');
  await reply(last('cmd', 'cloud_state'), {enabled: true, signed_in: false, email: '', slicer_log: false});
  await until(() => byTest('cloud-sign-in'), 'sign-in shown');
  eq(text(byTest('cloud-chip')), 'Not signed in', 'chip');
  eq(byTest('cloud-find').disabled, true, 'no Anycubic Slicer Next logs here: disabled');
  assert(text(byTest('cloud-sign-in')).includes('paste a token'), 'says why');
`);
test('anycubic cloud: Anycubic Slicer Next sign-in shows the email; a pasted token is sent once and cleared', CLOUD_JS + `
  await ready(VIEW());
  await post(CLOUD_ON());
  await tab('settings');
  await click(q('.oui-settings-link[data-section="cloud-h"]'));
  await until(() => last('cmd', 'cloud_state'), 'state asked');
  await reply(last('cmd', 'cloud_state'), {enabled: true, signed_in: false, email: '', slicer_log: true});
  await until(() => byTest('cloud-find') && !byTest('cloud-find').disabled, 'find offered');
  await click(byTest('cloud-find'));
  await fail(last('cmd', 'cloud_find'), 'No Anycubic sign-in was found');
  assert(alerts().includes('No Anycubic sign-in was found'), 'error said: ' + alerts());
  await click(q('[data-test="cloud-paste"] summary'));
  eq(byTest('cloud-token').type, 'password', 'token hidden');
  await type(byTest('cloud-token'), 'eyJsecret');
  await click(byTest('cloud-token-sign-in'));
  eq(last('cmd', 'cloud_sign_in').args, {token: 'eyJsecret'}, 'token sent');
  eq(byTest('cloud-token').value, '', 'cleared at once');
  await fail(last('cmd', 'cloud_sign_in'), 'token expired');
  await click(byTest('cloud-find'));
  await reply(last('cmd', 'cloud_find'), {email: 'me@example.org'});
  await until(() => byTest('cloud-email'), 'signed in');
  eq(text(byTest('cloud-email')), 'Signed in as me@example.org', 'email');
  eq(text(byTest('cloud-chip')), 'Signed in', 'chip');
  assert(!document.body.innerText.includes('eyJsecret') && !qa('input').some(i => i.value.includes('eyJsecret')), 'the token is not on the page');
  await until(() => last('cmd', 'cloud_printers'), 'printers asked');
  await click(byTest('cloud-sign-out'));
  await reply(last('cmd', 'cloud_sign_out'), {});
  await until(() => byTest('cloud-sign-in'), 'signed out');
  await tab('dash');
  await until(() => byTest('console-log'), 'console');
  const log = text(byTest('console-log'));
  assert(!log.includes('eyJsecret') && log.includes('cloud_sign_in token=***'), 'the console hides the token: ' + log);
`);
test('anycubic cloud: choosing a printer saves cloud_printer; Use the LAN printer clears it', CLOUD_JS + `
  await ready(VIEW());
  await post(CLOUD_ON());
  await tab('settings');
  await click(q('.oui-settings-link[data-section="cloud-h"]'));
  await until(() => last('cmd', 'cloud_state'), 'state asked');
  await reply(last('cmd', 'cloud_state'), {enabled: true, signed_in: true, email: 'me@example.org', slicer_log: true});
  await until(() => last('cmd', 'cloud_printers'), 'printers asked');
  await reply(last('cmd', 'cloud_printers'), CLOUD_PRINTERS);
  await until(() => byTest('cloud-printers'), 'list shown');
  const rows = text(byTest('cloud-printers'));
  assert(rows.includes('Garage K2') && rows.includes('Kobra 2 Pro') && rows.includes('Online') && rows.includes('Offline'), 'rows: ' + rows);
  eq(byTest('cloud-use-lan'), null, 'on the LAN printer: nothing to go back to');
  await click(q('[data-printer="42"] input'));
  const m = last('save_settings');
  eq([m.settings.cloud_enabled, m.settings.cloud_printer], [true, '42'], 'chosen and saved');
  await reply(m, {});
  await post(CLOUD_ON({cloud_printer: '42'}));
  eq(q('[data-printer="42"] input').checked, true, 'checked');
  await click(byTest('cloud-refresh'));
  eq(cmds('cloud_printers').length, 2, 'Refresh asks again');
  await reply(last('cmd', 'cloud_printers'), CLOUD_PRINTERS);
  await click(byTest('cloud-use-lan'));
  eq(last('save_settings').settings.cloud_printer, '', 'back to the LAN printer');
`);
test('anycubic cloud: the dashboard says so; moves, heat and feed say why; Pause and Resume ask first', `
  await ready(PRINTING({transport: 'cloud', can: {pause: true, resume: false, stop: true, move: false, heat: false, feed: false, print: false}}));
  eq(text(byTest('cloud-tag')), 'Anycubic Cloud', 'tag in the page header');
  const why = text(byTest('busy-banner'));
  assert(why.includes('Not available over Anycubic Cloud') && !why.includes('Moves are available'), 'cloud reason: ' + why);
  await click(byTest('pause'));
  assert(dialogOpen() && dialogText().includes('Pause the print on Bench Kobra? The order goes through Anycubic Cloud.'), 'asks: ' + dialogText());
  await no();
  eq(cmds('pause'), [], 'cancel sends nothing');
  await click(byTest('pause'));
  await yes();
  eq(cmds('pause').length, 1, 'confirmed pause sent');
  await reply(last('cmd', 'pause'), true);
  await post({type: 'status', data: PRINTING({transport: 'cloud', state: 'paused', can: {pause: false, resume: true, stop: true, move: false, heat: false, feed: false, print: false}})});
  await click(byTest('resume'));
  assert(dialogText().includes('Resume the print on Bench Kobra?'), 'resume asks: ' + dialogText());
  await yes();
  eq(cmds('resume').length, 1, 'confirmed resume sent');
`);
test('anycubic cloud: on the LAN there is no tag and Pause asks nothing', `
  await ready(PRINTING());
  eq(byTest('cloud-tag'), null, 'no tag');
  await click(byTest('pause'));
  eq(cmds('pause').length, 1, 'sent at once');
`);

test('upload bridge: a print from OrcaSlicer waits for Start; refused while the printer is busy', `
  await ready(VIEW({bridge_pending: {id: 'p1', name: 'cube.gcode', at: 1700000000}}));
  assert(text(byTest('bridge-pending')).includes('cube.gcode'), 'shown: ' + text(byTest('bridge-pending')));
  await click(byTest('bridge-start'));
  const m = last('cmd', 'bridge_start');
  eq(m.args, {id: 'p1'}, 'start carries the request id');
  await reply(m, {started: 'cube.gcode'});
  await post({type: 'status', data: PRINTING({bridge_pending: {id: 'p2', name: 'next.gcode', at: 1700000000}})});
  eq(byTest('bridge-start').disabled, true, 'no Start while printing');
  assert(text(byTest('bridge-pending')).includes('idle'), 'says why');
  await click(byTest('bridge-cancel'));
  eq(last('cmd', 'bridge_cancel').args, {id: 'p2'}, 'cancel');
  await reply(last('cmd', 'bridge_cancel'), {cancelled: true});
  await post({type: 'status', data: PRINTING()});
  eq(byTest('bridge-pending'), null, 'gone when none waits');
`);

test('settings: the language choice is posted; the version shows; the Spooler hint is there', `
  await ready(VIEW());
  await tab('settings');
  assert(text(byTest('version')).includes('Kobra Control 0.1.0'), 'version: ' + text(byTest('version')));
  await post(REQS());   // the plugin sends it with every config
  assert(text(q('.sv')).includes('Spooler detected'), 'Spooler hint');
  await pick(byTest('lang'), 'Português (Brasil)');
  eq(last('ui_language').value, 'pt-BR', 'choice posted');
  assert(text(q('[data-tab="dash"]')) === 'Painel', 'page switched to Portuguese: ' + text(q('[data-tab="dash"]')));
`);

// ------------------------------------------------------------------ language, theme, general
test('pt-BR: the page follows the host language and has no leftover English in the main surfaces', `
  await ready(VIEW());
  eq(qa('[data-tab]').map(text), ['Painel', 'Estoque', 'Arquivos', 'Ajustes'], 'tabs');
  eq(statusText(), 'Pronta', 'state');
  assert(text(byTest('link')) === 'Conectada', 'pill');
  eq(qa('.ace-g').map(text), ['ACE 1', 'Suporte de carretel'], 'groups');
  assert(text(q('[data-slot="3"]')).includes('Carregado na cabeça de impressão'), 'slot state: ' + text(q('[data-slot="3"]')));
  await post({type: 'status', data: PRINTING()});
  assert(text(q('[data-test="pause"]')) === 'Pausar', 'buttons');
  eq(text(q('[data-test="busy-banner"] strong')), 'A impressora está imprimindo.', 'the busy banner: ' + text(byTest('busy-banner')));
  await click(q('[data-test="stop"]'));
  assert(dialogText().includes('Parar a impressão'), 'dialog in Portuguese: ' + dialogText()); await no();
`, { lang: 'pt-BR' });

test('pt-BR: the first-run states are translated', `
  await until(() => last('hello'));
  await fail(last('hello'), 'x', {no_certificate: true});
  assert(text(byTest('first-run-cert')).includes('Certificado necessário') && text(byTest('find-cert')).includes('Procurar certificado'), 'cert: ' + text(byTest('first-run-cert')));
`, { lang: 'pt-BR' });

test('the page never shows U1 wording', `
  await ready(PRINTING());
  const bad = /\\bU1\\b|toolhead|Snapmaker|Moonraker|Klipper|extended firmware|purifier|g-code console/i;   // the Console widget is the page log, not a G-code console
  for (const name of ['dash', 'stock', 'files', 'settings']) {
    await tab(name);
    const shown = qa('[role=tabpanel]').filter(m => m.offsetParent).map(text).join(' ');
    assert(!bad.test(shown), name + ': ' + (shown.match(bad) || [''])[0]);
  }
  assert(!q('[data-tab="console"]'), 'no Console tab');
  assert(!bad.test(text(q('.oui-appbar'))), 'header');
`);

test('the boot block is the one the code reads; icons are compiled in, not injected', `
  assert(document.getElementById('kobra-boot'), 'kobra-boot exists');
  assert(!document.getElementById('kobra-icons'), 'no injected icon map');
  assert(!document.getElementById('u1-boot') && !document.getElementById('u1-icons'), 'no u1 ids');
  assert(qa('svg.oui-icon').length > 3, 'icons are drawn from the shared set');
`);

test('theme follows the host colour while the page runs', `
  const root = document.documentElement;
  root.style.setProperty('--orca-bg', '#f4f4f4');
  await until(() => !root.classList.contains('orca-dark'), 'light', 15000);
  root.style.setProperty('--orca-bg', '#151515');
  await until(() => root.classList.contains('orca-dark'), 'dark after the host changed', 15000);
  eq(getComputedStyle(document.body).backgroundColor, 'rgb(36, 36, 40)', 'OrcaSlicer’s own dark grey: the page is not tinted with the plugin colour');
  root.style.setProperty('--orca-bg', '#f4f4f4');
  await until(() => !root.classList.contains('orca-dark'), 'light again', 15000);
  eq(getComputedStyle(document.body).backgroundColor, 'rgb(240, 240, 240)', 'and its light grey');
`);

test('keyboard focus and typed values survive status refreshes', `
  await ready(PRINTING());
  q('#temp-nozzle').focus();
  await type(q('#temp-nozzle'), '215');
  for (let i = 0; i < 3; i++) await post({type: 'status', data: PRINTING({nozzle_temp: 200 + i})});
  assert(document.activeElement === q('#temp-nozzle'), 'focus stays in the field');
  eq(q('#temp-nozzle').value, '215', 'typed value stays');
  q('[data-test="pause"]').focus();
  await post({type: 'status', data: PRINTING({elapsed_s: 5000})});
  assert(document.activeElement === q('[data-test="pause"]'), 'focus stays on the button');
`);

test('the tabs switch panels and the lease follows the visible tab', `
  await ready(VIEW());
  await tab('stock'); assert(byTest('stock-head').offsetParent && !byTest('job-card').offsetParent, 'stock panel');
  await until(() => last('lease').stock !== undefined && last('lease').camera === false, 'no camera lease off the dashboard');
  await tab('files'); assert(byTest('files-head').offsetParent, 'files panel');
  await tab('settings'); assert(q('#conn-h'), 'settings panel');
  await tab('dash'); assert(byTest('job-card') && byTest('job-card').offsetParent, 'dashboard panel');
  assert(last('lease').stock !== undefined, 'lease has the stock flag');
`);

for (const width of [1040, 720, 420]) {
  test(`no tab scrolls sideways at ${width} px, the hidden (i) bubbles included`, `
  await ready(PRINTING({assist: ASSIST, storage: {total: 8000, used: 2000}}));
  await reply(last('cmd', 'stock'), STOCK());
  await reply(last('cmd', 'spools'), {spools: ROWS, bindings: {}});
  for (const view of ['dash', 'stock', 'files', 'settings']) {
    await tab(view);
    if (view === 'files') { await reply(last('cmd', 'files'), {files: [{name: 'benchy.gcode', size: 4200000, timestamp: 1700000000}]}); await click(fileRow('benchy.gcode')); }
    const wide = qa('body *').filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > innerWidth + 1 && getComputedStyle(e).position !== 'fixed' && !e.closest('.sc-wrap, .oui-files-scroll, .oui-table-wrap, .oui-truncate'); })   // not what scrolls or is cut with an ellipsis inside its own box
      .slice(0, 4).map(e => e.tagName + '.' + String(e.className).slice(0, 40));
    eq([document.documentElement.scrollWidth <= innerWidth, wide], [true, []], view + ' at ' + innerWidth + ' px');
  }
`, { size: [width, 900] });
}

test('one main landmark holds the four tab panels, each with its page header first', `
  await ready(VIEW());
  eq(qa('main').length, 1, 'one main');
  eq(qa('main [role=tabpanel]:not(.oui-settings-body)').map(p => p.getAttribute('aria-labelledby')), ['oui-tab-dash', 'oui-tab-stock', 'oui-tab-files', 'oui-tab-settings'], 'the tab panels are inside it');
  assert(!q('[data-view="files"]').firstElementChild, 'Files is not there, and asks the printer nothing, until its tab is opened');
  eq(cmds('files'), [], 'no file list asked on the Dashboard');
  for (const view of ['dash', 'stock', 'files']) { await tab(view); assert(q('[data-view="' + view + '"]').firstElementChild.classList.contains('oui-pagehead'), view + ': page header first'); }
  // the page's messages sit under the header of the tab that is open
  await post({type: 'offline', error: 'mqtt lost'});
  for (const view of ['dash', 'stock', 'files', 'settings']) {
    await tab(view);
    assert(q('#kc-why').offsetParent && q('[data-view="' + view + '"]').contains(q('#kc-why')), view + ': the banner is on this tab');
    eq(qa('#kc-why').length, 1, view + ': once');
  }
`);

test('Stop is offered whenever the printer allows it; Choose objects only for a running print', `
  await ready(VIEW({can: {pause: false, resume: false, stop: true, move: true, heat: true, feed: true, print: false}}));
  assert(!q('[data-test="stop"]').disabled && !byTest('skip-open') && !byTest('pause'), 'stop on, nothing to skip or pause');
  await post({type: 'status', data: PRINTING()});
  assert(!byTest('skip-open').disabled, 'there while printing');
`);

test('filament use: recently checked entries show without opening Review, and with no failed entry left', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'));
  await reply(last('cmd', 'usage'), USAGE({pending: [{file: 'gcodes/cube.gcode', printer: '192.168.1.50', grams: {'3': 2}}],
    acknowledged: [{...ENTRY, acknowledged_at: 1794300000}], acknowledged_total: 1}));
  assert(!byTest('usage-review'), 'nothing to review');
  assert(text(byTest('usage-recent')).includes('Recently checked (1 in total)'), 'history shown: ' + text(byTest('usage-card')));
  await click(q('[data-test="usage-recent"] summary'));
  assert(text(byTest('usage-recent')).includes('benchy.gcode') && text(byTest('usage-recent')).includes('ACE 1 · Slot 2'), 'entry listed: ' + text(byTest('usage-recent')));
`);

// Spanish, German, Simplified Chinese and Polish: the page follows OrcaSlicer's code (es_ES, de_DE, zh_CN, zh_TW, pl_PL), the main
// surfaces and a confirmation read in that language, and Settings can switch to another one by its native name.
for (const [lang, host, D] of [['es', 'es_ES', es], ['de', 'de_DE', de], ['zh-CN', 'zh_CN', zhCN], ['zh-CN', 'zh_TW', zhCN], ['pl', 'pl_PL', pl]]) {
  const T = JSON.stringify(D);
  test(`${lang} (host ${host}): the page follows the host language; tabs, state, slots, buttons and the stop dialog are translated`, `
const D = ${T};
await ready(VIEW());
eq(document.documentElement.lang, '${lang}', 'html lang');
eq(qa('[data-tab]').map(text), [D['nav.dash'], D['nav.stock'], D['nav.files'], D['nav.settings']], 'tabs');
eq(statusText(), D['status.state.idle'], 'state');
eq(text(byTest('link')), D['link.connected'], 'pill');
eq(qa('.ace-g').map(text), ['ACE 1', D['ace.head']], 'groups');
assert(text(q('[data-slot="3"]')).includes(D['slot.loadedHere']), 'slot state: ' + text(q('[data-slot="3"]')));
await post({type: 'status', data: PRINTING()});
eq(text(q('[data-test="pause"]')), D['act.pause'], 'pause button');
await click(q('[data-test="stop"]'));
assert(dialogText().includes(D['confirm.stop.title']) && dialogText().includes('Bench Kobra'), 'stop dialog: ' + dialogText()); await no();
`, { lang: host });
}
for (const [lang, D, name] of [['es', es, 'Español'], ['de', de, 'Deutsch'], ['zh-CN', zhCN, '简体中文'], ['pl', pl, 'Polski']]) {
  test(`${lang}: chosen in Settings over an English OrcaSlicer, posted and applied`, `
const D = ${JSON.stringify({ dash: D['nav.dash'], fr: D['fr.cert.title'] })};
await ready(VIEW());
await tab('settings');
await pick(byTest('lang'), '${name}');
eq(last('ui_language').value, '${lang}', 'choice posted');
eq(text(q('[data-tab="dash"]')), D.dash, 'page switched');
eq(document.documentElement.lang, '${lang}', 'html lang');
`);
  test(`${lang}: kept as the plugin's saved choice; first-run certificate state translated`, `
const D = ${JSON.stringify({ fr: D['fr.cert.title'], find: D['cert.find'] })};
await until(() => last('hello'));
await fail(last('hello'), 'x', {no_certificate: true});
assert(text(byTest('first-run-cert')).includes(D.fr) && text(byTest('find-cert')).includes(D.find), 'cert: ' + text(byTest('first-run-cert')));
`, { lang: 'en', pref: lang });
}
for (const lang of ['en', 'pt-BR', 'es', 'de', 'zh_CN', 'pl_PL']) {
  test(`files (${lang}): the selection bar and the print options fit inside the browser`, `
await ready(VIEW());
await tab('files');
await reply(last('cmd', 'files'), {files: [{name: 'benchy.gcode', size: 4200000, timestamp: 1700000000}]});
await until(() => fileRow('benchy.gcode'), 'listed');
await click(fileRow('benchy.gcode'));
await reply(last('cmd', 'file_details'), DETAILS());
await until(() => byTest('mat-warn'), 'details');
const inside = (el, box, what) => { const r = el.getBoundingClientRect(), c = box.getBoundingClientRect();
  assert(r.width > 0 && r.left >= c.left - 0.5 && r.right <= c.right + 0.5, what + ' clipped: ' + JSON.stringify([r.left, r.right, c.left, c.right])); };
for (const b of qa('button', filesBar())) inside(b, filesBar(), 'bar button ' + text(b));
const detail = q('[data-view="files"] .oui-files-detail');
for (const el of [byTest('print-start'), ...qa('.fv-opt', detail), ...qa('[data-mat]', detail)]) inside(el, detail, text(el).slice(0, 30));
// the picture is above the name and the facts, never over them (the detail scrolls when it is taller than the browser)
const pic = q('.oui-files-preview', detail).getBoundingClientRect(), name = q('.oui-files-detailname', detail).getBoundingClientRect();
assert(pic.bottom <= name.top + 0.5, 'the picture ends before the name: ' + pic.bottom + ' / ' + name.top);
assert(document.documentElement.scrollWidth <= innerWidth, 'no sideways scroll');
`, { lang });
}
// PrimeVue 5.0.5's InputNumber reads only the locale's decimal sign: in de/es/pt-BR a typed or pasted "100.4" became
// 1004 (over the limit, or a different temperature). Typed and pasted, it must read as 100.4 and heat to 100 °C.
for (const lang of ['en', 'pt_BR', 'es_ES', 'de_DE', 'zh_CN', 'pl_PL']) {
  test(`decimal input (${lang}): "100.4" typed or pasted into a target heats to 100 °C, never 1004`, `
await ready(VIEW());
const field = q('#temp-nozzle');
await type(field, '100.4');
await click(q('[data-set="nozzle"]'));
assert(dialogOpen() && text(q('[data-dlg="yes"]')).includes('100') && !dialogText().includes('1004'), 'typed: ' + field.value + ' / ' + dialogText());
await yes();
eq(cmds('set_temp').map(m => m.args), [{nozzle: 100}], 'typed value sent');
await reply(last('cmd', 'set_temp'), true);
await type(field, '');
field.focus();
const data = new DataTransfer();
data.setData('text/plain', '100.4');
field.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true}));
await settle();
await click(q('[data-set="nozzle"]'));
assert(dialogOpen() && !dialogText().includes('1004'), 'pasted: ' + field.value + ' / ' + dialogText());
await yes();
eq(cmds('set_temp').map(m => m.args), [{nozzle: 100}, {nozzle: 100}], 'pasted value sent');
for (const id of ['#temp-bed', '#fan', '#dry-t-0', '#dry-m-0']) {   // every number field shares the fix
  await type(q(id), '6.5');
  assert(!/^65/.test(q(id).value), id + ': ' + q(id).value);
}
`, { lang });
}
test('zh-CN: Chinese punctuation comes from a Chinese system font, Latin text stays Manrope', `
await ready(VIEW());
const font = getComputedStyle(document.body).fontFamily;
assert(/^"?OuiCJKPunct"?, "?Manrope/.test(font), 'font: ' + font);
`, { lang: 'zh_CN' });
test('en: no Chinese punctuation font outside Chinese', `
await ready(VIEW());
assert(!getComputedStyle(document.body).fontFamily.includes('OuiCJKPunct'), 'font: ' + getComputedStyle(document.body).fontFamily);
`);

// ------------------------------------------------------------------ print dialog (boot mode "print", plugin.ask_print)
const PD = {mode: 'print', data: PRINT_DATA};
const PD_HELP = `
const chip = f => q('[data-test="slot-' + f + '"]');
const submits = () => __t.submits;
async function openPicker(f) { chip(f).click(); await until(() => q('.p-popover [role=radio]') && !q('.p-popover[class*="enter-active"]'), 'picker open'); await settle(); }
async function choose(f, tray) { await openPicker(f); q('.p-popover [data-tray="' + tray + '"]').click(); await until(() => !q('.p-popover'), 'picker closed'); await settle(); }
`;
test('print setup: task, plate, chips, printer slots and options; Start print sends exactly them', PD_HELP + `
  await until(() => sent().some(m => m.ready), 'ready posted');
  eq(byTest('name').value, 'Benchy dual colour', 'task name');
  assert(text(q('.pd-plate')).includes('for Anycubic Kobra X') && text(q('.pd-facts')).includes('2 h 3 min') && text(q('.pd-facts')).includes('43 g / 14.18 m'), 'plate: ' + text(q('.pd-plate')));
  assert(text(q('.pd-printer')).includes('Bench Kobra · 192.168.1.50') && text(byTest('state')) === 'Ready', 'printer: ' + text(q('.pd-printer')));
  eq(qa('.pd-sq').length, 4, 'four slot squares');
  assert(chip(0).getAttribute('aria-label').includes('ACE 1 · Slot 1: PLA · Elegoo Red PLA'), 'chip label: ' + chip(0).getAttribute('aria-label'));
  eq(text(chip(2)), '2', 'second filament on slot 2');
  eq(qa('.pd-grid [data-option]').map(e => e.dataset.option), ['auto_leveling', 'vibration_compensation', 'timelapse', 'flow_calibration', 'auto_feed'], 'grid order');
  assert(q('#pd-o-flow_calibration').disabled && text(q('[data-option="flow_calibration"]')).includes('Settings'), 'flow locked by the setting');
  assert(q('#pd-o-timelapse').disabled && text(q('[data-option="timelapse"]')).includes('support'), 'time-lapse unsupported');
  await click(q('#pd-o-auto_leveling'));
  const field = byTest('name'); await type(field, 'Desk tidy');
  await choose(0, 7);
  assert(qa('[data-kind="variant"]').length === 1 && byTest('print').disabled, 'PLA in a PLA Silk slot needs use anyway');
  await click(q('#pd-ack'));
  await click(byTest('print'));
  const s = submits()[0];
  eq([s.name, s.trays, s.acknowledged], ['Desk tidy', {'0': 7, '2': 5}, ['variant:0:7']], 'name, trays, ack');
  eq(s.options, {auto_leveling: false, vibration_compensation: true, flow_calibration: false, timelapse: false}, 'options');
  eq([s.remember, s.auto_feed], [true, true], 'remember, auto feed');
  assert(byTest('print').disabled && byTest('cancel').disabled, 'sent once');
`, { boot: PD });

test('print setup: the slot picker allows only the same material, by keyboard too', PD_HELP + `
  await until(() => sent().some(m => m.ready), 'ready posted');
  await openPicker(2);
  const discs = qa('.p-popover [role=radio]');
  eq(discs.map(d => d.getAttribute('aria-disabled')), ['true', null, 'true', 'true'], 'PETG: only the PETG slot');
  eq(discs[1].getAttribute('aria-checked'), 'true', 'current one checked');
  assert(text(q('.p-popover')).includes('Only the same material can be selected'), 'rule said');
  eq(document.activeElement, discs[1], 'focus on the chosen disc');
  await press('Escape'); await until(() => !q('.p-popover'), 'closed'); await settle();
  eq(document.activeElement, chip(2), 'focus back on the chip');
  eq(submits().length, 0, 'Escape on the picker only closes it');
  await openPicker(0);
  const pla = qa('.p-popover [role=radio]');
  eq(pla.map(d => d.getAttribute('aria-disabled')), [null, 'true', 'true', null], 'PLA: PLA and PLA Silk');
  eq(pla.map(d => d.querySelector('.oui-spool').dataset.level), ['4', '6', '8', '1'], 'each spool drawn as full as the filament left; a slot that cannot be chosen is the bare reel, an unknown amount the full reel');
  eq(pla.map(d => d.querySelector('.oui-spool-unknown')?.textContent ?? ''), ['', '', '', '?'], 'only the unknown amount has the unknown badge');
  assert(pla[0].getAttribute('aria-label').includes('62'), 'the amount left is said: ' + pla[0].getAttribute('aria-label'));
  await press('ArrowRight'); await settle();
  eq(document.activeElement, pla[3], 'arrow skips the slots that cannot be chosen');
  await press('Enter'); await until(() => !q('.p-popover'), 'chosen'); await settle();
  eq(text(chip(0)), '4', 'slot 4 chosen');
`, { boot: PD });

test('print setup: busy printer locks the settings; refresh and live change; Escape cancels', PD_HELP + `
  await until(() => sent().some(m => m.ready), 'ready posted');
  const slots = JSON.parse(JSON.stringify(${JSON.stringify(PRINT_DATA.slots)}));
  await post({slots, state: 'printing', can_print: false});
  assert(text(byTest('busy')).includes('can’t change during a print'), 'busy said: ' + text(byTest('busy')));
  assert(byTest('print').disabled && chip(0).disabled && q('#pd-o-auto_leveling').disabled, 'locked');
  await click(byTest('refresh'));
  assert(sent().some(m => m.refresh), 'refresh asked');
  slots[0] = {...slots[0], usable: false, type: '', family: '', material: ''};
  await post({slots, state: 'idle', can_print: true});
  assert(!byTest('busy'), 'ready again');
  assert(text(q('.pd-issues')).includes('empty or can’t be used'), 'live: slot became unusable');
  assert(byTest('print').disabled && text(q('#pd-why')).includes('usable slot'), 'blocked');
  await click(byTest('settings'));
  assert(sent().some(m => m.open_settings) && text(q('.pd-bar')).includes('Settings are open'), 'settings link');
  await press('Escape'); await settle();
  eq(submits(), [{cancelled: true}], 'cancelled');
`, { boot: PD });

test('print setup: Portuguese, narrow window, no auto feed without an ACE', PD_HELP + `
  await until(() => sent().some(m => m.ready), 'ready posted');
  eq(text(byTest('print')), 'Iniciar impressão', 'pt-BR');
  assert(!q('[data-option="auto_feed"]'), 'no auto feed');
  assert(document.documentElement.scrollWidth <= innerWidth, 'no horizontal scroll at ' + innerWidth + ': ' + document.documentElement.scrollWidth);
  const a = q('[data-option="auto_leveling"]').getBoundingClientRect(), b = q('[data-option="vibration_compensation"]').getBoundingClientRect();
  assert(b.top >= a.bottom - 1, 'one column of options');
`, { boot: {...PD, data: {...PRINT_DATA, auto_feed: null}}, lang: 'pt-BR', pref: 'pt-BR', size: [380, 800] });
// ------------------------------------------------------------------ settings pages (one page per section)
const PAGES = ['conn-h', 'cert-h', 'print-h', 'cam-s-h', 'sm-s-h', 'bridge-h', 'cloud-h', 'needs-h', 'lang-h', 'about-h'];
const PAGES_JS = `
const PAGES = ${JSON.stringify(PAGES)};
const link = id => q('.oui-settings-link[data-section="' + id + '"]');
const shown = () => PAGES.filter(id => q('#' + id) && !q('#' + id).hidden);
const onHeading = id => document.activeElement === q('#' + id + ' .oui-panel-title');
const listShown = () => getComputedStyle(q('.oui-settings-nav')).display !== 'none';
const pageShown = () => getComputedStyle(q('.oui-settings-body')).display !== 'none';
`;
test('settings pages: list beside one page; a page opens with focus on its heading and is remembered', PAGES_JS + `
  await ready(VIEW());
  await tab('settings');
  eq(qa('.oui-settings-link').map(e => e.dataset.section), PAGES, 'one page per section');
  eq(shown(), ['conn-h'], 'only the first page');
  assert(listShown() && pageShown() && !byTest('settings-back').getClientRects().length, 'wide: list and page side by side, no Back');
  await click(link('sm-s-h'));
  eq(shown(), ['sm-s-h'], 'only Spoolman');
  assert(onHeading('sm-s-h'), 'focus on the page heading');
  assert(Object.entries(localStorage).some(([k, v]) => k.startsWith('oui-settings:') && v === 'sm-s-h'), 'last page stored');
  link('sm-s-h').focus(); await press('ArrowDown'); await settle();
  eq([shown(), document.activeElement.dataset.section], [['bridge-h'], 'bridge-h'], 'arrow keys move along the list');
  assert(byTest('save-top'), 'one save bar');
`);
test('settings pages: narrow shows the list, then one page with Back', PAGES_JS + `
  await ready(VIEW());
  await tab('settings');
  assert(listShown() && !pageShown(), 'narrow: the list first');
  await click(link('print-h'));
  assert(!listShown() && pageShown(), 'then the page alone');
  eq(shown(), ['print-h'], 'Print defaults only');
  assert(onHeading('print-h'), 'focus on its heading');
  assert(byTest('settings-back').getClientRects().length, 'Back shown');
  await click(byTest('settings-back'));
  assert(listShown() && !pageShown(), 'Back returns to the list');
  eq(document.activeElement, link('print-h'), 'focus back on the page it came from');
`, { size: [600, 900] });
test('settings pages: the last page opens again; a link opens its own page instead', PAGES_JS + `
  await ready(VIEW());
  await tab('settings');
  eq(shown(), ['lang-h'], 'remembered page');
  await tab('dash');
  await post({type: 'show_tab', tab: 'settings'});
  await until(() => shown()[0] === 'print-h', 'the print dialog link opens Print defaults');
  assert(onHeading('print-h'), 'heading focused');
  eq(text(q('[data-tab="settings"][aria-selected="true"]')) !== '', true, 'Settings tab selected');
`, { lastPage: 'lang-h' });
test('settings pages: Open Settings links open the page they are about', PAGES_JS + `
  await connect();
  await post(CONFIG({settings: {...SETTINGS, spoolman_url: ''}}));
  await post({type: 'status', data: VIEW()});
  await until(() => last('cmd', 'spools'), 'spools asked');
  await fail(last('cmd', 'spools'), 'Spoolman: no address set');
  await tab('stock');
  assert(visible(btn('Open Settings', byTest('spoolman-card'))), 'the link is on the Stock tab');
  await click(btn('Open Settings', byTest('spoolman-card')));
  eq(shown(), ['sm-s-h'], 'Spoolman page');
  assert(onHeading('sm-s-h'), 'heading focused');
`, { lastPage: 'about-h' });
test('settings pages: a page that needs attention is marked in the list', PAGES_JS + `
  await connect();
  await post(CONFIG({certificate: {found: false}}));
  await post({type: 'status', data: VIEW()});
  await tab('settings');
  eq(shown(), ['conn-h'], 'on another page');
  eq(link('cert-h').dataset.state, 'warn', 'certificate page flagged');
  assert(link('cert-h').querySelector('.oui-settings-flag'), 'with the flag icon');
`);
// Kobra: what the shared dashboard scenarios need to know about this page.
const DASH_PLUGIN = `
const STORE = dash => post(CONFIG({settings: {...SETTINGS, dashboard: dash}}));
async function READY(dash) { await connect(); await (dash === undefined ? post(CONFIG()) : STORE(dash)); await post({type: 'status', data: VIEW()}); }
const DEFAULT_IDS = ['job', 'ace', 'controls', 'temps', 'printer', 'camera', 'motion', 'console'];
const DEFAULT_ORDER = ['job', 'controls', 'ace', 'temps', 'camera', 'printer', 'console', 'motion'];
const ALL_IDS = ['job', 'ace', 'temps', 'controls', 'camera', 'motion', 'printer', 'console', 'files'];
const MOVER = 'camera', MOVER_FROM = '10 / span 3 | 5 / span 9', MOVE_COLS = 3, MOVER_TO = '7 / span 3 | 5 / span 9';
const CAM_W = 3, CAM_H = 9, TEMPS = 'temps', CONSOLE_LEAST = 'span 3 | span 4';
const OLD_DEFAULT = [{id: 'job', x: 0, y: 0, w: 12, h: 3}, {id: 'ace', x: 0, y: 3, w: 12, h: 16}, {id: 'controls', x: 0, y: 19, w: 8, h: 6},
  {id: 'camera', x: 8, y: 19, w: 4, h: 6}, {id: 'console', x: 0, y: 25, w: 8, h: 12}, {id: 'motion', x: 8, y: 25, w: 4, h: 6}, {id: 'printer', x: 8, y: 31, w: 4, h: 12}];
const MINE_CAMERA = '9 / span 4 | 20 / span 8';
const TEMPS_COMPACT = () => { const subs = qa('.oui-readout-sub', cell('temps')); return subs.length > 0 && subs.every(e => getComputedStyle(e).display === 'none'); };
`;
const CONSOLE_CHECK = `
  await click(q('input#light'));
  await until(() => text(byTest('console-log')).includes('> set_light on=true'), 'the command is in the console: ' + text(byTest('console-log')));
  await fail(last('cmd', 'set_light'), 'printer said no');
  await until(() => text(byTest('console-log')).includes('printer said no'), 'and its answer');
  assert(q('.kc-log-line.err', byTest('console-log')), 'a failure is marked');
  await post({type: 'status', data: VIEW({state: 'printing'})});
  assert(text(byTest('console-log')).includes('Printer: '), 'what the printer does is logged: ' + text(byTest('console-log')));
`;
const SETTINGS_CHECK = `
  await click(q('[data-settings="temps"]'));
  await click(q('input', q('[data-setting="bed"]', byTest('dash-settings'))));
`;
const SETTINGS_AFTER = `
  assert(q('[data-temp="nozzle"]', cell('temps')) && !q('[data-temp="bed"]', cell('temps')), 'the temperatures widget leaves the bed out');
  eq(itemOf(saved(), 'temps').cfg, {bed: false}, 'its setting is saved');
`;
// ------------------------------------------------------------------ the dashboard as a layout the user arranges (OuiDashboard)
// Real pointer input (Input.dispatchMouseEvent): HTML5 drag and drop never reaches a page in OrcaSlicer on macOS.
const DASH_JS = DASH_PLUGIN + `
const cell = id => q('.oui-dash-cell[data-widget="' + id + '"]');
const frame = id => q('[data-frame="' + id + '"]');
const handle = (id, h) => q('[data-frame="' + id + '"] [data-handle="' + h + '"]');
const place = id => { const c = cell(id); return c ? c.style.gridColumn + ' | ' + c.style.gridRow : null; };
const step = () => (q('.oui-dash-grid').getBoundingClientRect().width + 12) / 12;
const ROW = 44;
const mouseAt = (type, x, y) => cdp({op: 'mouse', type, x, y});
async function grab(el, at) { el.scrollIntoView({block: 'center'}); await settle(); const r = el.getBoundingClientRect(); const p = at ? at(r) : [r.left + r.width / 2, r.top + r.height / 2]; await mouseAt('mousePressed', ...p); return p; }
async function dragBy(el, dx, dy, opts = {}) {
  const [x, y] = await grab(el, opts.at);
  for (let i = 1; i <= 5; i++) await mouseAt('mouseMoved', x + dx * i / 5, y + dy * i / 5);
  if (opts.during) await opts.during();
  await mouseAt('mouseReleased', x + dx, y + dy);
}
const saved = () => last('dashboard') && last('dashboard').value;
const itemOf = (st, id) => st.layouts[st.active].items.find(i => i.id === id);
const shown = () => qa('.oui-dash-cell').filter(c => c.getClientRects().length).map(c => c.dataset.widget);
async function edit() { await click(byTest('dash-edit')); assert(q('.oui-dash-board[data-editing]'), 'edit mode on'); }
`;

test('dashboard: the console is a widget of the default layout and there is no Console tab', DASH_JS + `
  await READY();
  assert(!q('[data-tab="console"]'), 'no Console tab');
  assert(cell('console') && cell('console').contains(byTest('console')), 'the console sits in a dashboard cell');
  eq(shown(), DEFAULT_IDS, 'the default layout');
  assert(!q('.oui-dash-frame') && !q('.oui-dash-handle'), 'no frames or handles outside edit mode');
` + CONSOLE_CHECK);

test('dashboard: drag a widget with the pointer; the others make room; Escape puts it back', DASH_JS + `
  await READY();
  await edit();
  eq(place(MOVER), MOVER_FROM, 'starts at its default place');
  const before = JSON.stringify(qa('.oui-dash-cell').map(c => [c.dataset.widget, c.style.gridColumn, c.style.gridRow]));
  await dragBy(frame(MOVER), -MOVE_COLS * step(), 0, { during: async () => { await settle();
    assert(q('.oui-dash-slot'), 'the place it would land is marked');
    assert(cell(MOVER).dataset.dragged !== undefined && cell(MOVER).style.transform.includes('translate'), 'the widget follows the pointer'); } });
  await settle();
  eq(place(MOVER), MOVER_TO, 'dropped where the pointer left it');
  assert(!q('.oui-dash-slot'), 'no marker after the release');
  const cells = qa('.oui-dash-cell').map(c => c.getBoundingClientRect());
  assert(cells.every((a, i) => cells.every((b, j) => i === j || a.right <= b.left + 1 || b.right <= a.left + 1 || a.bottom <= b.top + 1 || b.bottom <= a.top + 1)), 'no widgets overlap');
  // a drag cancelled with Escape changes nothing
  const now = place(MOVER);
  const [x, y] = await grab(frame(MOVER));
  for (let i = 1; i <= 4; i++) await mouseAt('mouseMoved', x + i * step(), y + i * ROW);
  await cdp({op: 'key', key: 'Escape'});
  await mouseAt('mouseReleased', x + 4 * step(), y + 4 * ROW);
  eq(place(MOVER), now, 'Escape cancels the drag');
  eq(last('dashboard'), undefined, 'nothing stored before Save');
  await click(byTest('dash-cancel'));
  eq(JSON.stringify(qa('.oui-dash-cell').map(c => [c.dataset.widget, c.style.gridColumn, c.style.gridRow])), before, 'Cancel drops the edit');
`);

test('dashboard: resize from a corner and from an edge snaps to the grid, keeps a least size and is saved', DASH_JS + `
  await READY();
  await edit();
  await dragBy(handle('camera', 'se'), 2 * step(), 2 * ROW);
  eq(place('camera').replace(/\\d+ \\/ /g, ''), 'span ' + (CAM_W + 2) + ' | span ' + (CAM_H + 2), 'the corner grows width and height by whole cells');
  await dragBy(handle('camera', 's'), 0, -1 * ROW);
  // Rows grow to fit their content, so a row's height in pixels depends on its neighbours: lower, not by exactly one.
  const [cols, rows] = place('camera').replace(/\\d+ \\/ /g, '').split(' | ');
  assert(cols === 'span ' + (CAM_W + 2) && Number(rows.slice(5)) < CAM_H + 2, 'the bottom edge changes the height only: ' + place('camera'));
  await dragBy(handle('camera', 'w'), 2 * step(), 0);
  eq(place('camera').split(' | ')[0].replace(/\\d+ \\/ /, ''), 'span ' + CAM_W, 'the left edge changes the width and the column');
  await dragBy(handle('camera', 'se'), -12 * step(), -12 * ROW);
  eq(place('camera').replace(/\\d+ \\/ /g, ''), 'span 3 | span 4', 'not smaller than the least size of the camera');
  await click(byTest('dash-save'));
  const cam = itemOf(saved(), 'camera');
  eq([cam.w, cam.h], [3, 4], 'the size is saved');
  assert(!q('.oui-dash-board[data-editing]'), 'Save ends edit mode');
  eq(place('camera').replace(/\\d+ \\/ /g, ''), 'span 3 | span 4', 'and stays after it');
`);

test('dashboard: widget content follows its size: the camera keeps its shape, the console shows more lines, temperatures go compact', DASH_JS + `
  await READY();
  const ratio = () => { const r = q('.oui-camera', cell('camera')).getBoundingClientRect(); return r.width / r.height; };
  assert(Math.abs(ratio() - 16 / 9) < 0.05, 'camera 16:9: ' + ratio());
  const logH = () => byTest('console-log').getBoundingClientRect().height;
  const small = logH();
  await edit();
  await dragBy(handle('camera', 'e'), 3 * step(), 0);
  await dragBy(handle('console', 's'), 0, 4 * ROW);
  if (!cell(TEMPS)) { await click(byTest('dash-add')); await click(q('[data-add="' + TEMPS + '"]')); }
  await dragBy(handle(TEMPS, 'e'), -12 * step(), 0);
  await dragBy(handle(TEMPS, 's'), 0, -12 * ROW);
  await click(byTest('dash-save'));
  assert(Math.abs(ratio() - 16 / 9) < 0.05, 'camera still 16:9 when wider: ' + ratio());
  assert(logH() > small + 3 * ROW, 'a taller console has a taller log: ' + small + ' -> ' + logH());
  assert(TEMPS_COMPACT(), 'a small temperatures widget is compact');
  await edit();
  await click(q('[data-settings="camera"]'));
  await pick(q('[data-setting="aspect"]', byTest('dash-settings')), '4:3');
  await click(byTest('dash-save'));
  eq(itemOf(saved(), 'camera').cfg, {aspect: '4/3'}, 'the setting is saved');
  assert(Math.abs(ratio() - 4 / 3) < 0.05, 'camera 4:3: ' + ratio());
`);

test('dashboard: keyboard moves, resizes and removes; the catalogue adds; settings apply', DASH_JS + `
  await READY();
  await edit();
  await click(byTest('dash-add'));
  const cat = byTest('dash-catalogue');
  eq(qa('[data-widget]', cat).map(e => e.dataset.widget), ALL_IDS, 'every widget is in the catalogue');
  assert(!q('[data-add="console"]', cat) && q('[data-add="files"]', cat), 'widgets on the layout are marked, the others can be added');
  await click(q('[data-add="files"]', cat));
  assert(cell('files') && frame('files'), 'added');
  frame('files').focus();
  const at = () => cell('files').style.gridColumn;
  const was = at();
  await cdp({op: 'key', key: 'ArrowRight'}); await cdp({op: 'key', key: 'ArrowRight'});
  assert(at() !== was, 'arrows move it: ' + was + ' -> ' + at());
  eq(document.activeElement, frame('files'), 'focus stays on the widget');
  const w = () => Number(/span (\\d+)/.exec(cell('files').style.gridColumn)[1]);
  const w0 = w();
  await cdp({op: 'key', key: 'ArrowLeft', shift: true});
  eq(w(), w0 - 1, 'Shift and an arrow resize');
  assert(text(q('.oui-dash-board > .oui-sr')).includes('column'), 'the new place is said');
  await cdp({op: 'key', key: 'Delete'});
  assert(!cell('files'), 'Delete removes it');
  await click(q('[data-remove="console"]'));
  assert(!cell('console'), 'Remove takes a widget off');
  assert(byTest('dash-catalogue'), 'the catalogue stays open');
  await click(q('[data-add="console"]'));
  await click(q('[data-settings="console"]'));
  await pick(q('[data-setting="lines"]', byTest('dash-settings')), '100');
` + SETTINGS_CHECK + `
  await click(byTest('dash-save'));
  eq(itemOf(saved(), 'console').cfg.lines, 100, 'console keeps 100 lines');
  assert(!itemOf(saved(), 'files'), 'the removed widget is not saved');
` + SETTINGS_AFTER);

test('dashboard: named layouts are created, switched, renamed, reset and deleted, and come back after a reload', DASH_JS + `
  await READY();
  await edit();
  await click(byTest('dash-new'));
  await type(q('#oui-dash-name'), 'default');
  await click(byTest('dash-name-ok'));
  assert(text(byTest('dash-strip')).includes('Another layout has this name'), 'a name in use is refused');
  await type(q('#oui-dash-name'), 'Watch');
  await click(byTest('dash-name-ok'));
  eq(saved().layouts.map(l => l.name), ['Default', 'Watch'], 'created');
  eq(saved().active, 1, 'and opened');
  await click(q('[data-remove="console"]'));
  await click(q('[data-remove="' + MOVER + '"]'));
  await click(byTest('dash-save'));
  eq(shown().includes('console'), false, 'Watch has no console');
  await pick(byTest('dash-layout'), 'Default');
  eq(saved().active, 0, 'switching is stored');
  assert(cell('console'), 'Default still has its console');
  await pick(byTest('dash-layout'), 'Watch');
  await edit();
  await click(byTest('dash-rename'));
  await type(q('#oui-dash-name'), 'Camera view');
  await press('Enter');
  eq(saved().layouts.map(l => l.name), ['Default', 'Camera view'], 'renamed');
  await click(byTest('dash-reset'));
  eq(shown(), DEFAULT_IDS, 'reset brings the default widgets back');
  await click(byTest('dash-cancel'));
  eq(shown().includes('console'), false, 'a reset is kept only by Save');
  await edit();
  await click(byTest('dash-delete'));
  await click(byTest('dash-delete-ok'));
  eq(saved().layouts.map(l => l.name), ['Default'], 'deleted');
  assert(!byTest('dash-delete') || byTest('dash-delete').disabled, 'the last layout cannot be deleted');
  await click(byTest('dash-cancel'));
  // a second layout to bring back after the reload
  await edit();
  await click(byTest('dash-new'));
  await type(q('#oui-dash-name'), 'Night');
  await press('Enter');
  await click(q('[data-remove="camera"]'));
  await click(byTest('dash-save'));
  return { carry: saved() };
`, { after: DASH_JS + `
  await READY(CARRY);
  eq(q('.oui-dash-pick .p-select-label') && text(q('.oui-dash-pick .p-select-label')), 'Night', 'the open layout is the one saved');
  assert(!cell('camera') && cell('console'), 'its widgets as saved');
  await pick(byTest('dash-layout'), 'Default');
  assert(cell('camera'), 'the other layout is there too');
` });

test('dashboard: a stored layout is checked: unknown widgets dropped, sizes brought within limits, broken data gives the default', DASH_JS + `
  await READY({v: 1, active: 0, layouts: [{name: 'Mine', items: [{id: 'ghost', x: 0, y: 0, w: 4, h: 4}, {id: 'camera', x: 9, y: 3, w: 99, h: 1}, {id: 'console', x: 0, y: 0, w: 2, h: 2, cfg: {lines: 7}}]}]});
  eq(shown().sort(), ['camera', 'console'], 'the unknown widget is dropped');
  eq(place('camera').replace(/\\d+ \\/ /g, ''), 'span 12 | span 4', 'too wide and too short: brought within limits');
  eq(place('console').replace(/\\d+ \\/ /g, ''), CONSOLE_LEAST, 'the least size of the console');
  await STORE('not a dashboard');
  eq(shown(), DEFAULT_IDS, 'broken data: the default layout');
`);

test('dashboard: a widget is maximised and restored', DASH_JS + `
  await READY();
  await click(q('[data-test="widget-max"]', cell('console')));
  eq(shown(), ['console'], 'only the console');
  assert(cell('console').getBoundingClientRect().height > 400, 'as tall as the window allows');
  await cdp({op: 'key', key: 'Escape'});
  eq(shown(), DEFAULT_IDS, 'Escape restores the dashboard');
`);

test('dashboard: a narrow window shows one column in reading order and is not edited', DASH_JS + `
  await READY();
  assert(q('.oui-dash-grid[data-narrow]'), 'one column');
  const tops = DEFAULT_ORDER.map(id => cell(id).getBoundingClientRect().top);
  assert(tops.every((t, i) => !i || t > tops[i - 1]), 'in reading order: ' + tops.join());
  assert(byTest('dash-edit').disabled, 'Edit layout is off');
`, { size: [480, 900] });


test('dashboard: a layout still as the first default gets the new one; an arranged one stays; Reset gives the new one', DASH_JS + `
  await READY({v: 1, active: 0, layouts: [{name: 'Default', items: OLD_DEFAULT}, {name: 'Mine', items: OLD_DEFAULT.map(i => i.id === 'camera' ? {...i, h: i.h + 2} : i)}]});
  eq(shown(), DEFAULT_IDS, 'the untouched default shows the new default');
  eq(place(MOVER), MOVER_FROM, 'at its new place');
  await pick(byTest('dash-layout'), 'Mine');
  eq(place('camera'), MINE_CAMERA, 'the arranged layout is as it was saved');
  await edit();
  await click(byTest('dash-reset'));
  await click(byTest('dash-save'));
  eq(saved().layouts[1].items.map(i => i.id), DEFAULT_IDS, 'Reset to default gives the new default');
  eq(place(MOVER), MOVER_FROM, 'with its places');
`);
for (const size of [[1280, 800], [1920, 1080]]) test(`dashboard: at ${size.join('x')} no widget of the default layout clips or scrolls inside`, DASH_JS + `
  await READY();
  const bad = qa('.oui-dash-cell').map(c => [c.dataset.widget, q('.oui-panel-body', c)]).filter(([, b]) => b && (b.scrollHeight > b.clientHeight + 1 || b.scrollWidth > b.clientWidth + 1))
    .map(([id, b]) => id + ' ' + b.scrollHeight + '/' + b.clientHeight);
  eq(bad, [], 'every widget fits');
`, { size });


test('dashboard: a stored size too small for its content shows all of it and is kept as stored', DASH_JS + `
  await READY({v: 1, active: 0, layouts: [{name: 'Tiny', items: [{id: 'job', x: 0, y: 0, w: 6, h: 2}, {id: 'console', x: 0, y: 2, w: 12, h: 6}]}]});
  const body = q('.oui-panel-body', cell('job'));
  assert(body.scrollHeight <= body.clientHeight + 1 && cell('job').getBoundingClientRect().height > 76, 'its rows grew to the content: ' + cell('job').getBoundingClientRect().height);
  eq(place('job'), '1 / span 6 | 1 / span 2', 'its stored size is not changed');
  eq(last('dashboard'), undefined, 'nothing is saved');
`);

// ------------------------------------------------------------------ runner
const workers = Number(process.env.WORKERS ?? 4);
if (!Number.isSafeInteger(workers) || workers < 1) throw new Error('WORKERS must be a positive integer');
const filter = process.argv[2];
const chosen = scenarios.filter(s => !filter || s.name.includes(filter));
const page = await pageWithIcons();
const dir = await mkdtemp(join(tmpdir(), 'kobra-page-'));
const browser = await launch();
let failed = 0;
const results = [];
try {
  await Promise.all(Array.from({ length: Math.min(workers, chosen.length) }, async (_, worker) => {
    for (let k = worker; k < chosen.length; k += workers) {
      const sc = chosen[k];
      const boot = { version: 'test', lang: sc.lang ?? 'en', pref: sc.pref ?? 'auto', ...(sc.boot ?? {}) };
      const file = join(dir, `p${k}.html`);
      await writeFile(file, preparePage(page, boot));
      const p = await browser.newPage();
      const started = Date.now();
      try {
        await p.size(...(sc.size ?? [1280, 900]));
        // seed: the settings page remembered from an earlier visit (OuiSettings' own key: page path and its page ids)
        const seed = sc.lastPage ? `localStorage.setItem('oui-settings:' + location.pathname + ':' + ${JSON.stringify(PAGES.join(','))}, ${JSON.stringify(sc.lastPage)});` : '';
        await p.init(MOCK_HOST + `try { localStorage.clear(); ${seed} } catch {}`);
        await p.goto(pathToFileURL(file).href);
        // A scenario may return { carry }; its `after` runs on the same page loaded again (what the plugin stored, CARRY).
        const body = (code, carry) => `(async () => { ${HELPERS} ${PRELUDE}
          const CARRY = ${JSON.stringify(carry ?? null)};
          await until(() => document.querySelector('#app > *'), 'app mounted');
          const __r = await (async () => { ${code} })();
          await settle();
          return { carry: __r && __r.carry, violations: __t.violations, rejections: __t.rejections, errors: __t.errors };
        })()`;
        let probe = await p.evaluate(body(sc.body));
        if (probe.violations.length || probe.rejections.length || probe.errors.length) throw new Error('page problems: ' + JSON.stringify(probe));
        if (sc.after) {
          await p.goto(pathToFileURL(file).href);
          probe = await p.evaluate(body(sc.after, probe.carry));
          if (probe.violations.length || probe.rejections.length || probe.errors.length) throw new Error('page problems after reload: ' + JSON.stringify(probe));
        }
        results.push({ name: sc.name, ok: true, ms: Date.now() - started });
        console.log(`ok   ${sc.name}`);
      } catch (e) {
        failed++;
        results.push({ name: sc.name, ok: false, error: String(e.message || e) });
        console.log(`FAIL ${sc.name}\n     ${String(e.message || e).split('\n')[0]}`);
      } finally {
        await p.close();
      }
    }
  }));
} finally {
  await browser.close();
  await rm(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}
if (process.env.RESULTS) await writeFile(process.env.RESULTS, JSON.stringify(results, null, 2));
console.log(`${chosen.length - failed}/${chosen.length} page scenarios passed`);
if (failed || !chosen.length) process.exit(1);
console.log('PASS');
