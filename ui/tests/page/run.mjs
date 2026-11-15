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
const CERT = {found: true, source: 'Anycubic Slicer Next'};
const SETTINGS = {host: '', printer_name: 'Bench Kobra', ui_language: 'auto', ffmpeg_path: '', camera_enabled: false, auto_leveling: true, vibration_compensation: true,
  spoolman_url: 'http://box:7912', spoolman_auto: true, spoolman_report_usage: true, spooler_hint_dismissed: false};
const CONFIG = extra => ({type: 'config', settings: SETTINGS, certificate: CERT, spooler: {installed: true, url: 'https://example.org/spooler', dismissed: false}, version: '0.1.0',
  limits: {nozzle_max: 300, bed_max: 100}, ...extra});
async function connect(gen) {
  await until(() => last('hello'), 'hello sent');
  await reply(last('hello'), {address: '192.168.1.50', printer: 'Bench Kobra', generation: gen || 1});
}
async function ready(view, gen) { await connect(gen); await post(CONFIG()); await post({type: 'status', data: view || VIEW()}); }
async function tab(name) { await click(q('[data-tab="' + name + '"]')); }
async function pick(root, label) {
  assert(root, 'select to open'); root.click(); await until(() => q('.p-select-overlay') && !q('.p-select-overlay[class*="enter-active"]'), 'select overlay open');
  // the overlay is positioned when the option stops moving (a filtered list shifts while it focuses its search field)
  const first = qa('.p-select-overlay [role=option]')[0];
  let at = '', steady = 0;
  await until(() => { const r = first.getBoundingClientRect(), now = r.top + ':' + r.left; steady = now === at ? steady + 1 : 0; at = now; return steady >= 5; }, 'overlay in place');
  const opt = qa('.p-select-overlay [role=option]').find(o => text(o) === label);
  assert(opt, 'option ' + label + ' in ' + qa('.p-select-overlay [role=option]').map(text).join('|'));
  opt.click(); await settle(); await until(() => !q('.p-select-overlay'), 'overlay closed'); await settle();
}
const alerts = () => qa('[role=alert] .p-message').map(text).join(' | ');
const statusText = () => text(q('[data-test="state"]'));
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
  await click(q('[data-file="benchy.gcode"] [data-print]'));
  await reply(last('cmd', 'file_details'), details);
  await until(() => q('.fv-thumb'), 'file details shown');
}
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
  assert(text(q('.kc-addr')).includes('Bench Kobra') && text(q('.kc-addr')).includes('192.168.1.50'), 'printer and address shown');
  await post({type: 'status', data: VIEW({updated_at: 0, nozzle_temp: 0, bed_temp: 0, nozzle_target: 0, bed_target: 0, fan_pct: 0})});
  assert(text(q('[data-heater-row="nozzle"] .st-read')).includes('—'), 'no report yet: nozzle is a dash, not 0: ' + text(q('[data-heater-row="nozzle"] .st-read')));
  await post({type: 'status', data: PRINTING()});
  eq(statusText(), 'Printing', 'state');
  assert(text(q('.st-file')).includes('benchy.gcode') && text(q('.st-file')).includes('37%'), 'file and progress');
  assert(text(q('#status-h').parentElement).includes('Layer 142 / 380'), 'layers');
  assert(text(q('.st-kv')).includes('1 h 8 min') && text(q('.st-kv')).includes('1 h 56 min'), 'elapsed and remaining: ' + text(q('.st-kv')));
  assert(text(q('[data-heater-row="nozzle"] .st-read')).includes('219.6') && text(q('[data-heater-row="bed"] .st-read')).includes('59.8'), 'temperatures');
  eq(q('.p-progressbar').getAttribute('aria-valuenow'), '37', 'progress bar');
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

test('buttons follow status.can and a disabled action says why', `
  await ready(VIEW());
  for (const k of ['pause', 'resume', 'stop']) assert(q('[data-test="' + k + '"]').disabled, k + ' disabled when idle');
  assert(text(byTest('print-why')).includes('No print is running'), 'says why: ' + text(byTest('print-why')));
  await post({type: 'status', data: PRINTING()});
  assert(!q('[data-test="pause"]').disabled && q('[data-test="resume"]').disabled && !q('[data-test="stop"]').disabled, 'printing: pause and stop');
  await post({type: 'status', data: PRINTING({state: 'paused', can: {pause: false, resume: true, stop: true, move: true, heat: true, feed: true, print: false}})});
  assert(q('[data-test="pause"]').disabled && !q('[data-test="resume"]').disabled, 'paused: resume');
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
  await click(btn('Dismiss', q('[role=alert]')));
  assert(!alerts(), 'dismissed by the user');
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
  await until(() => text(q('.notices')).includes('Stop sent'), 'result shown');
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
  assert(text(q('#temp-why-nozzle')).includes('doesn’t allow heating'), 'says why: ' + text(q('#temp-why-nozzle')));
`);

test('confirmed:false shows "sent, waiting"; confirmed:true shows success; a second home while one runs shows the error', `
  await ready(PRINTING());
  await click(q('[data-test="pause"]'));
  await reply(last('cmd', 'pause'), {confirmed: false});
  assert(text(q('.notices')).includes('Pause sent; waiting for the printer'), 'waiting text: ' + text(q('.notices')));
  assert(!qa('.p-message-success').length, 'not shown as success');
  await post({type: 'status', data: PRINTING({state: 'paused', can: {pause: false, resume: true, stop: true, move: true, heat: true, feed: true, print: false}})});
  await click(q('[data-test="resume"]'));
  await reply(last('cmd', 'resume'), {confirmed: true});
  assert(text(q('.notices')).includes('Resume sent.') && qa('.p-message-success').length === 1, 'confirmed: plain success: ' + text(q('.notices')));
  await click(q('[data-move="x+"]'));
  await reply(last('cmd', 'move'), {confirmed: false});
  assert(text(q('.notices')).includes('Move sent; waiting'), 'move waits');
  await click(q('[data-home="z"]')); await yes();
  await reply(last('cmd', 'home'), {confirmed: false});
  assert(text(q('.notices')).includes('Home sent; waiting'), 'home waits');
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
  assert(text(byTest('move-why')).includes('idle or paused'), 'says why: ' + text(byTest('move-why')));
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
  assert(byTest('skip-open').disabled, 'disabled when idle, with the reason');
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
  await click(btn('Apply', q('.st-line')));
  eq(cmds('set_speed').map(m => m.args), [{mode: 3}], 'speed mode number');
  await post({type: 'status', data: VIEW()});
  assert(text(q('.st-line .kc-why')).includes('No print is running'), 'speed needs a print, and says so');
`);

// ------------------------------------------------------------------ ACE
test('ACE card: units, slots, loaded slot, empty slot, activity', `
  await ready(VIEW());
  assert(text(byTest('ace-mode')).includes('Print head and ACE together'), 'mode: ' + text(byTest('ace-mode')));
  eq(qa('.ace-g').map(text), ['Print head', 'ACE 1'], 'groups');
  eq(qa('[data-slot]').length, 7, 'one tile per slot');
  assert(text(q('[data-slot="3"]')).includes('Loaded in the print head') && text(q('[data-slot="3"]')).includes('Slot 1'), 'loaded slot: ' + text(q('[data-slot="3"]')));
  assert(text(q('[data-slot="1"]')).includes('Empty'), 'empty slot');
  assert(text(q('[data-slot="6"]')).includes('Loading'), 'activity: ' + text(q('[data-slot="6"]')));
  assert(text(q('[data-slot="4"]')).includes('ABS'), 'material');
  assert(q('[data-feed="1"]').disabled && text(q('[data-slot="1"]')).includes('No filament in this slot'), 'feed refused on an empty slot, with the reason');
  assert(!/toolhead|\\bT[1-4]\\b/i.test(text(byTest('ace-card'))), 'no U1 wording');
`);

test('slot reports: brand, material name, percent and weight from the printer; box humidity when not drying', `
  await ready(VIEW({slots: SLOTS().map(s => (s.global_index === 4 ? {...s, brand: 'Acme', material_name: 'ABS Pro', percent: 40, weight: 400} : s)),
    ace_units: [{id: 0, auto_feed: false, humidity: 32, temp: 45, drying: DRY0}]}));
  const t = text(q('[data-slot="4"]'));
  assert(t.includes('Acme ABS Pro') && t.includes('40%') && t.includes('400 g'), 'slot details: ' + t);
  assert(text(byTest('unit-humidity')).includes('32'), 'box humidity: ' + text(q('[data-unit="0"]')));
  await post({type: 'status', data: VIEW({ace_units: [{id: 0, auto_feed: true, humidity: 30, temp: 44, drying: {status: 1, target_temp: 50, duration: 86400, remain_time: 901, humidity: null, current_temp: null}}]})});
  const d = text(byTest('drying'));
  assert(d.includes('15 h 1 min left') && d.includes('Humidity 30 %') && d.includes('44'), 'drying uses box readings and remain_time minutes: ' + d);
  assert(!d.includes('86400') && !d.includes('24 h'), 'the constant duration is never shown');
`);

test('toolhead-only printer: only the print head group, no unit controls', `
  await ready(VIEW({mode: 'toolhead', slots: SLOTS().slice(0, 3), ace_units: [], loaded_slot: 0}));
  eq(qa('.ace-g').map(text), ['Print head'], 'one group');
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
  await click(q('[data-retract="4"]')); await yes();
  eq(cmds('slot_retract').map(m => m.args), [{slot: 4}], 'retract');
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
  assert(text(byTest('spool-source')).includes('2 spools'), 'source line: ' + text(byTest('spool-source')));
  eq(qa('[data-pick]').length, 7, 'one picker per slot');
  await pick(q('[data-pick="4"]'), '#11 Acme White · PETG · 40 g');
  assert(dialogOpen() && dialogText().includes('#11'), 'bind asks: ' + dialogText()); await yes();
  eq(cmds('bind').map(m => m.args), [{slot: 4, spool_id: 11}], 'bind');
  await reply(last('cmd', 'bind'), {});
  await pick(q('[data-pick="3"]'), 'No spool (unlink)');
  assert(dialogOpen(), 'unbind asks'); await yes();
  eq(cmds('unbind').map(m => m.args), [{slot: 3}], 'unbind');
`);

test('Spoolman without an address says where to set it', `
  await connect();
  await post(CONFIG({settings: {...SETTINGS, spoolman_url: ''}}));
  await post({type: 'status', data: VIEW()});
  await until(() => last('cmd', 'spools'), 'spools asked');
  await fail(last('cmd', 'spools'), 'Spoolman: no address set: enter one under Settings, or use Spooler with Spoolman');
  eq(text(byTest('spool-source')), 'No Spoolman address', 'one short line, not the error three times');
  assert(text(byTest('spoolman-card')).includes('Set a Spoolman address under Settings') && btn('Open Settings', byTest('spoolman-card')), 'where to set it');
`);

test('Spoolman: the address Spooler uses is taken when none is set here, and Settings says so', `
  await connect();
  await post(CONFIG({settings: {...SETTINGS, spoolman_url: ''}, located: {address: '10.0.0.5', source: 'discovered', preset_host: '', preset_agent: '',
    spoolman_url: 'http://box:7912', spoolman_source: 'spooler'}}));
  await post({type: 'status', data: VIEW()});
  await reply(last('cmd', 'spools'), {spools: ROWS, bindings: {}});
  eq(text(byTest('spool-source')), '2 spools in Spoolman', 'the slot pickers work from the Spoolman of Spooler');
  assert(!text(byTest('spoolman-card')).includes('Set a Spoolman address'), 'no contradiction with the Stock card');
  await tab('settings');
  assert(text(byTest('sm-from')).includes('Spooler’s Spoolman is used: http://box:7912'), 'source: ' + text(byTest('sm-from')));
`);

test('stock card: link a spool to a slot', `
  await ready(VIEW());
  await reply(last('cmd', 'stock'), STOCK());
  await reply(last('cmd', 'spools'), {spools: ROWS, bindings: {}});
  await until(() => byTest('stock-card'), 'stock card');
  eq(qa('[data-stock]').length, 2, 'two spools listed');
  await pick(byTest('stock-slot'), 'ACE 1 · Slot 2');
  await click(q('[data-stock="11"]'));
  assert(dialogOpen() && dialogText().includes('ACE 1 · Slot 2') && dialogText().includes('#11'), 'asks: ' + dialogText()); await no();
  eq(cmds('stock_assign'), [], 'cancel links nothing');
  await click(q('[data-stock="11"]')); await yes();
  eq(cmds('stock_assign').map(m => m.args), [{slot: 4, spool_id: 11, key: 's1:3'}], 'stock_assign');
`);

test('stock card: rows say which slot holds them (bound_slot)', `
  await ready(VIEW());
  await reply(last('cmd', 'stock'), STOCK({stock: {...STOCK().stock, rows: [{...ROWS[0], bound_slot: 3}, {...ROWS[1], bound_slot: null}]}}));
  await until(() => byTest('stock-card'), 'stock card');
  assert(text(q('[data-stock="7"]').closest('tr')).includes('on ACE 1 · Slot 1'), 'chip: ' + text(q('[data-stock="7"]').closest('tr')));
  assert(!text(q('[data-stock="11"]').closest('tr')).includes(' on '), 'unbound row has no chip');
`);

test('stock card shows only for a usable list; the lease flag follows; Settings says what is missing', `
  await ready(VIEW());
  await reply(last('cmd', 'stock'), STOCK());
  await until(() => byTest('stock-card'), 'usable list: card');
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
    assert(!byTest('stock-card'), what + ': no card at all');
    assert(!qa('.kc-card').some(c => /stock/i.test(text(c.querySelector('h2')))), what + ': no stock heading');
  }
  await until(() => last('lease').stock === false, 'lease: stock off when there is no usable list (renewed every 2 s)');
  await tab('settings');
  assert(text(byTest('spooler-no-stock')).includes('needs a Spooler version that supports Kobra Control'), 'Settings says why: ' + text(q('.sv')));
`);

// ------------------------------------------------------------------ filament use
test('filament use: nothing pending shows no card, and the page asked for it', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'), 'usage asked');
  eq(last('cmd', 'usage').args, {}, 'no arguments');
  await reply(last('cmd', 'usage'), USAGE());
  assert(!byTest('usage-card'), 'no empty card');
  await post({type: 'status', data: VIEW()});
  assert(!byTest('usage-card'), 'still none');
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
  assert(!card.classList.contains('warn'), 'not a warning');
`);

test('filament use: a failed booking lists its identity and reason; marking it checked is local and asks first', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'));
  await reply(last('cmd', 'usage'), USAGE({unconfirmed: [ENTRY], restore_notice: '2 unreadable unconfirmed entries were skipped'}));
  const card = byTest('usage-card');
  assert(card, 'card shown');
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
  assert(!byTest('usage-card'), 'nothing left to show once checked: no empty card');
`);

test('filament use: a failed acknowledgement keeps the entry and says why', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'));
  await reply(last('cmd', 'usage'), USAGE({unconfirmed: [{...ENTRY, spool: null, at: 1794300000}]}));
  assert(text(byTest('usage-card')).includes('none linked'), 'unlinked spool said, not hidden');
  await click(btn('Mark the use on ACE 1 · Slot 2 of benchy.gcode as checked')); await yes();
  await fail(last('cmd', 'usage_ack'), "can't save the print ledger (disk full)");
  assert(alerts().includes('disk full') && text(byTest('usage-card')).includes('benchy.gcode'), 'entry kept, error shown: ' + alerts());
`);

test('filament use: the error path of usage is shown with the reason; a ledger that cannot be saved too', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'));
  await fail(last('cmd', 'usage'), 'ledger unreadable');
  assert(byTest('usage-card') && text(byTest('usage-card')).includes('Couldn’t read the filament-use ledger: ledger unreadable'), 'load error shown: ' + text(q('.kc-main')));
  const n = cmds('usage').length;
  await until(() => cmds('usage').length > n, 'asked again later', 20000);   // every 10 s while the Dashboard is on screen
  await reply(last('cmd', 'usage'), USAGE({save_error: 'disk full'}));
  assert(text(byTest('usage-card')).includes('The ledger can’t be saved: disk full') && !text(byTest('usage-card')).includes('Couldn’t read'), 'recovers, and shows the save error');
`);

test('filament use: pt-BR', `
  await ready(VIEW());
  await until(() => last('cmd', 'usage'));
  await reply(last('cmd', 'usage'), USAGE({unconfirmed: [ENTRY]}));
  const t = text(byTest('usage-card'));
  assert(t.includes('Consumo de filamento no Spoolman') && t.includes('1 consumo não confirmado') && t.includes('Já conferi no Spoolman'), 'Portuguese: ' + t);
`, { lang: 'pt-BR' });

// ------------------------------------------------------------------ camera
test('camera: off by default and compact; frames are acknowledged; leases follow it', `
  await ready(VIEW());
  assert(q('.cam-card').classList.contains('compact') && !q('.cam-view'), 'compact while off');
  assert(last('lease').camera === false, 'lease: camera off');
  await click(byTest('camera'));
  assert(last('lease').camera === true, 'lease: camera on');
  await post({type: 'frame', image: PNG});
  await until(() => q('.cam-view img'), 'frame shown');
  await until(() => last('frame_ack'), 'frame acknowledged');
  await tab('settings');
  await until(() => last('lease').camera === false, 'lease drops when the Dashboard is not on screen (the lease is renewed every 2 s)');
`);

test('camera errors: a plain explanation per reason', `
  await ready(VIEW());
  await click(byTest('camera'));
  await post({type: 'camera_error', error: 'ffmpeg not found', reason: 'no_ffmpeg'});
  assert(text(q('.cam-empty')).includes('ffmpeg is not installed') && text(q('.cam-empty')).includes('Settings > Camera'), 'no_ffmpeg: ' + text(q('.cam-empty')));
  await click(byTest('cam-settings'));
  assert(q('#c-ffmpeg'), 'the button leads to the ffmpeg path field');
  await tab('dash');
  await post({type: 'camera_error', error: 'no rtsp', reason: 'no_stream'});
  assert(text(q('.cam-empty')).includes('isn’t sending a camera stream'), 'no_stream: ' + text(q('.cam-empty')));
  assert(!byTest('cam-settings'), 'no ffmpeg button for another reason');
  await post({type: 'camera_error', error: 'exit 1', reason: 'failed'});
  assert(text(q('.cam-empty')).includes('The camera stopped: exit 1'), 'failed: ' + text(q('.cam-empty')));
  await post({type: 'frame', image: PNG});
  await until(() => q('.cam-view img'), 'recovers when frames come back');
`);

test('the camera starts on only when the saved setting says so', `
  await connect();
  await post(CONFIG({settings: {...SETTINGS, camera_enabled: true}}));
  await post({type: 'status', data: VIEW()});
  assert(q('.cam-view') && last('lease').camera === true, 'camera on from the setting');
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
  assert(text(q('.notices')).includes('Certificate found'), 'success shown');
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
  assert(q('#c-host'), 'goes to the address field');
  await tab('files');
  assert(text(byTest('files-why')).includes('No Kobra X found yet'), 'Files says what is missing');
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
  assert(q('[data-test="pause"]').disabled && text(byTest('controls-why')).includes('doesn’t answer'), 'controls off, with the reason');
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
  await post({type: 'offline', error: 'Something answers at 10.25.16.41, but it is not a Kobra X in LAN mode', retry_at: Date.now() / 1000 + 32});
  eq(text(byTest('link')), 'Offline', 'badge');
  const banner = text(byTest('target-banner'));
  assert(banner.includes('unreachable') && banner.includes('not a Kobra X in LAN mode') && !banner.includes('Connecting'), 'banner: ' + banner);
  // Derived from retry_at and the time the message was posted, not a fixed window: the page's 1 s clock may lag.
  const n = +(/tries again by itself in ([0-9]+) s/.exec(text(byTest('retry-in'))) || [])[1];
  assert(n >= 1 && n <= 32, 'next try within retry_at: ' + text(byTest('retry-in')));
  eq(text(byTest('state')), 'Offline', 'Status card');
  assert(text(byTest('cam-why')).includes('doesn’t answer'), 'camera gives the same reason: ' + text(byTest('cam-why')));
  assert(!text(document.body).includes('Select a printer first'), 'no "no printer" text while one is selected');
  const card = q('[aria-labelledby="status-h"]');
  const live = qa('button, input, [role="checkbox"]', card).filter(el => !el.disabled && !el.closest('[data-p-disabled="true"]') && el.getAttribute('aria-disabled') !== 'true'
    && !el.closest('.p-disabled') && !el.closest('details:not([open])'));
  eq(live.map(el => (el.textContent || el.getAttribute('aria-label') || el.outerHTML).trim().slice(0, 60)), [], 'every printer control is off');
  for (const b of qa('button.p-button', card)) {
    const st = getComputedStyle(b);
    assert(parseFloat(st.opacity) <= 0.7 || st.cursor === 'not-allowed', 'looks disabled: ' + text(b) + ' opacity ' + st.opacity);
  }
`);

test('a found printer OrcaSlicer must allow first: the page asks once, then connects', `
  await until(() => last('hello'));
  await fail(last('hello'), 'Found a printer at 10.25.7.41. Allow Kobra Control to reach it in OrcaSlicer’s dialog; it connects by itself afterwards.',
    {no_target: true, candidates: [], pending: ['10.25.7.41']});
  await until(() => last('allow_hosts'), 'asks the plugin to show the dialog');
  eq(last('allow_hosts').hosts, ['10.25.7.41'], 'that address');
  eq(last('allow_hosts').user, false, 'asked by the page itself');
  assert(text(byTest('first-run-target')).includes('connects by itself'), 'says what to do: ' + text(byTest('first-run-target')));
  await reply(last('allow_hosts'), {allowed: ['10.25.7.41'], refused: []});
  await until(() => sent().filter(m => m.type === 'hello').length === 2, 'connects without another click');
  await fail(last('hello'), 'Found a printer at 10.25.7.41.', {no_target: true, pending: ['10.25.7.41']});
  await settle();
  eq(sent().filter(m => m.type === 'allow_hosts').length, 1, 'never asks twice for the same address in a loop');
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

test('first run: several printers found, pick one', `
  await until(() => last('hello'));
  await fail(last('hello'), '2 Kobra X printers answer on this network: choose one.', {no_target: true,
    candidates: [{ip: '10.0.0.2', name: 'Left KX', model: 'Anycubic Kobra X'}, {ip: '10.0.0.3', name: 'Right KX', model: 'Anycubic Kobra X'}]});
  const box = byTest('first-run-target');
  assert(text(box).includes('Several Kobra X found') && text(box).includes('Right KX') && text(box).includes('10.0.0.3'), 'picker: ' + text(box));
  await click(q('[data-pick-ip="10.0.0.3"]'));
  eq(cmds('choose_printer').map(m => m.args), [{host: '10.0.0.3'}], 'choice sent');
  await reply(last('cmd', 'choose_printer'), {address: '10.0.0.3'});
  await until(() => sent().filter(m => m.type === 'hello').length === 2, 'connects to it');
`);

test('settings: the address in use, how it was found, Search again, and the other printer agent', `
  await until(() => last('hello'));
  await post(CONFIG({located: {address: '', source: '', preset_host: '10.25.16.41', preset_agent: 'moonraker', spoolman_url: '', spoolman_source: ''}}));
  await reply(last('hello'), {address: '10.25.7.41', printer: 'Bench Kobra', generation: 1, source: 'discovered',
    note: 'The printer preset points to 10.25.16.41, which is not a Kobra X in LAN mode; found the Kobra X at 10.25.7.41 and using that.'});
  await post({type: 'status', data: VIEW()});
  assert(text(q('.notices')).includes('points to 10.25.16.41'), 'one quiet line: ' + text(q('.notices')));
  assert(text(q('.notices')).includes('“moonraker” printer agent'), 'agent note once: ' + text(q('.notices')));
  await tab('settings');
  eq(text(byTest('in-use')), 'In use: 10.25.7.41 (found on the network).', 'in use');
  assert(text(byTest('other-agent')).includes('Printer Agent > kobracontrol'), 'how to switch: ' + text(byTest('other-agent')));
  await click(byTest('search-again-settings'));
  eq(cmds('search_printer').length, 1, 'search again');
  await type(q('#c-host'), '10.25.7.50');
  assert(byTest('search-again-settings').disabled, 'no search while an address is typed here');
`);

test('stock table: thumbnails stay small and nothing overlaps, with many spools, at wide and narrow widths', `
  const many = Array.from({length: 55}, (_, i) => ({...ROWS[i % 2], id: 100 + i, name: 'Spool ' + i}));
  await ready(VIEW());
  await reply(last('cmd', 'stock'), STOCK({stock: {...STOCK().stock, rows: many}}));
  await until(() => byTest('stock-card'), 'stock card');
  // the owner's web view drew each spool as a tall narrow strip; without aspect-ratio support it must still be a square
  const style = document.createElement('style'); style.textContent = '.sf { aspect-ratio: auto !important; }'; document.head.appendChild(style);
  for (const width of ['', '380px']) {
    q('.kc-shell').style.width = width; q('.kc-shell').style.maxWidth = width || '';
    await settle();
    const wrap = q('[data-test="stock-card"] .sc-wrap');
    for (const fig of qa('.sf', wrap).slice(0, 6)) {
      const r = fig.getBoundingClientRect();
      assert(Math.abs(r.width - 40) < 1 && Math.abs(r.height - 40) < 1, 'thumbnail 40x40 at ' + (width || 'wide') + ', got ' + r.width + 'x' + r.height);
    }
    const rows = qa('tbody tr', wrap).slice(0, 6).map(tr => tr.getBoundingClientRect().height);
    assert(Math.max(...rows) < 90, 'compact rows at ' + (width || 'wide') + ': ' + rows.join(','));
    const box = wrap.getBoundingClientRect(), next = wrap.nextElementSibling || q('[data-test="stock-card"] .sc-tabs');
    assert(box.height <= 361, 'the table scrolls in its own area: ' + box.height);
    assert(!next || next.getBoundingClientRect().top >= box.bottom - 0.5, 'nothing runs onto what follows');
    assert(wrap.scrollHeight > wrap.clientHeight, 'many spools scroll inside');
  }
  style.remove();
`);

test('stale status shows its age', `
  await ready(PRINTING());
  const real = Date.now;
  Date.now = () => real() + 30000;
  await until(() => text(byTest('target-banner')).includes('out of date'), 'stale banner', 15000);
  assert(text(byTest('target-banner')).includes('Last printer status'), 'says the age: ' + text(byTest('target-banner')));
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
test('files: list, details, the two print options, print and cancel', `
  await ready(VIEW({storage: {total: 8000, used: 2000}}));
  await tab('files');
  await until(() => last('cmd', 'files'), 'files asked');
  await reply(last('cmd', 'files'), {files: [{name: 'benchy.gcode', size: 4200000, timestamp: 1700000000}, {name: 'cube.gcode', size: 900000, timestamp: 1699000000}]});
  eq(qa('[data-file]').map(e => e.getAttribute('data-file')), ['benchy.gcode', 'cube.gcode'], 'rows');
  assert(text(byTest('disk')).includes('2 GB') && text(byTest('disk')).includes('8 GB'), 'storage: ' + text(byTest('disk')));
  await click(q('[data-file="benchy.gcode"] [data-print]'));
  eq(cmds('file_details').map(m => m.args), [{name: 'benchy.gcode'}], 'details asked');
  await reply(last('cmd', 'file_details'), {name: 'benchy.gcode', thumbnail: PNG, objects: []});
  await until(() => q('.fv-thumb'), 'thumbnail');
  assert(q('#opt-level input, input#opt-level').checked !== false, 'auto-leveling starts on from the setting');
  await click(q('input#opt-vib'));
  await click(byTest('print-start'));
  assert(dialogOpen() && dialogText().includes('benchy.gcode') && dialogText().includes('Bench Kobra'), 'asks: ' + dialogText());
  await no();
  eq(cmds('file_print'), [], 'cancel prints nothing');
  await click(byTest('print-start')); await yes();
  eq(cmds('file_print').map(m => m.args), [{name: 'benchy.gcode', auto_leveling: true, vibration_compensation: false}], 'file_print with both options');
  await reply(last('cmd', 'file_print'), true);
  await until(() => !byTest('print-panel'), 'panel closes after printing');
`);

test('files: print is refused while the printer cannot start, with the reason', `
  await ready(PRINTING());
  await tab('files');
  await reply(last('cmd', 'files'), {files: [{name: 'a.gcode', size: 1, timestamp: 1700000000}]});
  await click(q('[data-print]'));
  assert(byTest('print-start').disabled, 'start disabled');
  assert(text(byTest('print-panel')).includes('can’t start a print right now'), 'says why: ' + text(byTest('print-panel')));
`);

test('files: delete asks first and refreshes the list', `
  await ready(VIEW());
  await tab('files');
  await reply(last('cmd', 'files'), {files: [{name: 'a.gcode', size: 1, timestamp: 1700000000}]});
  await click(q('[data-delete]'));
  assert(dialogOpen() && dialogText().includes('a.gcode'), 'asks: ' + dialogText()); await no();
  eq(cmds('file_delete'), [], 'cancel deletes nothing');
  await click(q('[data-delete]')); await yes();
  eq(cmds('file_delete').map(m => m.args), [{names: ['a.gcode']}], 'file_delete');
  await reply(last('cmd', 'file_delete'), true);
  await until(() => cmds('files').length === 2, 'list refreshed');
  await reply(last('cmd', 'files'), {files: []});
  assert(text(q('.fv-empty')).includes('No files on the printer'), 'empty state');
`);

test('files: a list error says so and can be retried', `
  await ready(VIEW());
  await tab('files');
  await fail(last('cmd', 'files'), 'printer timed out');
  assert(text(q('.p-message')).includes('printer timed out'), 'error shown');
  await click(btn('Try again', q('.p-message')));
  eq(cmds('files').length, 2, 'retry');
`);

test('files: the print panel shows what the file needs and which slot prints each filament', `
  await openDetails(DETAILS());
  const info = text(byTest('file-info'));
  for (const want of ['7 h 10 min', '1,875', '103 g', '0.16 mm', '205 / 60 °C']) assert(info.includes(want), want + ' in ' + info);
  eq(qa('[data-mat]').length, 2, 'one row per filament');
  assert(text(q('[data-mat="0"]')).includes('Print head · Slot 1') && text(q('[data-mat="0"]')).includes('PETG'), 'slot of filament 1: ' + text(q('[data-mat="0"]')));
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

test('files: search and sort the list', `
  await ready(VIEW());
  await tab('files');
  await reply(last('cmd', 'files'), {files: [{name: 'benchy.gcode', size: 4200000, timestamp: 1700000000}, {name: 'cube.gcode', size: 900000, timestamp: 1699000000},
    {name: 'Arch.gcode', size: 9000000, timestamp: 1698000000}]});
  const names = () => qa('[data-file]').map(e => e.getAttribute('data-file'));
  eq(names(), ['benchy.gcode', 'cube.gcode', 'Arch.gcode'], 'newest first by default');
  await type(byTest('files-q'), 'CU');
  await until(() => names().length === 1, 'filtered');
  eq(names(), ['cube.gcode'], 'search ignores case');
  eq(text(byTest('files-count')), 'Showing 1 of 3 files', 'count');
  await type(byTest('files-q'), 'zzz');
  await until(() => byTest('files-nomatch'), 'no match');
  assert(text(byTest('files-nomatch')).includes('zzz'), 'says what found nothing');
  await type(byTest('files-q'), '');
  await until(() => names().length === 3, 'cleared');
  await pick(byTest('files-sort'), 'Name');
  eq(names(), ['Arch.gcode', 'benchy.gcode', 'cube.gcode'], 'by name');
  await pick(byTest('files-sort'), 'Largest first');
  eq(names(), ['Arch.gcode', 'benchy.gcode', 'cube.gcode'], 'by size');
  await pick(byTest('files-sort'), 'Oldest first');
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

test('pt-BR: the new file, finish-time and certificate texts are translated', `
  const at = Math.floor(Date.now() / 1000);
  await ready(PRINTING({updated_at: at, remaining_s: 7000, tls: {fingerprint: 'ab'.repeat(32), changed_from: 'cd'.repeat(32)}}));
  assert(text(q('.st-kv')).includes('Termina') && byTest('eta'), 'eta: ' + text(q('.st-kv')));
  assert(text(byTest('tls-changed')).includes('certificado da impressora mudou'), 'tls: ' + text(byTest('tls-changed')));
  await post({type: 'status', data: VIEW()});
  await tab('files');
  await reply(last('cmd', 'files'), {files: [{name: 'benchy.gcode', size: 1, timestamp: 1700000000}, {name: 'cube.gcode', size: 1, timestamp: 1}]});
  await type(byTest('files-q'), 'cube');
  await until(() => qa('[data-file]').length === 1, 'filtered');
  eq(text(byTest('files-count')), 'Mostrando 1 de 2 arquivos', 'count');
  await click(q('[data-file="cube.gcode"] [data-print]'));
  await reply(last('cmd', 'file_details'), DETAILS({name: 'cube.gcode'}));
  await until(() => byTest('file-info'), 'details');
  assert(text(byTest('file-info')).includes('Tempo estimado'), 'info: ' + text(byTest('file-info')));
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
    spoolman_url: 'http://box:7912', spoolman_auto: true, spoolman_report_usage: true}, 'every setting, by its name');
  assert(!text(q('.notices')).includes('Settings saved'), 'not saved before the answer');
  await reply(m, {});
  assert(text(q('.notices')).includes('Settings saved'), 'saved after the answer');
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

test('settings: the language choice is posted; the version shows; the Spooler hint is there', `
  await ready(VIEW());
  await tab('settings');
  assert(text(byTest('version')).includes('Kobra Control 0.1.0'), 'version: ' + text(byTest('version')));
  assert(text(q('.sv')).includes('Spooler detected'), 'Spooler hint');
  await pick(byTest('lang'), 'Português (Brasil)');
  eq(last('ui_language').value, 'pt-BR', 'choice posted');
  assert(text(q('[data-tab="dash"]')) === 'Painel', 'page switched to Portuguese: ' + text(q('[data-tab="dash"]')));
`);

// ------------------------------------------------------------------ language, theme, general
test('pt-BR: the page follows the host language and has no leftover English in the main surfaces', `
  await ready(VIEW());
  eq(qa('[data-tab]').map(text), ['Painel', 'Arquivos', 'Ajustes'], 'tabs');
  eq(statusText(), 'Pronta', 'state');
  assert(text(byTest('link')) === 'Conectada', 'pill');
  eq(qa('.ace-g').map(text), ['Cabeça de impressão', 'ACE 1'], 'groups');
  assert(text(q('[data-slot="3"]')).includes('Carregado na cabeça de impressão'), 'slot state: ' + text(q('[data-slot="3"]')));
  assert(text(q('[data-test="pause"]')) === 'Pausar', 'buttons');
  await post({type: 'status', data: PRINTING()});
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
  const bad = /\\bU1\\b|toolhead|Snapmaker|Moonraker|Klipper|extended firmware|purifier|console/i;
  for (const name of ['dash', 'files', 'settings']) {
    await tab(name);
    assert(!bad.test(text(q('.kc-main'))), name + ': ' + (text(q('.kc-main')).match(bad) || [''])[0]);
  }
  assert(!q('[data-tab="console"]'), 'no Console tab');
  assert(!bad.test(text(q('.kc-head'))), 'header');
`);

test('boot and icon blocks are the ones the code reads', `
  assert(document.getElementById('kobra-boot') && document.getElementById('kobra-icons'), 'kobra-boot and kobra-icons exist');
  assert(!document.getElementById('u1-boot') && !document.getElementById('u1-icons'), 'no u1 ids');
  assert(qa('.kc-icon svg').length > 3, 'icons are drawn from the injected map');
`);

test('theme follows the host colour while the page runs', `
  const root = document.documentElement;
  root.style.setProperty('--orca-bg', '#f4f4f4');
  await until(() => !root.classList.contains('orca-dark'), 'light', 15000);
  root.style.setProperty('--orca-bg', '#151515');
  await until(() => root.classList.contains('orca-dark'), 'dark after the host changed', 15000);
  eq(getComputedStyle(document.body).backgroundColor, 'rgb(24, 28, 34)', 'dark palette background');
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
  await tab('files'); assert(q('#files-h'), 'files panel');
  await tab('settings'); assert(q('#conn-h'), 'settings panel');
  await tab('dash'); assert(q('#status-h'), 'dashboard panel');
  assert(last('lease').stock !== undefined, 'lease has the stock flag');
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
      const boot = { version: 'test', lang: sc.lang ?? 'en', pref: sc.pref ?? 'auto' };
      const file = join(dir, `p${k}.html`);
      await writeFile(file, preparePage(page, boot));
      const p = await browser.newPage();
      const started = Date.now();
      try {
        await p.size(1280, 900);
        await p.init(MOCK_HOST + 'try { localStorage.clear(); } catch {}');
        await p.goto(pathToFileURL(file).href);
        const body = `(async () => { ${HELPERS} ${PRELUDE}
          await until(() => document.querySelector('#app > *'), 'app mounted');
          ${sc.body}
          await settle();
          return { violations: __t.violations, rejections: __t.rejections, errors: __t.errors };
        })()`;
        const probe = await p.evaluate(body);
        if (probe.violations.length || probe.rejections.length || probe.errors.length) throw new Error('page problems: ' + JSON.stringify(probe));
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
