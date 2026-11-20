<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import Button from 'primevue/button';
import Checkbox from 'primevue/checkbox';
import { OuiEmpty, OuiHint, OuiIcon, OuiJob, OuiPanel, OuiReadout, OuiStatus, type OuiState } from '../../shared/src/components';
import { layers, pause as pauseIcon, play, stop as stopIcon, x } from '../../shared/src/icons';
import PrinterFigure from './PrinterFigure.vue';
import * as bridge from '../core/bridge';
import { s, run, tracker, controlsOff, link, printing, printerName, stale, bindings, whyId } from '../app/store';
import { ask } from '../core/dialog';
import { t, tMaybe, fmt } from '../core/i18n';
import { finishAt, skippable } from '../core/logic';
import { figureSpools } from '../core/figure';
import { message } from '../core/tracker';

// The status block across the top of the dashboard: the printer's small picture, the state, the print (file, layer,
// percentage, times) and what can be done to it. Last known values of a printer the page no longer hears from are drawn
// grey with their age. Only the actions that apply are shown: Pause while it prints, Resume while it is paused, none
// with no print. Stop is the destructive one, outlined red, and it asks first.
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
// The file name may wrap after "_", "-" or "." before it breaks inside a word (desk_organiser_plate_1.gcode).
const jobName = computed(() => st.value?.filename || t('reason.noPrint'));
const nameParts = computed(() => jobName.value.match(/[^_.-]*[_.-]?/g)?.filter(Boolean) ?? []);
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
/** Off: the page's reason (#kc-why), the printer's (it is still preparing: #kc-busy), or its own command under way. */
const off = (kind: Kind) => !!controlsOff.value || tracker.isBusy(kind) || !st.value?.can[kind];
const paused = computed(() => state.value === 'paused');
const show = computed(() => ({ pause: !paused.value && (printing.value || !!st.value?.can.pause), resume: paused.value || !!st.value?.can.resume,
  stop: printing.value || !!st.value?.can.stop, skip: printing.value }));
const describedBy = computed(() => whyId(!!st.value?.preparing));
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
  <OuiPanel :aria-label="t('status.title')" data-test="job-card">
    <OuiEmpty v-if="!st" compact :state="link === 'offline' ? 'offline' : 'loading'" :title="t('status.noStatus')" />

    <OuiJob v-else class="kc-job" :stale="stale" :name="jobName" :progress="job ? pct : undefined" :progress-label="t('status.progress')" :detail="job ? layer : model" :data-idle="!job || undefined">
      <template #thumb><PrinterFigure :spools="spools" :state="state" :stale="stale" /></template>
      <template #status>
        <span class="kc-state"><OuiStatus :state="chip" data-test="state">{{ stateName }}</OuiStatus>
          <span v-if="detail || lastKnown" class="kc-state-detail" data-test="state-detail">{{ detail || lastKnown }}</span></span>
        <p class="kc-job-name" :title="jobName" data-test="job-name"><template v-for="(part, i) in nameParts" :key="i"><wbr v-if="i" />{{ part }}</template></p>
      </template>
      <template v-if="printing">
        <OuiReadout :label="t('status.elapsed')" :value="fmt.duration(st.elapsed_s)" size="sm" :stale="stale" />
        <OuiReadout :label="t('status.left')" :value="st.remaining_s ? fmt.duration(st.remaining_s) : null" size="sm" :stale="stale" :unknown-label="t('common.unknown')" />
        <OuiReadout :label="t('status.eta')" :value="eta" size="sm" :stale="stale" :unknown-label="t('common.unknown')" :data-test="eta ? 'eta' : undefined" />
      </template>
      <template v-if="show.pause || show.resume || show.stop || show.skip" #actions>
        <div class="kc-job-actions" role="group" :aria-label="t('status.controls')">
          <Button v-if="show.pause" severity="secondary" :label="t('act.pause')" :disabled="off('pause')" :aria-describedby="describedBy" :loading="tracker.isBusy('pause')" data-focus-key="pause" data-test="pause" @click="pause">
            <template #icon><OuiIcon :icon="pauseIcon" :size="14" /></template></Button>
          <Button v-if="show.resume" severity="secondary" :label="t('act.resume')" :disabled="off('resume')" :aria-describedby="describedBy" :loading="tracker.isBusy('resume')" data-focus-key="resume" data-test="resume" @click="resume">
            <template #icon><OuiIcon :icon="play" :size="14" /></template></Button>
          <Button v-if="show.skip" severity="secondary" text :label="open ? t('skip.close') : t('skip.open')" :aria-expanded="open" aria-controls="skip-body" :disabled="!!controlsOff"
                  :aria-describedby="whyId(false)" data-test="skip-open" data-focus-key="skip-open" @click="toggle">
            <template #icon><OuiIcon :icon="layers" :size="14" /></template></Button>
          <Button v-if="show.stop" severity="danger" outlined :label="t('act.stop')" :disabled="off('stop')" :aria-describedby="describedBy" :loading="tracker.isBusy('stop')" data-focus-key="stop" data-test="stop" @click="stop">
            <template #icon><OuiIcon :icon="stopIcon" :size="14" /></template></Button>
        </div>
      </template>
    </OuiJob>

    <div v-if="open" id="skip-body" class="kc-skip" data-test="skip-body">
      <!-- the (i) beside the label, not inside it: a label is set in capitals, and its hint would be too -->
      <div class="kc-skip-head"><p class="oui-label">{{ t('skip.title') }}</p><OuiHint :label="t('skip.title')" :text="t('skip.help')" /></div>
      <OuiEmpty v-if="sk.state === 'loading'" compact state="loading" :title="t('skip.loading')" role="status" />
      <div v-else-if="sk.state === 'error'" role="alert" class="oui-row" data-test="skip-error">
        <p class="kc-skip-err">{{ t('skip.error', { error: sk.error }) }}</p>
        <Button size="small" severity="secondary" :label="t('common.retry')" data-test="skip-retry" @click="loadObjects" />
      </div>
      <OuiEmpty v-else-if="!sk.objects.length" compact :title="t('skip.none')" role="status" />
      <template v-else>
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
/* The file name is drawn here so it can wrap at _ - . before it breaks inside a word (OuiJob's own name line is hidden);
   two lines at most. */
.kc-job .oui-job-id > .oui-job-name { display: none; }
.kc-job-name { font-size: var(--oui-text-lg); font-weight: 700; line-height: 1.3; overflow: hidden; overflow-wrap: anywhere;
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; }
/* No print: the block is the picture, the state and the printer's model; there is no progress to draw. */
.kc-job[data-idle] .oui-job-progress { display: none; }
/* The printer's photo in OuiJob's fixed 72 px box (a percentage would not resolve in its auto row). */
.kc-job .oui-job-thumb > .kx { width: auto; height: 72px; }
.kc-job-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: var(--oui-s2); }
.kc-skip { display: grid; gap: var(--oui-s2); margin-top: var(--oui-s3); padding-top: var(--oui-s3); border-top: 1px solid var(--oui-border); }
.kc-skip-head { display: flex; align-items: center; gap: var(--oui-s1); }
.kc-skip-err { color: var(--oui-danger); }
.kc-skip-objects { display: flex; flex-wrap: wrap; gap: var(--oui-s2) var(--oui-s5); }
.kc-skip-object { color: var(--oui-text); font-size: var(--oui-text-md); }
</style>
