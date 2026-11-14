<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import Button from 'primevue/button';
import InputNumber from 'primevue/inputnumber';
import Select from 'primevue/select';
import Checkbox from 'primevue/checkbox';
import ProgressBar from 'primevue/progressbar';
import Icon from './Icon.vue';
import MotionPanel from './MotionPanel.vue';
import { s, run, tracker, controlsOff, printing, printerName, reported } from '../app/store';
import { ask } from '../core/dialog';
import { t, tMaybe, fmt } from '../core/i18n';
import { parseTarget, parseWhole } from '../core/logic';

const st = computed(() => s.status);
const stateText = computed(() => {
  const d = st.value;
  if (!d) return t('status.noStatus');
  const name = tMaybe(`status.state.${d.state}`, d.state);
  // While the printer works on one slot (feeding, retracting, purging) it says which one: ACE 1 · Slot 2.
  const where = d.preparing && d.phase_unit && d.phase_channel ? ` · ${t('ace.unit', { n: d.phase_unit })} · ${t('slot.name', { n: d.phase_channel })}` : '';
  const detail = d.preparing ? tMaybe(`phase.${d.kobra_state}`, d.kobra_state) + where
    : d.state === 'error' ? d.last_error?.msg ?? '' : d.state === 'paused' ? d.pause_reason?.msg ?? '' : '';
  return detail ? `${name} · ${detail}` : name;
});
const pct = computed(() => Math.max(0, Math.min(100, st.value?.progress ?? 0)));

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
const pause = () => run({ key: 'pause', label: t('act.pause'), cmd: 'pause', okText: t('ok.pause'), sentText: t('sent.pause'), timeoutMs: 15000 });
const resume = () => run({ key: 'resume', label: t('act.resume'), cmd: 'resume', okText: t('ok.resume'), sentText: t('sent.resume'), timeoutMs: 15000 });
async function stop() {
  if (!await ask({ title: t('confirm.stop.title'), text: t('confirm.stop.text', { printer: printerName.value }),
    yes: t('confirm.stop.yes'), no: t('confirm.stop.no'), danger: true })) return;
  await run({ key: 'stop', label: t('act.stop'), cmd: 'stop', okText: t('ok.stop'), sentText: t('sent.stop'), timeoutMs: 15000 });
}

// ---------------------------------------------------------------- temperatures
// InputNumber commits its model on blur; the typed value is tracked on every input so buttons react at once.
const asNumber = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
type HeaterKey = 'nozzle' | 'bed';
const drafts = reactive<Record<string, number | null>>({});
const heaters = computed(() => {
  const d = st.value;
  return [
    { key: 'nozzle' as HeaterKey, label: t('temps.nozzle'), temp: d?.nozzle_temp, target: d?.nozzle_target, max: s.limits.nozzle_max, badge: 'icon/temperature' },
    { key: 'bed' as HeaterKey, label: t('temps.bed'), temp: d?.bed_temp, target: d?.bed_target, max: s.limits.bed_max, badge: 'icon/bed' },
  ];
});
const heatOff = computed(() => controlsOff.value || (st.value && !st.value.can.heat ? t('reason.noHeat') : ''));
const parsed = (key: string, max: number) => parseTarget(drafts[key], max);
function setWhy(key: string, max: number): string {
  if (heatOff.value) return heatOff.value;
  const p = parsed(key, max);
  if (p.kind === 'empty') return t('temps.empty');
  if (p.kind === 'invalid') return t('temps.invalid', { min: 0, max });
  return tracker.isBusy('temp:' + key) ? t('reason.pending') : '';
}
const reading = (v: number | undefined) => (reported.value && v != null ? fmt.number(v, 1) : '—');
async function turnOff(key: HeaterKey, heater: string) {
  await run({ key: 'temp:' + key, label: t('act.temperature', { heater }), cmd: 'set_temp', args: { [key]: 0 }, okText: t('ok.off', { heater }) });
}
async function setTemp(key: HeaterKey, heater: string, max: number) {
  const p = parsed(key, max);
  if (p.kind === 'off') return turnOff(key, heater);
  if (p.kind !== 'heat') return;
  const value = p.value;
  if (!await ask({ title: t('confirm.heat.title', { heater }), text: t('confirm.heat.text', { heater, printer: printerName.value, value }),
    yes: t('confirm.heat.yes', { value }), no: t('common.goBack') })) return;
  const r = await run({ key: 'temp:' + key, label: t('act.temperature', { heater }), cmd: 'set_temp', args: { [key]: value },
    okText: t('ok.heat', { heater, value }) });
  if (r.ok) drafts[key] = null;
}

// ---------------------------------------------------------------- speed mode, fan, light
const SPEED_MODES = [1, 2, 3];
const speedDraft = ref<number | null>(null);
const speedOptions = computed(() => SPEED_MODES.map(n => ({ value: n, label: t(`speed.mode.${n}` as 'speed.mode.1') })));
const speedNow = computed(() => (st.value?.speed_mode ? tMaybe(`speed.mode.${st.value.speed_mode}`, t('speed.modeN', { n: st.value.speed_mode })) : '—'));
const speedWhy = computed(() => controlsOff.value || (!printing.value ? t('reason.noPrint') : ''));
async function setSpeed() {
  const mode = speedDraft.value;
  if (mode == null) return;
  const r = await run({ key: 'speed', label: t('act.speed'), cmd: 'set_speed', args: { mode }, okText: t('ok.speed') });
  if (r.ok) speedDraft.value = null;
}
const fanDraft = ref<number | null>(null);
const fanValue = computed(() => parseWhole(fanDraft.value, 0, 100));
async function setFan() {
  const value = fanValue.value;
  if (value == null) return;
  const r = await run({ key: 'fan', label: t('act.fan'), cmd: 'set_fan', args: { pct: value }, okText: t('ok.fan', { value }) });
  if (r.ok) fanDraft.value = null;
}
const setLight = (on: boolean) => run({ key: 'light', label: t('act.light'), cmd: 'set_light', args: { on } });
</script>

<template>
  <section class="kc-card" aria-labelledby="status-h">
    <h2 id="status-h">{{ t('status.title') }}</h2>
    <div class="kc-row">
      <strong data-test="state">{{ stateText }}</strong><span class="kc-spacer" />
      <span v-if="st?.layer" class="oui-meta">{{ t('status.layer', { n: st.layer, total: st.total_layers || '?' }) }}</span>
    </div>
    <ProgressBar :value="pct" :show-value="false" style="height: 8px; margin: 8px 0" :aria-label="t('status.progress')" />
    <div v-if="st?.filename" class="oui-meta st-file">{{ st.filename }}<template v-if="printing"> · {{ fmt.number(pct) }}%</template></div>
    <dl v-if="printing" class="st-kv">
      <dt>{{ t('status.elapsed') }}</dt><dd>{{ fmt.duration(st?.elapsed_s) }}</dd>
      <dt>{{ t('status.left') }}</dt><dd>{{ st?.remaining_s ? fmt.duration(st.remaining_s) : '—' }}</dd>
    </dl>

    <div class="st-controls" role="group" :aria-label="t('status.controls')">
      <div class="kc-row">
        <Button severity="secondary" outlined :disabled="!!pauseWhy" :loading="tracker.isBusy('pause')" data-focus-key="pause" data-test="pause" @click="pause">
          <Icon name="icon/pause" /><span>{{ t('act.pause') }}</span></Button>
        <Button severity="secondary" outlined :disabled="!!resumeWhy" :loading="tracker.isBusy('resume')" data-focus-key="resume" data-test="resume" @click="resume">
          <Icon name="icon/resume" /><span>{{ t('act.resume') }}</span></Button>
        <Button severity="danger" outlined :disabled="!!stopWhy" :loading="tracker.isBusy('stop')" data-focus-key="stop" data-test="stop" @click="stop">
          <Icon name="icon/cancel" /><span>{{ t('act.stop') }}</span></Button>
      </div>
      <p v-if="controlsOff" class="kc-why" data-test="controls-why">{{ t('reason.controlsOff', { reason: controlsOff }) }}</p>
      <p v-else-if="pauseWhy && resumeWhy && stopWhy" class="kc-why" data-test="print-why">{{ t('reason.noPrint') }}</p>
    </div>

    <h3 class="st-h3"><Icon name="icon/temperature" /> {{ t('temps.title') }}</h3>
    <div class="st-temps">
      <div v-for="h in heaters" :key="h.key" class="st-temp" :data-heater-row="h.key">
        <span class="st-tlabel"><Icon :name="h.badge" :size="20" /> {{ h.label }}</span>
        <span class="kc-num st-read">{{ t('temps.reading', { temp: reading(h.temp), target: reported && h.target != null ? fmt.number(h.target) : '—' }) }}</span>
        <InputNumber :model-value="drafts[h.key]" :input-id="'temp-' + h.key" :min="0" :max="h.max" :use-grouping="false" :allow-empty="true"
                     input-class="st-input" :placeholder="t('temps.range', { min: 0, max: h.max })" :aria-label="t('temps.target', { heater: h.label })"
                     :aria-describedby="'temp-why-' + h.key" :invalid="parsed(h.key, h.max).kind === 'invalid'" :disabled="!!heatOff"
                     @input="e => (drafts[h.key] = asNumber(e.value))" @update:model-value="v => (drafts[h.key] = v)"
                     @keydown.enter="setTemp(h.key, h.label, h.max)" />
        <Button severity="secondary" outlined :label="t('temps.set')" :aria-label="t('temps.setFor', { heater: h.label })" :disabled="!!setWhy(h.key, h.max)"
                :loading="tracker.isBusy('temp:' + h.key)" :data-focus-key="'set-' + h.key" :data-set="h.key" @click="setTemp(h.key, h.label, h.max)" />
        <Button severity="secondary" outlined :label="t('temps.off')" :aria-label="t('temps.offFor', { heater: h.label })"
                :disabled="!!heatOff || tracker.isBusy('temp:' + h.key)" :data-focus-key="'off-' + h.key" :data-off="h.key" @click="turnOff(h.key, h.label)" />
        <span :id="'temp-why-' + h.key" class="kc-why st-why" :class="{ 'kc-err': parsed(h.key, h.max).kind === 'invalid' }">
          {{ parsed(h.key, h.max).kind === 'invalid' ? t('temps.invalid', { min: 0, max: h.max }) : heatOff && !controlsOff ? heatOff : '' }}</span>
      </div>
    </div>

    <div class="kc-row st-line">
      <label id="speed-l">{{ t('speed.label') }}</label>
      <Select v-model="speedDraft" :options="speedOptions" option-label="label" option-value="value" :placeholder="speedNow" aria-labelledby="speed-l"
              :disabled="!!speedWhy" class="st-select" data-test="speed" />
      <Button severity="secondary" outlined :label="t('common.apply')" :disabled="!!speedWhy || speedDraft == null" :loading="tracker.isBusy('speed')"
              data-focus-key="speed" @click="setSpeed" />
      <span v-if="speedWhy && !controlsOff" class="kc-why">{{ speedWhy }}</span>
    </div>
    <div class="kc-row st-line">
      <Icon name="icon/fan" /><label for="fan">{{ t('fan.label') }}</label>
      <InputNumber :model-value="fanDraft" input-id="fan" :min="0" :max="100" :step="5" suffix=" %" :use-grouping="false" :allow-empty="true"
                   :placeholder="reported && st ? `${fmt.number(st.fan_pct)} %` : '—'" :disabled="!!controlsOff" input-class="st-input" aria-describedby="fan-why"
                   @input="e => (fanDraft = asNumber(e.value))" @update:model-value="v => (fanDraft = v)" @keydown.enter="setFan" />
      <Button severity="secondary" outlined :label="t('fan.set')" :disabled="!!controlsOff || fanValue == null" :loading="tracker.isBusy('fan')"
              data-focus-key="fan" @click="setFan" />
      <span id="fan-why" class="kc-why">{{ fanDraft != null && fanValue == null ? t('fan.invalid') : '' }}</span>
    </div>
    <div class="kc-row st-line">
      <Checkbox input-id="light" binary :model-value="!!st?.light_on" :disabled="!!controlsOff || tracker.isBusy('light')" @update:model-value="setLight" />
      <label for="light"><Icon name="icon/chamber-light" /> {{ t('light.label') }}</label>
    </div>

    <MotionPanel />
  </section>
</template>

<style scoped>
.st-file { overflow-wrap: anywhere; }
.st-kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 8px 0; }
.st-kv dt { color: var(--oui-muted); } .st-kv dd { margin: 0; }
.st-controls { margin: 12px 0; display: grid; gap: 8px; }
.st-h3 { display: flex; align-items: center; gap: 6px; margin: 16px 0 8px; }
.st-temps { display: grid; gap: 8px; }
.st-temp { display: grid; grid-template-columns: 96px minmax(96px, auto) 110px auto auto; align-items: center; gap: 8px; }
.st-why { grid-column: 1 / -1; }
.st-why:empty { display: none; }
.st-tlabel { display: inline-flex; align-items: center; gap: 4px; font-weight: 600; }
.st-line { margin-top: 12px; }
.st-select { min-width: 180px; }
:deep(.st-input) { width: 110px; }
@media (max-width: 560px) {
  .st-temp { grid-template-columns: minmax(0, 1fr) auto auto; }
  .st-read { grid-column: 1 / -1; }
  :deep(.st-input), :deep(.st-input input) { width: 100%; min-width: 0; }
}
</style>
