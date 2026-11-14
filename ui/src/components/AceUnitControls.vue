<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import Checkbox from 'primevue/checkbox';
import InputNumber from 'primevue/inputnumber';
import Icon from './Icon.vue';
import { s, run, tracker, controlsOff, printerName } from '../app/store';
import { ask } from '../core/dialog';
import { t, fmt } from '../core/i18n';
import { parseWhole } from '../core/logic';
import type { AceUnit } from '../app/types';

const props = defineProps<{ unit: AceUnit; label: string }>();
// The printer's own limits for drying (30-80 C, 10 min - 24 h).
const TEMP = { min: 30, max: 80 }, MINUTES = { min: 10, max: 1440 };
const drying = computed(() => props.unit.drying.status !== 0);
const d = computed(() => props.unit.drying);
const temp = ref<number | null>(null);
const minutes = ref<number | null>(null);
const asNumber = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const tempValue = computed(() => parseWhole(temp.value, TEMP.min, TEMP.max));
const minutesValue = computed(() => parseWhole(minutes.value, MINUTES.min, MINUTES.max));
const startWhy = computed(() => controlsOff.value || (s.status && !s.status.can.heat ? t('reason.noHeat') : '') || (tempValue.value == null ? t('dry.tempInvalid', TEMP) : minutesValue.value == null ? t('dry.timeInvalid', MINUTES)
  : tracker.isBusy(`dry:${props.unit.id}`) ? t('reason.pending') : ''));

const setAuto = (on: boolean) => run({ key: `auto:${props.unit.id}`, label: t('act.autoFeed', { ace: props.label }), cmd: 'auto_feed', args: { ace: props.unit.id, on } });
async function start() {
  const tp = tempValue.value, mn = minutesValue.value;
  if (tp == null || mn == null) return;
  if (!await ask({ title: t('confirm.dry.title', { ace: props.label }), text: t('confirm.dry.text', { ace: props.label, temp: tp, time: fmt.duration(mn * 60), printer: printerName.value }),
    yes: t('confirm.dry.yes', { ace: props.label }), no: t('common.goBack') })) return;
  await run({ key: `dry:${props.unit.id}`, label: t('act.dryStart', { ace: props.label }), cmd: 'dry_start', args: { aces: [props.unit.id], temp: tp, minutes: mn },
    okText: t('ok.dryStart', { ace: props.label }) });
}
const stop = () => run({ key: `dry:${props.unit.id}`, label: t('act.dryStop', { ace: props.label }), cmd: 'dry_stop', args: { aces: [props.unit.id] }, okText: t('ok.dryStop', { ace: props.label }) });
</script>

<template>
  <div class="au" :data-unit="unit.id">
    <div class="kc-row">
      <Checkbox :input-id="`auto-${unit.id}`" binary :model-value="unit.auto_feed" :disabled="!!controlsOff || tracker.isBusy(`auto:${unit.id}`)"
                :data-auto="unit.id" @update:model-value="setAuto" />
      <label :for="`auto-${unit.id}`">{{ t('ace.autoFeed') }}</label>
    </div>
    <div v-if="drying" class="au-dry" role="status" data-test="drying">
      <div class="kc-row"><Icon name="icon/dry" /><strong>{{ t('dry.running', { temp: fmt.number(d.target_temp) }) }}</strong>
        <span class="kc-num">{{ d.remain_time ? t('dry.left', { time: fmt.duration(d.remain_time * 60) }) : '—' }}</span></div>
      <div v-if="d.humidity != null || d.current_temp != null" class="oui-meta">
        <template v-if="d.current_temp != null">{{ t('dry.now', { temp: fmt.number(d.current_temp, 1) }) }}</template>
        <template v-if="d.humidity != null && d.current_temp != null"> · </template>
        <template v-if="d.humidity != null">{{ t('dry.humidity', { value: fmt.number(d.humidity) }) }}</template></div>
      <Button severity="secondary" outlined size="small" :label="t('dry.stop')" :aria-label="t('dry.stopLabel', { ace: label })" :disabled="!!controlsOff"
              :loading="tracker.isBusy(`dry:${unit.id}`)" :data-focus-key="`dry-stop:${unit.id}`" :data-dry-stop="unit.id" @click="stop" />
    </div>
    <div v-else class="au-dry">
      <div class="kc-row"><Icon name="icon/dry" /><strong>{{ t('dry.title') }}</strong></div>
      <div class="kc-row">
        <label :for="`dry-t-${unit.id}`">{{ t('dry.temp') }}</label>
        <InputNumber :model-value="temp" :input-id="`dry-t-${unit.id}`" :min="TEMP.min" :max="TEMP.max" :use-grouping="false" suffix=" °C" :allow-empty="true"
                     :placeholder="`${TEMP.min}–${TEMP.max}`" input-class="au-input" :disabled="!!controlsOff"
                     @input="e => (temp = asNumber(e.value))" @update:model-value="v => (temp = v)" />
        <label :for="`dry-m-${unit.id}`">{{ t('dry.time') }}</label>
        <InputNumber :model-value="minutes" :input-id="`dry-m-${unit.id}`" :min="MINUTES.min" :max="MINUTES.max" :use-grouping="false" suffix=" min" :allow-empty="true"
                     :placeholder="`${MINUTES.min}–${MINUTES.max}`" input-class="au-input" :disabled="!!controlsOff"
                     @input="e => (minutes = asNumber(e.value))" @update:model-value="v => (minutes = v)" />
        <Button size="small" :label="t('dry.start')" :aria-label="t('dry.startLabel', { ace: label })" :disabled="!!startWhy" :loading="tracker.isBusy(`dry:${unit.id}`)"
                :data-focus-key="`dry-start:${unit.id}`" :data-dry-start="unit.id" @click="start" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.au { display: grid; gap: 8px; margin: 8px 0; }
.au-dry { display: grid; gap: 6px; padding: 8px 12px; border: 1px solid var(--oui-border); border-radius: 8px; }
:deep(.au-input) { width: 104px; }
</style>
