<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import Button from 'primevue/button';
import Checkbox from 'primevue/checkbox';
import { OuiEmpty, OuiIcon, OuiJob, OuiPanel, OuiReadout, OuiStatus, type OuiState } from '../../shared/src/components';
import { calendar, clock, hourglass, layers, pause as pauseIcon, play, stop as stopIcon, x } from '../../shared/src/icons';
import PrinterFigure from './PrinterFigure.vue';
import * as bridge from '../core/bridge';
import { s, run, tracker, controlsOff, link, printing, printerName, stale, bindings } from '../app/store';
import { ask } from '../core/dialog';
import { t, tMaybe, fmt } from '../core/i18n';
import { finishAt, skippable } from '../core/logic';
import { figureSpools } from '../core/figure';
import { message } from '../core/tracker';

// The page's hero: the print (file, percentage, times) in the plugin's colour, or the idle printer. Last known values
// of a printer the page no longer hears from are drawn grey with their age. Pause, Resume, Skip objects and Stop sit
// under it; Stop is the destructive one, red, apart at the far end, and it asks first.
const st = computed(() => s.status);
const state = computed(() => st.value?.state ?? '');
const stateName = computed(() => (link.value === 'connecting' ? t('link.connecting') : link.value === 'offline' ? t('status.state.offline')
  : tMaybe(`status.state.${state.value}`, state.value)));
const chip = computed<OuiState>(() => (link.value === 'offline' ? 'offline' : stale.value ? 'stale'
  : (({ printing: 'busy', paused: 'pending', cancelled: 'idle', error: 'error', busy: 'busy' } as Record<string, OuiState>)[state.value] ?? 'ok')));
// While the printer works on one slot (feeding, retracting, purging) it says which one: ACE 1 · Slot 2.
const detail = computed(() => {
  const d = st.value;
  if (!d || link.value === 'offline' || link.value === 'connecting') return '';
  const where = d.preparing && d.phase_unit && d.phase_channel ? ` · ${t('ace.unit', { n: d.phase_unit })} · ${t('slot.name', { n: d.phase_channel })}` : '';
  return d.preparing ? tMaybe(`phase.${d.kobra_state}`, d.kobra_state) + where
    : d.state === 'error' ? d.last_error?.msg ?? '' : d.state === 'paused' ? d.pause_reason?.msg ?? '' : '';
});
const lastKnown = computed(() => (stale.value ? t('status.lastKnown', { age: fmt.ago(s.statusAt / 1000, s.now / 1000) }) : ''));
const job = computed(() => printing.value || !!st.value?.filename);
const pct = computed(() => (typeof st.value?.progress === 'number' ? Math.max(0, Math.min(100, st.value.progress)) : null));
const layer = computed(() => (st.value?.layer ? t('status.layer', { n: st.value.layer, total: st.value.total_layers || '?' }) : ''));
const eta = computed(() => {
  const at = finishAt(st.value, s.now / 1000);
  if (at == null || stale.value) return null;
  return new Date(at * 1000).toDateString() === new Date(s.now).toDateString() ? fmt.time(at) : fmt.dateTime(at);
});
// The drawing's four spools: the Spoolman spool bound to each slot (listed by Spoolman or by the stock view), else the ACE.
const spools = computed(() => figureSpools(st.value?.slots ?? [], [...s.spools, ...(s.stock?.stock.rows ?? [])], bindings.value, st.value?.loaded_slot ?? -1));
const model = computed(() => [st.value?.model, st.value?.firmware ? t('status.firmware', { version: st.value.firmware }) : ''].filter(Boolean).join(' · '));

// ---------------------------------------------------------------- print controls
type Kind = 'pause' | 'resume' | 'stop';
function why(kind: Kind): string {
  if (controlsOff.value) return controlsOff.value;
  if (tracker.isBusy(kind)) return t('reason.pending');
  if (st.value?.can[kind]) return '';
  if (kind === 'pause') return st.value?.preparing ? t('reason.preparing') : t('reason.notPrinting');
  return kind === 'resume' ? t('reason.notPaused') : t('reason.noPrint');
}
const pauseWhy = computed(() => why('pause'));
const resumeWhy = computed(() => why('resume'));
const stopWhy = computed(() => why('stop'));
const noPrint = computed(() => !controlsOff.value && !!pauseWhy.value && !!resumeWhy.value && !!stopWhy.value);
const describedBy = computed(() => (controlsOff.value ? 'kc-why' : noPrint.value ? 'print-why' : undefined));
const pause = () => run({ key: 'pause', label: t('act.pause'), cmd: 'pause', okText: t('ok.pause'), sentText: t('sent.pause'), timeoutMs: 15000 });
const resume = () => run({ key: 'resume', label: t('act.resume'), cmd: 'resume', okText: t('ok.resume'), sentText: t('sent.resume'), timeoutMs: 15000 });
async function stop() {
  if (!await ask({ title: t('confirm.stop.title'), text: t('confirm.stop.text', { printer: printerName.value }),
    yes: t('confirm.stop.yes'), no: t('confirm.stop.no'), danger: true })) return;
  await run({ key: 'stop', label: t('act.stop'), cmd: 'stop', okText: t('ok.stop'), sentText: t('sent.stop'), timeoutMs: 15000 });
}

// ---------------------------------------------------------------- object skip: the plugin's `objects` command answers for the running print when opened
const open = ref(false);
const sk = reactive({ state: 'idle' as 'idle' | 'loading' | 'ok' | 'error', objects: [] as string[], error: '' });
const chosen = ref<string[]>([]);
let seq = 0;
async function loadObjects() {
  const mine = ++seq;
  sk.state = 'loading';
  try {
    const r = await bridge.command('objects', {}, s.info?.generation);
    if (mine !== seq) return;
    sk.objects = skippable(r?.objects, r?.skipped);
    chosen.value = chosen.value.filter(n => sk.objects.includes(n));
    sk.state = 'ok';
  } catch (e) {
    if (mine !== seq) return;
    sk.error = message(e); sk.state = 'error';
  }
}
function toggle() { open.value = !open.value; if (open.value) void loadObjects(); }
const skipWhy = computed(() => controlsOff.value || (!printing.value ? t('reason.noPrint') : ''));
// Skip off for its own reason while Stop still works (the shared reasons above don't cover it): said beside it.
const skipOwnWhy = computed(() => (skipWhy.value && !controlsOff.value && !noPrint.value ? skipWhy.value : ''));
const skipDescribedBy = computed(() => (!skipWhy.value ? undefined : skipOwnWhy.value ? 'skip-why' : describedBy.value));
// A finished print or another printer closes the section: its list is no longer true.
watch(() => [printing.value, s.epoch], () => { open.value = false; seq++; sk.state = 'idle'; chosen.value = []; });
async function skip() {
  const names = chosen.value.filter(n => sk.objects.includes(n));
  if (!names.length) return;
  if (!await ask({ title: t('confirm.skip.title'), text: t('confirm.skip.text', { printer: printerName.value, names: fmt.list(names) }),
    yes: t('confirm.skip.yes'), no: t('common.goBack'), danger: true })) return;
  const r = await run({ key: 'skip', label: t('act.skip'), cmd: 'skip_objects', args: { names }, okText: t('ok.skip') });
  if (r.ok) { chosen.value = []; void loadObjects(); }
}
</script>

<template>
  <OuiPanel flush :aria-label="t('status.title')" data-test="job-card">
    <OuiEmpty v-if="!st" compact :state="link === 'offline' ? 'offline' : 'loading'" :title="t('status.noStatus')" />

    <OuiJob v-else-if="job" class="kc-hero" hero :stale="stale" :name="st.filename || stateName" :progress="pct" :progress-label="t('status.progress')" :detail="layer">
      <template #thumb><PrinterFigure :spools="spools" :state="state" :stale="stale" /></template>
      <template #status>
        <span class="kc-state"><OuiStatus :state="chip" data-test="state">{{ stateName }}</OuiStatus>
          <span v-if="detail || lastKnown" class="kc-state-detail" data-test="state-detail">{{ detail || lastKnown }}</span></span>
      </template>
      <template v-if="printing">
        <OuiReadout :icon="clock" :label="t('status.elapsed')" :value="fmt.duration(st.elapsed_s)" size="sm" :stale="stale" />
        <OuiReadout :icon="hourglass" :label="t('status.left')" :value="st.remaining_s ? fmt.duration(st.remaining_s) : null" size="sm" :stale="stale" :unknown-label="t('common.unknown')" />
        <OuiReadout :icon="calendar" :label="t('status.eta')" :value="eta" size="sm" :stale="stale" :unknown-label="t('common.unknown')" :data-test="eta ? 'eta' : undefined" />
      </template>
    </OuiJob>

    <div v-else class="oui-hero kc-idle" :class="{ 'oui-on-band': !stale }" :data-tone="stale ? 'neutral' : undefined">
      <div class="kc-figure"><PrinterFigure :spools="spools" :state="state" :stale="stale" /></div>
      <div class="kc-idle-id">
        <span class="kc-state"><OuiStatus :state="chip" data-test="state">{{ stateName }}</OuiStatus>
          <span v-if="detail || lastKnown" class="kc-state-detail" data-test="state-detail">{{ detail || lastKnown }}</span></span>
        <p class="kc-idle-name oui-truncate" :title="printerName">{{ printerName }}</p>
        <p v-if="model" class="kc-idle-detail">{{ model }}</p>
      </div>
    </div>

    <div class="kc-job-actions" role="group" :aria-label="t('status.controls')">
      <Button severity="secondary" :label="t('act.pause')" :disabled="!!pauseWhy" :aria-describedby="describedBy" :loading="tracker.isBusy('pause')" data-focus-key="pause" data-test="pause" @click="pause">
        <template #icon><OuiIcon :icon="pauseIcon" :size="14" /></template></Button>
      <Button severity="secondary" :label="t('act.resume')" :disabled="!!resumeWhy" :aria-describedby="describedBy" :loading="tracker.isBusy('resume')" data-focus-key="resume" data-test="resume" @click="resume">
        <template #icon><OuiIcon :icon="play" :size="14" /></template></Button>
      <Button severity="secondary" text :label="open ? t('skip.close') : t('skip.open')" :aria-expanded="open" aria-controls="skip-body" :disabled="!!skipWhy"
              :aria-describedby="skipDescribedBy" data-test="skip-open" data-focus-key="skip-open" @click="toggle">
        <template #icon><OuiIcon :icon="layers" :size="14" /></template></Button>
      <span class="oui-spacer" />
      <Button severity="danger" :label="t('act.stop')" :disabled="!!stopWhy" :aria-describedby="describedBy" :loading="tracker.isBusy('stop')" data-focus-key="stop" data-test="stop" @click="stop">
        <template #icon><OuiIcon :icon="stopIcon" :size="14" /></template></Button>
      <p v-if="skipOwnWhy" id="skip-why" class="oui-meta kc-job-why" data-test="skip-why">{{ fmt.pair(t('skip.title'), skipOwnWhy) }}</p>
      <p v-if="noPrint" id="print-why" class="oui-meta kc-job-why" data-test="print-why">{{ t('reason.noPrint') }}</p>
    </div>

    <div v-if="open" id="skip-body" class="kc-skip" data-test="skip-body">
      <p class="oui-label">{{ t('skip.title') }}</p>
      <p v-if="sk.state === 'loading'" class="oui-muted" role="status">{{ t('skip.loading') }}</p>
      <div v-else-if="sk.state === 'error'" role="alert" class="oui-row" data-test="skip-error">
        <p class="kc-skip-err">{{ t('skip.error', { error: sk.error }) }}</p>
        <Button size="small" severity="secondary" :label="t('common.retry')" data-test="skip-retry" @click="loadObjects" />
      </div>
      <p v-else-if="!sk.objects.length" class="oui-muted" role="status">{{ t('skip.none') }}</p>
      <template v-else>
        <p class="oui-meta">{{ t('skip.help') }}</p>
        <div class="kc-skip-objects" role="group" :aria-label="t('skip.title')">
          <label v-for="(n, i) in sk.objects" :key="n" class="kc-inline kc-skip-object" :for="`obj-${i}`">
            <Checkbox v-model="chosen" :input-id="`obj-${i}`" :value="n" :data-object="n" />{{ n }}</label>
        </div>
        <div class="oui-row">
          <Button severity="danger" outlined size="small" :label="t('skip.go')" :disabled="!chosen.length" :loading="tracker.isBusy('skip')" data-test="skip" data-focus-key="skip" @click="skip">
            <template #icon><OuiIcon :icon="x" :size="14" /></template></Button>
        </div>
      </template>
    </div>
  </OuiPanel>
</template>

<style>
.kc-state { display: inline-flex; flex-wrap: wrap; align-items: center; gap: var(--oui-s1) var(--oui-s2); min-width: 0; }
.kc-state-detail { font-size: var(--oui-text-sm); font-weight: 600; }
.kc-idle { display: flex; align-items: center; gap: var(--oui-s3); border-radius: var(--oui-radius-lg) var(--oui-radius-lg) 0 0; }
.kc-idle-id { display: grid; gap: 2px; min-width: 0; }
.kc-idle-id > .kc-state { margin-bottom: 4px; }
.kc-idle-name { font-size: var(--oui-text-lg); font-weight: 700; line-height: 1.3; }
.kc-idle-detail { font-size: var(--oui-text-sm); }
/* Wide: the printer photo takes about 40 % of the card beside the whole job block, no taller than that block. */
@container oui-page (min-width: 560px) {
  .kc-hero .oui-job-block { grid-template-columns: 40% minmax(0, 1fr) auto; grid-template-rows: 1fr auto auto; column-gap: var(--oui-s4); }
  .kc-hero .oui-job-head { display: contents; }
  .kc-hero .oui-job-thumb { grid-column: 1; grid-row: 1 / span 3; display: flex; justify-content: center; align-self: center; }
  .kc-hero .oui-job-id { grid-column: 2; grid-row: 1; align-self: end; }
  .kc-hero .oui-job-figure { grid-column: 3; grid-row: 1; align-self: end; }
  .kc-hero .oui-job-bar { grid-column: 2 / 4; grid-row: 2; }
  .kc-hero .oui-job-stats { grid-column: 2 / 4; grid-row: 3; }
  .kc-hero .kx { height: 296px; max-width: 100%; }
  .kc-figure { flex: 0 0 40%; display: flex; justify-content: center; }
  .kc-figure .kx { height: 272px; max-width: 100%; }
}
/* Narrow (the dock): the printer takes its own row above the name. */
@container oui-page (max-width: 559px) {
  .kc-hero .oui-job-head, .kc-idle { flex-wrap: wrap; }
  .kc-hero .oui-job-thumb, .kc-figure { flex-basis: 100%; display: flex; justify-content: center; }
  .kc-hero .kx, .kc-figure .kx { height: 200px; }
}
.kc-job-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oui-s2); padding: var(--oui-s3) var(--oui-s4); }
.kc-job-why { flex-basis: 100%; }
.kc-skip { display: grid; gap: var(--oui-s2); padding: var(--oui-s3) var(--oui-s4); border-top: 1px solid var(--oui-border); }
.kc-skip-err { color: var(--oui-danger); }
.kc-skip-objects { display: flex; flex-wrap: wrap; gap: var(--oui-s2) var(--oui-s5); }
.kc-skip-object { color: var(--oui-text); font-size: var(--oui-text-md); }
</style>
