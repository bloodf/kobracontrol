<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Select from 'primevue/select';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiEmpty, OuiIcon, OuiKeyValue, OuiPanel, OuiSwatch, OuiThumb, OuiToolbar } from '../../shared/src/components';
import { file as fileIcon, files as filesIcon, printer, refresh, trash, x } from '../../shared/src/icons';
import * as bridge from '../core/bridge';
import { s, run, tracker, targetKnown, printerName, controlsOff } from '../app/store';
import { config } from '../app/settings';
import { ask } from '../core/dialog';
import { t, fmt } from '../core/i18n';
import { message } from '../core/tracker';
import { thumbSrc, listFiles, type FileSort } from '../core/logic';
import type { FileDetails, FileEntry, FileMaterial, FilesResult } from '../app/types';

const state = ref<'idle' | 'loading' | 'ok' | 'error'>('idle');
const error = ref('');
const files = ref<FileEntry[]>([]);
let loadSeq = 0;

async function load() {
  if (!targetKnown.value || !s.info) { state.value = 'idle'; files.value = []; return; }
  const mine = ++loadSeq;
  state.value = 'loading';
  try {
    const r: FilesResult = await bridge.command('files', {}, s.info.generation);
    if (mine !== loadSeq) return;
    files.value = r.files ?? [];
    state.value = 'ok';
  } catch (e) {
    if (mine !== loadSeq) return;
    error.value = message(e); state.value = 'error';
  }
}

// Search and order: on the page only, over the list the printer gave.
const query = ref('');
const sort = ref<FileSort>('newest');
const sortOptions = computed(() => (['newest', 'oldest', 'name', 'largest'] as const).map(v => ({ value: v, label: t(`files.sort.${v}`) })));
const shown = computed(() => listFiles(files.value, query.value, sort.value));

// Storage comes with the status, in MB.
const disk = computed(() => { const st = s.status?.storage; return st?.total ? t('files.used', { used: fmt.bytes((st.used ?? 0) * 1e6), total: fmt.bytes(st.total * 1e6) }) : ''; });
const seconds = (ts: number) => (ts > 1e12 ? ts / 1000 : ts);

// ---------------------------------------------------------------- print panel: details and the two print options
const selected = ref<string | null>(null);
const details = ref<FileDetails | null>(null);
const detailsError = ref('');
const options = ref({ leveling: true, vibration: true });
let detailSeq = 0;
watch(() => [s.tab, s.epoch, s.phase], () => { if (s.tab === 'files') void load(); else selected.value = null; }, { immediate: true });
async function openPanel(name: string) {
  selected.value = name; details.value = null; detailsError.value = '';
  options.value = { leveling: config.value?.settings.auto_leveling !== false, vibration: config.value?.settings.vibration_compensation !== false };
  const mine = ++detailSeq;
  try {
    const r = await bridge.command('file_details', { name }, s.info?.generation);
    if (mine === detailSeq) details.value = r ?? {};
  } catch (e) {
    if (mine === detailSeq) detailsError.value = message(e);
  }
}
const closePanel = () => { selected.value = null; };
const thumb = computed(() => thumbSrc(details.value?.thumbnail));
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
const printWhyId = computed(() => (!printWhy.value ? undefined : controlsOff.value ? 'kc-why' : 'print-start-why'));
const printWhy = computed(() => controlsOff.value || (s.status && !s.status.can.print ? t('reason.noPrintNow') : tracker.isBusy('print') ? t('reason.pending') : ''));
async function print() {
  const name = selected.value;
  if (!name) return;
  const warn = [mismatch.value ? t('files.mat.warn', { list: mismatch.value }) : '',
    info.value && !info.value.model_ok ? t('files.modelOther', { model: info.value.printer_model }) : ''].filter(Boolean).join('\n');
  if (!await ask({ title: t('act.print'), text: t('confirm.print.text', { name, printer: printerName.value, leveling: t(options.value.leveling ? 'common.on' : 'common.off'),
    vibration: t(options.value.vibration ? 'common.on' : 'common.off') }) + (warn ? '\n' + warn : ''), yes: t('confirm.print.yes'), no: t('common.goBack'), danger: !!warn })) return;
  const r = await run({ key: 'print', label: t('act.print'), cmd: 'file_print', args: { name, auto_leveling: options.value.leveling, vibration_compensation: options.value.vibration },
    okText: t('ok.print'), timeoutMs: 60000 });
  if (r.ok) closePanel();
}

async function del(name: string) {
  if (!await ask({ title: t('files.delete'), text: t('confirm.delete.text', { name }), yes: t('confirm.delete.yes'), no: t('common.goBack'), danger: true })) return;
  const r = await run({ key: `del:${name}`, label: t('act.delete'), cmd: 'file_delete', args: { names: [name] }, okText: t('ok.delete') });
  if (r.ok) { if (selected.value === name) closePanel(); void load(); }
}
</script>
<template>
  <div class="fv" :data-detail="selected ? true : undefined">
    <OuiPanel :icon="filesIcon" flush aria-labelledby="files-h" class="fv-list">
      <template #title><span id="files-h">{{ t('files.title') }}</span></template>
      <template #meta><span data-test="disk">{{ disk }}</span></template>
      <template #actions>
        <Button severity="secondary" size="small" :label="t('common.refresh')" :loading="state === 'loading'" :disabled="!targetKnown" data-test="refresh" @click="load">
          <template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
      </template>
      <OuiToolbar v-if="state === 'ok' && files.length" class="fv-bar" :label="t('files.search')">
        <InputText v-model="query" type="search" size="small" :placeholder="t('files.searchPh')" :aria-label="t('files.search')" class="fv-q" data-test="files-q" />
        <Select v-model="sort" :options="sortOptions" option-label="label" option-value="value" size="small" :aria-label="t('files.sort')" data-test="files-sort" />
        <span v-if="query.trim()" class="oui-meta oui-num" role="status" data-test="files-count">{{ t('files.count', { shown: shown.length, total: files.length }) }}</span>
      </OuiToolbar>
      <OuiEmpty v-if="!targetKnown" state="offline" :title="t(s.phase === 'noCertificate' ? 'files.noCertificate' : s.phase === 'noTarget' ? 'files.noTarget' : 'files.waiting')" data-test="files-why" />
      <OuiEmpty v-else-if="state === 'loading' && !files.length" state="loading" :title="t('files.loading')" role="status" />
      <OuiEmpty v-else-if="state === 'error'" state="error" class="fv-error" :title="t('files.error', { error })">
        <template #actions><Button size="small" severity="secondary" :label="t('common.retry')" @click="load"><template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button></template>
      </OuiEmpty>
      <OuiEmpty v-else-if="state === 'ok' && !files.length" class="fv-empty" :icon="fileIcon" :title="t('files.empty')" />
      <div v-else-if="state === 'ok'" class="oui-table-wrap">
        <table class="kc-table fv-table">
          <thead><tr><th scope="col">{{ t('files.col.name') }}</th><th scope="col" class="oui-num fv-size">{{ t('files.col.size') }}</th>
            <th scope="col" class="fv-date">{{ t('files.col.modified') }}</th><th scope="col" class="oui-end fv-act"><span class="oui-sr">{{ t('files.col.actions') }}</span></th></tr></thead>
          <tbody>
            <tr v-for="f in shown" :key="f.name" :class="{ sel: selected === f.name }" :data-file="f.name">
              <td><span class="fv-name"><OuiIcon :icon="fileIcon" :size="14" tile soft /><span class="oui-strong">{{ f.name }}</span></span></td>
              <td class="oui-num">{{ fmt.bytes(f.size) }}</td>
              <td class="fv-date">{{ f.timestamp ? fmt.dateTime(seconds(f.timestamp)) : '' }}</td>
              <td class="oui-end"><span class="fv-acts">
                <Button size="small" severity="secondary" :label="t('files.print')" :aria-label="t('files.printLabel', { name: f.name })" :data-focus-key="`print:${f.name}`" data-print
                        @click="openPanel(f.name)"><template #icon><OuiIcon :icon="printer" :size="14" /></template></Button>
                <!-- Delete is the destructive one: red, last, a gap away from Print. It always asks first. -->
                <Button size="small" severity="danger" text class="fv-del" :aria-label="t('files.deleteLabel', { name: f.name })" :title="t('files.delete')" :loading="tracker.isBusy(`del:${f.name}`)"
                        :data-focus-key="`del:${f.name}`" data-delete @click="del(f.name)"><template #icon><OuiIcon :icon="trash" :size="14" /></template></Button>
              </span></td>
            </tr>
            <tr v-if="files.length && !shown.length"><td colspan="4" class="oui-muted" data-test="files-nomatch">{{ t('files.noMatch', { q: query.trim() }) }}</td></tr>
          </tbody>
        </table>
      </div>
    </OuiPanel>

    <OuiPanel v-if="selected" :icon="printer" class="fv-detail" role="region" :aria-label="t('files.panel', { name: selected })" data-test="print-panel">
      <template #title><span class="oui-truncate" :title="selected">{{ selected }}</span></template>
      <template #actions>
        <Button severity="secondary" text size="small" :aria-label="t('common.close')" :title="t('common.close')" @click="closePanel"><template #icon><OuiIcon :icon="x" :size="14" /></template></Button>
      </template>
      <div class="oui-stack">
        <div class="fv-top">
          <OuiThumb v-if="thumb" class="fv-thumb" :src="thumb" :alt="t('files.thumbAlt', { name: selected })" :size="132" />
          <div class="fv-facts">
            <p v-if="detailsError" class="kc-why" data-tone="danger">{{ t('files.detailsError', { error: detailsError }) }}</p>
            <OuiEmpty v-else-if="!details" compact state="loading" :title="t('files.detailsLoading')" role="status" />
            <OuiKeyValue v-if="info" :items="facts" :aria-label="t('files.info')" data-test="file-info" />
          </div>
        </div>
        <p v-if="info && !info.model_ok" class="fv-warn" role="alert" data-test="model-warn">{{ t('files.modelOther', { model: info.printer_model }) }}</p>
        <div v-if="materials.length" class="fv-mats">
          <p class="oui-label">{{ t('files.mat.title') }}</p>
          <ul>
            <li v-for="m in materials" :key="m.paint_index" :data-mat="m.paint_index" :data-check="m.check">
              <OuiSwatch :color="m.colour || null" /><span>{{ t('files.mat.name', { n: m.paint_index + 1 }) }}: {{ m.material || t('slot.noType') }} · {{ fmt.grams(m.grams) }}</span>
              <span class="oui-muted" aria-hidden="true">→</span>
              <OuiSwatch :color="m.slot_colour || null" /><span>{{ slotLabel(m.slot) }}<template v-if="m.slot_type"> ({{ m.slot_type }})</template></span>
            </li>
          </ul>
          <p v-if="mismatch" class="fv-warn" role="alert" data-test="mat-warn">{{ t('files.mat.warn', { list: mismatch }) }}</p>
        </div>
        <fieldset class="fv-opts">
          <legend class="oui-label">{{ t('files.options') }}</legend>
          <label class="fv-opt" for="opt-level"><span>{{ t('files.autoLeveling') }}</span><ToggleSwitch v-model="options.leveling" input-id="opt-level" data-opt="auto_leveling" /></label>
          <label class="fv-opt" for="opt-vib"><span>{{ t('files.vibration') }}</span><ToggleSwitch v-model="options.vibration" input-id="opt-vib" data-opt="vibration_compensation" /></label>
        </fieldset>
      </div>
      <template #footer>
        <Button :label="t('files.startPrint')" :disabled="!!printWhy" :aria-describedby="printWhyId" :loading="tracker.isBusy('print')" data-test="print-start" data-focus-key="print-start" @click="print">
          <template #icon><OuiIcon :icon="printer" :size="14" /></template></Button>
        <Button severity="secondary" text :label="t('common.cancel')" data-test="print-close" @click="closePanel" />
        <span v-if="printWhy && !controlsOff" id="print-start-why" class="oui-meta">{{ printWhy }}</span>
      </template>
    </OuiPanel>
  </div>
</template>

<style>
.fv { display: grid; gap: var(--oui-s3); grid-template-columns: minmax(0, 1fr); align-items: start; }
@container oui-page (min-width: 1160px) { .fv[data-detail] { grid-template-columns: minmax(0, 3fr) minmax(360px, 2fr); } }
.fv-bar { border-bottom: 1px solid var(--oui-border); }
.fv-q { width: 240px; max-width: 100%; }
.fv-table { table-layout: fixed; min-width: 520px; }
.fv-size { width: 96px; } .fv-date { width: 150px; } .fv-act { width: 132px; }
.fv-name { display: inline-flex; align-items: center; gap: var(--oui-s2); min-width: 0; overflow-wrap: anywhere; }
.fv-acts { display: inline-flex; align-items: center; justify-content: flex-end; gap: var(--oui-s1); white-space: nowrap; }
.fv-del { margin-inline-start: var(--oui-s3); }
.fv-table tr.sel > td { background: var(--oui-primary-soft); }
.fv-top { display: flex; flex-wrap: wrap; gap: var(--oui-s4); align-items: flex-start; }
.fv-facts { flex: 1 1 200px; min-width: 0; }
.fv-warn { font-size: var(--oui-text-sm); font-weight: 600; color: var(--oui-warning); }
.fv-mats ul { list-style: none; margin: var(--oui-s1) 0 0; padding: 0; display: grid; gap: var(--oui-s1); }
.fv-mats li { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oui-s2); }
.fv-mats li[data-check='differs'], .fv-mats li[data-check='missing'] { color: var(--oui-warning); }
.fv-opts { display: grid; gap: var(--oui-s1); margin: 0; padding: 0; border: 0; }
.fv-opt { display: flex; align-items: center; justify-content: space-between; gap: var(--oui-s3); min-height: 36px; }
</style>
