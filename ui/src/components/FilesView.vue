<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import Button from 'primevue/button';
import Checkbox from 'primevue/checkbox';
import Message from 'primevue/message';
import Icon from './Icon.vue';
import * as bridge from '../core/bridge';
import { s, run, tracker, targetKnown, printerName, controlsOff } from '../app/store';
import { config } from '../app/settings';
import { ask } from '../core/dialog';
import { t, fmt } from '../core/i18n';
import { message } from '../core/tracker';
import { thumbSrc } from '../core/logic';
import type { FileEntry, FilesResult } from '../app/types';

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

// Storage comes with the status, in MB.
const disk = computed(() => { const st = s.status?.storage; return st?.total ? t('files.used', { used: fmt.bytes((st.used ?? 0) * 1e6), total: fmt.bytes(st.total * 1e6) }) : ''; });
const seconds = (ts: number) => (ts > 1e12 ? ts / 1000 : ts);

// ---------------------------------------------------------------- print panel: details and the two print options
const selected = ref<string | null>(null);
const details = ref<Record<string, unknown> | null>(null);
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
const printWhy = computed(() => controlsOff.value || (s.status && !s.status.can.print ? t('reason.noPrintNow') : tracker.isBusy('print') ? t('reason.pending') : ''));
async function print() {
  const name = selected.value;
  if (!name) return;
  if (!await ask({ title: t('act.print'), text: t('confirm.print.text', { name, printer: printerName.value, leveling: t(options.value.leveling ? 'common.on' : 'common.off'),
    vibration: t(options.value.vibration ? 'common.on' : 'common.off') }), yes: t('confirm.print.yes'), no: t('common.goBack') })) return;
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
  <section class="kc-card" aria-labelledby="files-h">
    <div class="kc-row fv-bar">
      <h2 id="files-h" class="fv-h"><Icon name="icon/files" /> {{ t('files.title') }}</h2>
      <span class="oui-meta" data-test="disk">{{ disk }}</span><span class="kc-spacer" />
      <Button severity="secondary" outlined :label="t('common.refresh')" :loading="state === 'loading'" :disabled="!targetKnown" data-test="refresh" @click="load" />
    </div>
    <p v-if="!targetKnown" class="oui-muted" data-test="files-why">{{ t(s.phase === 'noCertificate' ? 'files.noCertificate' : s.phase === 'noTarget' ? 'files.noTarget' : 'files.waiting') }}</p>
    <p v-else-if="state === 'loading' && !files.length" class="oui-muted" role="status">{{ t('files.loading') }}</p>
    <Message v-else-if="state === 'error'" severity="error">{{ t('files.error', { error }) }}
      <div><Button size="small" severity="secondary" outlined :label="t('common.retry')" @click="load" /></div></Message>
    <div v-else-if="state === 'ok'" class="oui-table-wrap">
      <table class="kc-table">
        <thead><tr><th scope="col">{{ t('files.col.name') }}</th><th scope="col">{{ t('files.col.size') }}</th><th scope="col">{{ t('files.col.modified') }}</th>
          <th scope="col">{{ t('files.col.actions') }}</th></tr></thead>
        <tbody>
          <tr v-for="f in files" :key="f.name" :class="{ sel: selected === f.name }" :data-file="f.name">
            <td class="fv-name">{{ f.name }}</td><td class="kc-num">{{ fmt.bytes(f.size) }}</td>
            <td>{{ f.timestamp ? fmt.dateTime(seconds(f.timestamp)) : '' }}</td>
            <td class="fv-acts">
              <Button size="small" :aria-label="t('files.printLabel', { name: f.name })" :data-focus-key="`print:${f.name}`" data-print @click="openPanel(f.name)">
                <Icon name="icon/print-setup" /><span>{{ t('files.print') }}</span></Button>
              <Button size="small" severity="danger" outlined :aria-label="t('files.deleteLabel', { name: f.name })" :loading="tracker.isBusy(`del:${f.name}`)"
                      :data-focus-key="`del:${f.name}`" data-delete @click="del(f.name)"><Icon name="icon/delete" /><span>{{ t('files.delete') }}</span></Button></td>
          </tr>
          <tr v-if="!files.length"><td colspan="4"><div class="fv-empty"><Icon name="spot/no-files" :size="96" /><span>{{ t('files.empty') }}</span></div></td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="selected" class="fv-panel" role="region" :aria-label="t('files.panel', { name: selected })" data-test="print-panel">
      <div class="fv-panel-top">
        <img v-if="thumb" :src="thumb" :alt="t('files.thumbAlt', { name: selected })" class="fv-thumb">
        <div class="fv-panel-text">
          <strong class="fv-name">{{ selected }}</strong>
          <p v-if="detailsError" class="kc-why kc-err">{{ t('files.detailsError', { error: detailsError }) }}</p>
          <p v-else-if="!details" class="kc-why" role="status">{{ t('files.detailsLoading') }}</p>
          <fieldset class="fv-opts">
            <legend class="oui-meta">{{ t('files.options') }}</legend>
            <span class="kc-row"><Checkbox v-model="options.leveling" binary input-id="opt-level" data-opt="auto_leveling" /><label for="opt-level">{{ t('files.autoLeveling') }}</label></span>
            <span class="kc-row"><Checkbox v-model="options.vibration" binary input-id="opt-vib" data-opt="vibration_compensation" /><label for="opt-vib">{{ t('files.vibration') }}</label></span>
          </fieldset>
        </div>
      </div>
      <div class="kc-row">
        <Button :disabled="!!printWhy" :loading="tracker.isBusy('print')" data-test="print-start" data-focus-key="print-start" @click="print">
          <Icon name="icon/print-setup" /><span>{{ t('files.startPrint') }}</span></Button>
        <Button severity="secondary" outlined :label="t('common.cancel')" data-test="print-close" @click="closePanel" />
        <span v-if="printWhy" class="kc-why">{{ printWhy }}</span>
      </div>
    </div>
  </section>
</template>
<style scoped>
.fv-h { margin: 0; display: flex; align-items: center; gap: 8px; }
.fv-bar { margin-bottom: 12px; }
.fv-name { overflow-wrap: anywhere; }
.fv-acts { display: flex; flex-wrap: wrap; gap: 6px; }
.fv-empty { display: grid; justify-items: center; gap: 8px; padding: 16px; color: var(--oui-muted); }
tr.sel td { background: color-mix(in srgb, var(--p-primary-color) 10%, transparent); }
.fv-panel { margin-top: 16px; padding: 12px; border: 1px solid var(--p-primary-color); border-radius: 12px; display: grid; gap: 12px; }
.fv-panel-top { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-start; }
.fv-panel-text { display: grid; gap: 8px; flex: 1 1 260px; min-width: 0; }
.fv-thumb { width: 160px; max-width: 100%; height: auto; border-radius: 8px; background: var(--oui-surface); border: 1px solid var(--oui-border); }
.fv-opts { display: grid; gap: 6px; margin: 0; padding: 0; border: 0; }
.fv-panel p { margin: 0; }
</style>
