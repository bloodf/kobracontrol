<script setup lang="ts">
import { computed, nextTick, ref, watch, type ComponentPublicInstance } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiBanner, OuiEmpty, OuiFileBrowser, OuiHint, OuiIcon, OuiPageHeader, OuiPanel, OuiSwatch, type OuiFileBrowserLabels } from '../../shared/src/components';
import { printer, refresh } from '../../shared/src/icons';
import * as bridge from '../core/bridge';
import { s, run, tracker, targetKnown, printerName, controlsOff, busy, whyId } from '../app/store';
import { config } from '../app/settings';
import { ask } from '../core/dialog';
import { t, tn, fmt } from '../core/i18n';
import { message } from '../core/tracker';
import { clipLength, thumbSrc, listFiles } from '../core/logic';
import type { FileDetails, FileEntry, FileMaterial, FilesResult, VideoEntry, VideosResult } from '../app/types';

// The Files tab, on the shared file browser: what is on the printer, with multi-select and delete, and one file's
// details and print options beside the list.
// What the Kobra X's LAN protocol offers (docs/protocol.md): file/listLocal of the storage's root, file/fileDetails,
// file/deleteBatch (several files in one message), file/listVideo and file/deleteVideo (one video per message). It has
// no folders to work with and no message to move, rename or create one, and no download. So the browser is shown
// without its folder tree and without "Move to"; the printer's two lists (print files, time-lapses) are a switch over
// the table.
type Place = 'local' | 'videos';
/** One array for good: a new one on each render would look like a changed tree to the browser. */
const NO_FOLDERS: never[] = [];
type Load = 'idle' | 'loading' | 'ok' | 'error';
const place = ref<Place>('local');
const selected = ref<string[]>([]);
const state = ref<Record<Place, Load>>({ local: 'idle', videos: 'idle' });
const error = ref<Record<Place, string>>({ local: '', videos: '' });
const set = (which: Place, to: Load, why = '') => { state.value = { ...state.value, [which]: to }; error.value = { ...error.value, [which]: why }; };
const files = ref<FileEntry[]>([]);
const videos = ref<VideoEntry[]>([]);
const seq = { local: 0, videos: 0 };
// Time-lapses are listed for a connected printer (idle or printing).
const hasVideos = computed(() => s.phase === 'connected');

async function loadFiles() {
  if (!targetKnown.value || !s.info) { set('local', 'idle'); files.value = []; return; }
  const mine = ++seq.local;
  set('local', 'loading');
  try {
    const r: FilesResult = await bridge.command('files', {}, s.info.generation);
    if (mine !== seq.local) return;
    files.value = r.files ?? [];
    set('local', 'ok');
  } catch (e) {
    if (mine === seq.local) set('local', 'error', message(e));
  }
}
async function loadVideos() {
  if (!hasVideos.value || !s.info) { set('videos', 'idle'); videos.value = []; return; }
  const mine = ++seq.videos;
  set('videos', 'loading');
  try {
    const r: VideosResult = await bridge.command('videos', {}, s.info.generation);
    if (mine !== seq.videos) return;
    videos.value = r.videos ?? [];
    set('videos', 'ok');
  } catch (e) {
    if (mine === seq.videos) set('videos', 'error', message(e));
  }
}
const load = () => Promise.all([loadFiles(), loadVideos()]);
const reloadOpen = () => (place.value === 'videos' ? loadVideos() : loadFiles());
watch(() => [s.tab, s.epoch, s.phase], () => { if (s.tab === 'files') void load(); else selected.value = []; }, { immediate: true });
watch(hasVideos, on => { if (!on) place.value = 'local'; });
/** The other list: nothing stays selected across the two. */
function openList(to: Place) { if (to !== place.value) { selected.value = []; place.value = to; } }

// Storage comes with the status, in MB.
const storage = computed(() => { const st = s.status?.storage; return st?.total ? { used: (st.used ?? 0) * 1e6, total: st.total * 1e6 } : null; });
const disk = computed(() => (storage.value ? t('files.used', { used: fmt.bytes(storage.value.used), total: fmt.bytes(storage.value.total) }) : ''));
const seconds = (ts: number) => (ts > 1e12 ? ts / 1000 : ts);

// ---------------------------------------------------------------- one file selected: its details and the print options
const one = computed(() => (place.value === 'local' && selected.value.length === 1 ? selected.value[0] : null));
const details = ref<FileDetails | null>(null);
const detailsError = ref('');
const thumbs = ref<Record<string, string>>({});
const options = ref({ leveling: true, vibration: true, flow: false, timelapse: false });
// Flow calibration and time-lapse only where the printer says it has them (info/report features; unknown = offered).
const canFlow = computed(() => s.status?.features?.flow_calibration_support !== false);
const canTimelapse = computed(() => s.status?.features?.camera_timelapse_support !== false);
let detailSeq = 0;
watch(one, async name => {
  details.value = null; detailsError.value = '';
  const mine = ++detailSeq;
  if (!name) return;
  const st = config.value?.settings;
  options.value = { leveling: st?.auto_leveling !== false, vibration: st?.vibration_compensation !== false, flow: st?.flow_calibration === true,
    timelapse: st?.timelapse === true };
  try {
    const r: FileDetails = (await bridge.command('file_details', { name }, s.info?.generation)) ?? {};
    if (mine !== detailSeq) return;
    details.value = r;
    const src = thumbSrc(r.thumbnail);
    if (src) thumbs.value = { ...thumbs.value, [name]: src };
  } catch (e) {
    if (mine === detailSeq) detailsError.value = message(e);
  }
});
const info = computed(() => details.value?.info ?? null);
const materials = computed(() => details.value?.materials ?? []);
function slotLabel(g: number | null): string {
  const sl = g == null ? null : s.status?.slots.find(x => x.global_index === g);
  if (!sl) return t('files.mat.none');
  return `${sl.box_id < 0 ? t('ace.head') : t('ace.unit', { n: sl.box_id + 1 })} · ${t('slot.name', { n: sl.index + 1 })}`;
}
const problem = (m: FileMaterial) => (m.check === 'differs'
  ? t('files.mat.differs', { n: m.paint_index + 1, material: m.material, slot: slotLabel(m.slot), type: m.slot_type || t('slot.noType') })
  : m.check === 'missing' ? t('files.mat.missing', { n: m.paint_index + 1, material: m.material || t('slot.noType') }) : '');
// Read-only check of what the file needs against the slots the print would use (file_details, plugin side).
const mismatch = computed(() => materials.value.map(problem).filter(Boolean).join('; '));
const n0 = (v: number | null | undefined, d = 0) => (v == null ? '—' : fmt.number(v, d));
const facts = computed(() => {
  const i = info.value;
  if (!i) return [];
  return [
    { label: t('files.info.time'), value: i.estimated_s != null ? fmt.duration(i.estimated_s) : '—' },
    { label: t('files.info.layers'), value: n0(i.layers) },
    { label: t('files.info.filament'), value: i.filament_g != null ? fmt.grams(i.filament_g) : '—' },
    { label: t('files.info.layer'), value: i.layer_height != null ? `${n0(i.layer_height, 2)} mm` : '—' },
    { label: t('files.info.temps'), value: t('files.info.tempsValue', { nozzle: n0(i.nozzle_temp), bed: n0(i.bed_temp) }) },
    { label: t('files.info.nozzle'), value: i.nozzle != null ? `${n0(i.nozzle, 1)} mm` : '—' },
  ];
});
const printOff = computed(() => !!controlsOff.value || busy.value.print || tracker.isBusy('print'));
async function print() {
  const name = one.value;
  if (!name || printOff.value) return;
  const flow = canFlow.value && options.value.flow, timelapse = canTimelapse.value && options.value.timelapse;
  const warn = [mismatch.value ? t('files.mat.warn', { list: mismatch.value }) : '',
    info.value && !info.value.model_ok ? t('files.modelOther', { model: info.value.printer_model }) : ''].filter(Boolean).join('\n');
  if (!await ask({ title: t('act.print'), text: t('confirm.print.text', { name, printer: printerName.value, leveling: t(options.value.leveling ? 'common.on' : 'common.off'),
    vibration: t(options.value.vibration ? 'common.on' : 'common.off'), flow: t(flow ? 'common.on' : 'common.off'), timelapse: t(timelapse ? 'common.on' : 'common.off') })
    + (warn ? '\n' + warn : ''), yes: t('confirm.print.yes'), no: t('common.goBack'), danger: !!warn })) return;
  const r = await run({ key: 'print', label: t('act.print'), cmd: 'file_print', args: { name, auto_leveling: options.value.leveling, vibration_compensation: options.value.vibration,
    flow_calibration: flow, timelapse },
    okText: t('ok.print'), timeoutMs: 60000 });
  if (r.ok) selected.value = [];
}
// Enter or a double click on a file: it becomes the one selected, with the keyboard on Start printing.
async function onOpen(id: string) {
  if (place.value !== 'local') return;
  selected.value = [id];
  await nextTick();
  document.querySelector<HTMLElement>('[data-focus-key="print-start"]')?.focus();
}

// ---------------------------------------------------------------- what the browser shows
const query = ref('');
const KIND: Record<string, string> = { gcode: 'G-code', gco: 'G-code', '3mf': '3MF' };
const kind = (name: string) => KIND[name.slice(name.lastIndexOf('.') + 1).toLowerCase()];
const places = computed<{ id: Place; name: string }[]>(() => [{ id: 'local', name: t('files.local') }, { id: 'videos', name: t('videos.title') }]);
const needle = computed(() => query.value.trim().toLowerCase());
const rows = computed(() => (place.value === 'videos'
  ? videos.value.filter(v => !needle.value || `${v.name} ${v.filename}`.toLowerCase().includes(needle.value)).map(v => ({
    id: v.filename, name: v.filename, size: v.size, sizeText: fmt.bytes(v.size), modified: v.created || null, modifiedText: v.created ? fmt.when(v.created, s.now / 1000) : undefined,
    kind: v.empty ? t('videos.aborted') : clipLength(v.duration) || undefined,
    facts: [{ label: t('videos.col.print'), value: v.name }, { label: t('videos.col.length'), value: v.empty ? t('videos.abortedHint') : clipLength(v.duration) || '—' },
      ...(v.created ? [{ label: t('videos.col.recorded'), value: fmt.dateTime(v.created) }] : [])] }))
  : listFiles(files.value, query.value, 'newest').map(f => ({
    id: f.name, name: f.name, size: f.size, sizeText: fmt.bytes(f.size), modified: f.timestamp ? seconds(f.timestamp) : null, modifiedText: f.timestamp ? fmt.when(seconds(f.timestamp), s.now / 1000) : undefined,
    kind: kind(f.name), thumb: thumbs.value[f.name] || thumbSrc(f.thumbnail) || null, facts: one.value === f.name ? facts.value : undefined }))));
const total = computed(() => (place.value === 'videos' ? videos.value.length : files.value.length));
const count = (n: number) => (place.value === 'videos' ? tn('videos.count', n) : tn('files.items', n));
const labels = computed<OuiFileBrowserLabels>(() => {
  const vid = place.value === 'videos';
  return {
    folders: t('files.places'), files: vid ? t('videos.title') : t('files.title'), name: t('files.col.name'), size: t('files.col.size'),
    modified: vid ? t('videos.col.recorded') : t('files.col.modified'), selectAll: t('files.selectAll'), select: name => t('files.select', { name }),
    items: n => (needle.value ? t('files.count', { shown: n, total: total.value }) : count(n)), selected: n => tn('files.selected', n),
    clear: t('common.clear'), moveTo: '', remove: t('files.delete'),
    removeTitle: n => fmt.pair(t(vid ? 'act.videoDelete' : 'files.delete'), count(n)), removeText: t('files.deleteText'), andMore: n => t('usage.more', { n }), cancel: t('common.goBack'),
    empty: needle.value ? t('files.noMatch', { q: query.value.trim() }) : vid ? t('videos.empty') : t('files.empty'),
    emptyText: needle.value ? undefined : vid ? t('videos.emptyHint') : undefined,
    loading: vid ? t('videos.loading') : t('files.loading'), nothingSelected: t('files.noneSelected'),
  };
});
const openError = computed(() => (state.value[place.value] === 'error' ? t(place.value === 'videos' ? 'videos.error' : 'files.error', { error: error.value[place.value] }) : ''));

// foundation-gap: OuiFileBrowser 5.0.0 always starts sorted by name and has no prop for it. A printer's list reads
// newest first (the file just sent is on top), so its own "Added" header is pressed once when it is drawn.
const browser = ref<ComponentPublicInstance | null>(null);
const newestFirst = () => (browser.value?.$el as HTMLElement | undefined)?.querySelectorAll<HTMLElement>('.oui-files-sort')[2]?.click();

// ---------------------------------------------------------------- delete (the browser has already asked)
// Refresh stands for the rows that went. The browser's own confirmation is still leaving when the printer has already
// answered, so the check waits for it: the keyboard is never left on <body>.
async function afterDelete() {
  await reloadOpen();   // after an error too: the list then shows what is still on the printer
  for (const end = Date.now() + 1500; document.querySelector('.p-dialog') && Date.now() < end;) await new Promise(r => setTimeout(r, 50));
  await nextTick();
  if (document.activeElement === document.body) document.querySelector<HTMLElement>('[data-focus-key="files-refresh"]')?.focus();
}
async function onDelete(ids: string[]) {
  if (!ids.length) return;
  const vid = place.value === 'videos';
  const done = (n: number) => (n === 1 ? t(vid ? 'ok.videoDelete' : 'ok.delete') : t('ok.deleteMany', { n }));
  if (vid) {
    // The printer deletes one video per message: one after the other, each failure said by itself.
    let ok = 0;
    for (const name of ids) {
      const r = await run({ key: `vdel:${name}`, label: t('act.videoDelete'), cmd: 'video_delete', args: { name } });
      if (r.ok) ok++;
    }
    if (ok) tracker.notify('success', done(ok));
  } else {
    await run({ key: 'files-delete', label: t('act.delete'), cmd: 'file_delete', args: { names: ids }, okText: done(ids.length) });
  }
  await afterDelete();
}
</script>

<template>
  <OuiPageHeader :title="t('nav.files')" data-test="files-head">
    <template #meta><span data-test="disk">{{ disk }}</span></template>
    <template #actions>
      <OuiHint v-if="hasVideos" end :label="t('videos.title')" :text="t('videos.noDownload')" data-test="videos-note" />
      <Button severity="secondary" :label="t('common.refresh')" :loading="state.local === 'loading' || state.videos === 'loading'" :disabled="!targetKnown" data-test="refresh" data-focus-key="files-refresh" @click="load">
        <template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
    </template>
  </OuiPageHeader>

  <div class="kc-msgs" data-msgs="files" />

  <div role="alert" class="kc-live fv-alert">
    <OuiBanner :show="!!openError && targetKnown" tone="error" :title="openError" data-test="files-error">
      <template #actions><Button size="small" severity="secondary" :label="t('common.retry')" @click="reloadOpen"><template #icon><OuiIcon :icon="refresh" :size="13" /></template></Button></template>
    </OuiBanner>
  </div>

  <OuiPanel v-if="!targetKnown" flush>
    <OuiEmpty state="offline" :title="t(s.phase === 'noCertificate' ? 'files.noCertificate' : s.phase === 'noTarget' ? 'files.noTarget' : 'files.waiting')" data-test="files-why" />
  </OuiPanel>

  <!-- No folders are passed: the printer has none, so the tree has nothing in it and nothing can take a drop. -->
  <OuiFileBrowser v-else ref="browser" :folder="place" v-model:selected="selected" :folders="NO_FOLDERS" :files="rows" :labels="labels" :loading="state[place] === 'loading' && !total"
                  :readonly="!!controlsOff" :describedby="whyId(false)" :data-place="place" @delete="onDelete" @open="onOpen" @vue:mounted="newestFirst">
    <template #toolbar>
      <span v-if="hasVideos" class="kc-seg" role="group" :aria-label="t('files.places')" data-test="files-lists">
        <Button v-for="p in places" :key="p.id" size="small" :severity="place === p.id ? undefined : 'secondary'" :text="place !== p.id" :aria-pressed="place === p.id"
                :label="p.name" :data-list="p.id" @click="openList(p.id)" />
      </span>
      <InputText v-model="query" type="search" size="small" :placeholder="t('files.searchPh')" :aria-label="t('files.search')" class="fv-q" data-test="files-q" />
    </template>
    <template v-if="place === 'local'" #actions="{ file }">
      <div class="fv-print" role="region" :aria-label="t('files.panel', { name: file.name })" data-test="print-panel">
        <p v-if="detailsError" class="kc-err" role="alert">{{ t('files.detailsError', { error: detailsError }) }}</p>
        <OuiEmpty v-else-if="!details" compact state="loading" :title="t('files.detailsLoading')" role="status" />
        <p v-if="info && !info.model_ok" class="fv-warn" role="alert" data-test="model-warn">{{ t('files.modelOther', { model: info.printer_model }) }}</p>
        <div v-if="materials.length" class="fv-mats">
          <p class="oui-label">{{ t('files.mat.title') }}</p>
          <ul>
            <li v-for="m in materials" :key="m.paint_index" :data-mat="m.paint_index" :data-check="m.check">
              <span class="fv-mat"><OuiSwatch :color="m.colour || null" /><span>{{ fmt.pair(t('files.mat.name', { n: m.paint_index + 1 }), m.material || t('slot.noType')) }} · {{ fmt.grams(m.grams) }}</span></span>
              <span class="fv-mat"><span class="oui-muted" aria-hidden="true">→</span><OuiSwatch :color="m.slot_colour || null" /><span>{{ slotLabel(m.slot) }}<template v-if="m.slot_type"> ({{ m.slot_type }})</template></span></span>
            </li>
          </ul>
          <p v-if="mismatch" class="fv-warn" role="alert" data-test="mat-warn">{{ t('files.mat.warn', { list: mismatch }) }}</p>
        </div>
        <fieldset class="fv-opts">
          <legend class="oui-label">{{ t('files.options') }}</legend>
          <label class="fv-opt" for="opt-level"><span>{{ t('files.autoLeveling') }}</span><ToggleSwitch v-model="options.leveling" input-id="opt-level" data-opt="auto_leveling" /></label>
          <label class="fv-opt" for="opt-vib"><span>{{ t('files.vibration') }}</span><ToggleSwitch v-model="options.vibration" input-id="opt-vib" data-opt="vibration_compensation" /></label>
          <label v-if="canFlow" class="fv-opt" for="opt-flow"><span>{{ t('files.flow') }}</span><ToggleSwitch v-model="options.flow" input-id="opt-flow" data-opt="flow_calibration" /></label>
          <label v-if="canTimelapse" class="fv-opt" for="opt-tl"><span>{{ t('files.timelapse') }}</span><ToggleSwitch v-model="options.timelapse" input-id="opt-tl" data-opt="timelapse" /></label>
        </fieldset>
        <Button :label="t('files.startPrint')" :disabled="printOff" :aria-describedby="whyId(busy.print)" :loading="tracker.isBusy('print')" data-test="print-start" data-focus-key="print-start" @click="print">
          <template #icon><OuiIcon :icon="printer" :size="14" /></template></Button>
      </div>
    </template>
  </OuiFileBrowser>
</template>

<style>
.fv-alert:empty { display: none; }
.fv-q { width: 220px; max-width: 100%; }
.fv-print { flex: 1 1 100%; display: grid; gap: var(--oui-s3); min-width: 0; }
.fv-print > .p-button { justify-self: start; }
.fv-warn { font-size: var(--oui-text-sm); font-weight: 600; color: var(--oui-warning); }
.fv-mats ul { list-style: none; margin: var(--oui-s1) 0 0; padding: 0; display: grid; gap: var(--oui-s1); }
.fv-mats li { display: flex; flex-wrap: wrap; align-items: center; gap: 2px var(--oui-s2); }
.fv-mat { display: inline-flex; align-items: center; gap: 6px; min-width: 0; }
.fv-mats li[data-check='differs'], .fv-mats li[data-check='missing'] { color: var(--oui-warning); }
.fv-opts { display: grid; gap: var(--oui-s1); margin: 0; padding: 0; border: 0; }
.fv-opt { display: flex; align-items: center; justify-content: space-between; gap: var(--oui-s3); min-height: 32px; }
/* foundation-gap: OuiFileBrowser 5.0.0 cannot leave its folder tree, its breadcrumb or "Move to" out, and the Kobra X
   has no folders and no message to move a file. These rules reach into it to show the browser without them: the list
   and the detail take the whole width, and the toolbar holds the switch between the two lists and the search. Delete
   them once the foundation can do it; the page tests fail if its class names change. */
.kc-files .oui-files-rail, .kc-files .oui-files-path, .kc-files .oui-files-move { display: none; }
.kc-files .oui-files-grid { grid-template-columns: minmax(0, 1fr) 300px; }
.kc-files .oui-files-tools { flex: 1 1 auto; justify-content: space-between; }
/* Narrow, the detail goes under the list. foundation-gap: there the browser gives the detail all the height it asks
   for, and a tall one (the print options) squeezes the list to nothing. It gets its content's height up to 55 % of the
   browser and scrolls inside; the list keeps the rest. */
@container oui-files (max-width: 980px) { .kc-files .oui-files-grid { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr) fit-content(55%); } }
/* foundation-gap: a detail pane taller than the browser squeezes the picture's row to nothing, and the picture is then
   drawn over the name and the facts. Its rows keep their own height, and the pane scrolls. */
.kc-files .oui-files-detail { grid-auto-rows: max-content; }
</style>
