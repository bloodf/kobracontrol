<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiEmpty, OuiFileBrowser, OuiHint, OuiIcon, OuiPageHeader, OuiPanel, OuiSwatch, useFileBackend, type OuiFileBackend, type OuiFileBrowserLabels } from '@orca-plugins/ui-foundation/src/components';
import { printer, refresh } from '@orca-plugins/ui-foundation/src/icons';
import * as bridge from '../core/bridge';
import { s, run, tracker, targetKnown, printerName, controlsOff, busy, whyId } from '../app/store';
import { config } from '../app/settings';
import { ask } from '../core/dialog';
import { t, tn, fmt } from '../core/i18n';
import { message } from '../core/tracker';
import { clipLength, thumbSrc } from '../core/logic';
import type { FileDetails, FileEntry, FileMaterial, FilesResult, VideoEntry, VideosResult } from '../app/types';

// The Files tab, on the shared file browser: what is on the printer, with multi-select and delete, and one file's
// details and print options beside the list. It is mounted while its tab is open, so the printer is asked for its
// files when the tab is opened, not before.
// What the Kobra X's LAN protocol offers (docs/protocol.md): file/listLocal of the storage's root, file/fileDetails,
// file/deleteBatch (several files in one message), file/listVideo and file/deleteVideo (one video per message). It has
// no folders to work with and no message to move, rename or create one, and no download. So the storage behind the
// browser lists and deletes, and nothing else: the browser then has no folder tree, no "Move to" and no dragging. The
// printer's two lists (print files, time-lapses) are a switch over the table.
type Place = 'local' | 'videos';
const place = ref<Place>('local');
// Time-lapses are listed for a connected printer (idle or printing).
const hasVideos = computed(() => s.phase === 'connected');
// What the printer last listed. The rows are drawn from these (below), so they follow the page's language and clock.
const local = ref<FileEntry[]>([]);
const videos = ref<VideoEntry[]>([]);

/** The tracker has already told the user (no answer in time, or the same command still running): no second toast. */
class Said extends Error {}
const failed = (r: { reason: string; error?: string }) => (r.reason === 'error' ? new Error(r.error || t('common.unknown')) : new Said());
let deleting: Place = 'local';
const backend: OuiFileBackend = {
  async list() {
    const generation = s.info?.generation;
    if (generation == null) throw new Error(t('files.waiting'));
    if (place.value === 'videos') {
      videos.value = ((await bridge.command('videos', {}, generation)) as VideosResult).videos ?? [];
      return videos.value.map(v => ({ id: v.filename, name: v.filename }));
    }
    local.value = ((await bridge.command('files', {}, generation)) as FilesResult).files ?? [];
    return local.value.map(f => ({ id: f.name, name: f.name }));
  },
  // The browser has already asked. A delete that removed only some rejects with how many are left.
  async remove(ids) {
    deleting = place.value;
    if (deleting === 'local') {
      const r = await run({ key: 'files-delete', label: t('act.delete'), cmd: 'file_delete', args: { names: ids }, quiet: true });
      if (!r.ok) throw failed(r);
      // The plugin answers with the list as it is now: a name still in it was not deleted.
      const now: FileEntry[] = (r.result as Partial<FilesResult> | null)?.files ?? [];
      const left = ids.filter(id => now.some(f => f.name === id)).length;
      if (left) throw new Error(t('files.deleteSome', { failed: left, n: ids.length, error: t('common.unknown') }));
      return;
    }
    // The printer deletes one video per message: one after the other, behind the one question.
    let last: { reason: string; error?: string } | null = null, count = 0;
    for (const name of ids) {
      const r = await run({ key: `vdel:${name}`, label: t('act.videoDelete'), cmd: 'video_delete', args: { name }, quiet: true });
      if (!r.ok) { count++; last = r; }
    }
    if (last) throw ids.length === 1 ? failed(last) : new Error(t('files.deleteSome', { failed: count, n: ids.length, error: last.error || t('common.unknown') }));
  },
};
const files = useFileBackend(backend, {
  onDone: (_action, ids) => tracker.notify('success', ids.length === 1 ? t(deleting === 'videos' ? 'ok.videoDelete' : 'ok.delete') : t('ok.deleteMany', { n: ids.length })),
  onError: (_action, e) => { if (!(e instanceof Said)) tracker.notify('error', t('msg.failed', { action: t(deleting === 'videos' ? 'act.videoDelete' : 'act.delete'), error: message(e) })); },
});
// Another printer, or the same one answering again: read its list.
watch(() => [s.epoch, s.phase], () => { if (!hasVideos.value) place.value = 'local'; void files.reload(); });
/** The other list: nothing stays selected across the two. */
function openList(to: Place) { if (to !== place.value) { files.selected = []; place.value = to; void files.reload(); } }

// Storage comes with the status, in MB.
const disk = computed(() => { const st = s.status?.storage; return st?.total ? t('files.used', { used: fmt.bytes((st.used ?? 0) * 1e6), total: fmt.bytes(st.total * 1e6) }) : ''; });
const seconds = (ts: number) => (ts > 1e12 ? ts / 1000 : ts);

// ---------------------------------------------------------------- one file selected: its details and the print options
const one = computed(() => (place.value === 'local' && files.selected.length === 1 ? files.selected[0] : null));
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
  if (r.ok) files.selected = [];
}
// Enter or a double click on a file: it becomes the one selected, with the keyboard on Start printing.
async function onOpen(id: string) {
  if (place.value !== 'local') return;
  files.selected = [id];
  await nextTick();
  document.querySelector<HTMLElement>('[data-focus-key="print-start"]')?.focus();
}

// ---------------------------------------------------------------- what the browser shows
const query = ref('');
const KIND: Record<string, string> = { gcode: 'G-code', gco: 'G-code', '3mf': '3MF' };
const kind = (name: string) => KIND[name.slice(name.lastIndexOf('.') + 1).toLowerCase()];
const places = computed<{ id: Place; name: string }[]>(() => [{ id: 'local', name: t('files.local') }, { id: 'videos', name: t('videos.title') }]);
const needle = computed(() => query.value.trim().toLowerCase());
const NEWEST = { key: 'modified', down: true } as const;   // a printer's list reads newest first: the file just sent is on top
const rows = computed(() => (place.value === 'videos'
  ? videos.value.filter(v => !needle.value || `${v.name} ${v.filename}`.toLowerCase().includes(needle.value)).map(v => ({
    id: v.filename, name: v.filename, size: v.size, sizeText: fmt.bytes(v.size), modified: v.created || null, modifiedText: v.created ? fmt.when(v.created, s.now / 1000) : undefined,
    kind: v.empty ? t('videos.aborted') : clipLength(v.duration) || undefined,
    facts: [{ label: t('videos.col.print'), value: v.name }, { label: t('videos.col.length'), value: v.empty ? t('videos.abortedHint') : clipLength(v.duration) || '—' },
      ...(v.created ? [{ label: t('videos.col.recorded'), value: fmt.dateTime(v.created) }] : [])] }))
  : local.value.filter(f => !needle.value || f.name.toLowerCase().includes(needle.value)).map(f => ({
    id: f.name, name: f.name, size: f.size, sizeText: fmt.bytes(f.size), modified: f.timestamp ? seconds(f.timestamp) : null, modifiedText: f.timestamp ? fmt.when(seconds(f.timestamp), s.now / 1000) : undefined,
    kind: kind(f.name), thumb: thumbs.value[f.name] || thumbSrc(f.thumbnail) || null, facts: one.value === f.name ? facts.value : undefined }))));
const total = computed(() => (place.value === 'videos' ? videos.value.length : local.value.length));
const labels = computed<OuiFileBrowserLabels>(() => {
  const vid = place.value === 'videos';
  return {
    folders: t('files.places'), files: vid ? t('videos.title') : t('files.title'), name: t('files.col.name'), size: t('files.col.size'),
    modified: vid ? t('videos.col.recorded') : t('files.col.modified'), selectAll: t('files.selectAll'), select: name => t('files.select', { name }),
    items: n => (needle.value ? t('files.count', { shown: n, total: total.value }) : tn(vid ? 'videos.count' : 'files.items', n)), selected: n => tn('files.selected', n),
    clear: t('common.clear'), moveTo: '', remove: t('files.delete'),
    removeTitle: n => tn(vid ? 'videos.deleteTitle' : 'files.deleteTitle', n), removeText: t('files.deleteText'), andMore: n => t('files.andMore', { n }), cancel: t('common.goBack'),
    empty: needle.value ? t('files.noMatch', { q: query.value.trim() }) : vid ? t('videos.empty') : t('files.empty'),
    emptyText: needle.value ? undefined : vid ? t('videos.emptyHint') : undefined,
    loading: vid ? t('videos.loading') : t('files.loading'), loadFailed: vid ? t('videos.loadFailed') : t('files.loadFailed'), retry: t('common.retry'),
    nothingSelected: t('files.noneSelected'), nothingSelectedText: vid ? undefined : t('files.selectHint'),
  };
});
</script>

<template>
  <OuiPageHeader :title="t('nav.files')" data-test="files-head">
    <template #meta><span data-test="disk">{{ disk }}</span></template>
    <template #actions>
      <OuiHint v-if="hasVideos" :label="t('videos.title')" :text="t('videos.noDownload')" data-test="videos-note" />
      <Button severity="secondary" :label="t('common.refresh')" :loading="files.loading" :disabled="!targetKnown" data-test="refresh" @click="files.reload()">
        <template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
    </template>
  </OuiPageHeader>

  <div class="kc-msgs" data-msgs="files" />

  <OuiPanel v-if="!targetKnown" flush>
    <OuiEmpty state="offline" :title="t(s.phase === 'noCertificate' ? 'files.noCertificate' : s.phase === 'noTarget' ? 'files.noTarget' : 'files.waiting')" data-test="files-why" />
  </OuiPanel>

  <!-- The rows are this page's (search, language, the opened file's picture and facts); the rest is the storage's. -->
  <OuiFileBrowser v-else v-bind="files.props" :files="rows" :labels="labels" :sort="NEWEST" :readonly="!!controlsOff" :describedby="whyId(false)" :data-place="place"
                  v-on="files.on" @open="onOpen">
    <template #toolbar>
      <span v-if="hasVideos" class="kc-seg" role="group" :aria-label="t('files.places')" data-test="files-lists">
        <Button v-for="p in places" :key="p.id" size="small" :severity="place === p.id ? undefined : 'secondary'" :text="place !== p.id" :aria-pressed="place === p.id"
                :label="p.name" :data-list="p.id" @click="openList(p.id)" />
      </span>
      <span class="oui-spacer" />
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
</style>
