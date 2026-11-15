<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import InputNumber from 'primevue/inputnumber';
import { OuiIcon, OuiStatus } from '../../shared/src/components';
import { drop, flame } from '../../shared/src/icons';
import { s, run, tracker, controlsOff, printerName, stale } from '../app/store';
import { ask } from '../core/dialog';
import { t, fmt } from '../core/i18n';
import { parseWhole } from '../core/logic';
import type { AceUnit } from '../app/types';

// One ACE's drying strip (running: what it does and Stop drying; idle: temperature, time, Start).
const props = defineProps<{ unit: AceUnit; label: string }>();
// The printer's own limits for drying (30-80 C, 10 min - 24 h).
const TEMP = { min: 30, max: 80 }, MINUTES = { min: 10, max: 1440 };
const drying = computed(() => props.unit.drying.status !== 0);
const d = computed(() => props.unit.drying);
// Box-level readings are the fallback when the drying report has none. drying.duration is not shown: the printer
// reports a constant (86400) while drying, so it says nothing about the real total.
const humidity = computed(() => d.value.humidity ?? props.unit.humidity ?? null);
const inside = computed(() => d.value.current_temp ?? props.unit.temp ?? null);
const temp = ref<number | null>(null);
const minutes = ref<number | null>(null);
const asNumber = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const tempValue = computed(() => parseWhole(temp.value, TEMP.min, TEMP.max));
const minutesValue = computed(() => parseWhole(minutes.value, MINUTES.min, MINUTES.max));
const heatNo = computed(() => !controlsOff.value && !!s.status && !s.status.can.heat);
const startWhy = computed(() => controlsOff.value || (heatNo.value ? t('reason.noHeat') : '') || (tempValue.value == null ? t('dry.tempInvalid', TEMP) : minutesValue.value == null ? t('dry.timeInvalid', MINUTES)
  : tracker.isBusy(`dry:${props.unit.id}`) ? t('reason.pending') : ''));
const hint = computed(() => (heatNo.value ? t('reason.noHeat') : (temp.value != null && tempValue.value == null) ? t('dry.tempInvalid', TEMP)
  : (minutes.value != null && minutesValue.value == null) ? t('dry.timeInvalid', MINUTES) : ''));
const offId = computed(() => (controlsOff.value ? 'kc-why' : undefined));

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
  <div class="kc-unit" :data-unit="unit.id">
    <div v-if="drying" class="kc-dry" :data-stale="stale || undefined" role="status" data-test="drying">
      <OuiStatus :state="stale ? 'stale' : 'busy'">{{ t('dry.running', { temp: fmt.number(d.target_temp) }) }}</OuiStatus>
      <span v-if="inside != null" class="oui-num"><strong>{{ t('dry.now', { temp: fmt.number(inside, 1) }) }}</strong></span>
      <span class="oui-num oui-muted">{{ d.remain_time ? t('dry.left', { time: fmt.duration(d.remain_time * 60) }) : '—' }}</span>
      <span v-if="humidity != null" class="oui-num oui-muted"><OuiIcon :icon="drop" :size="13" tone="sky" class="kc-drop" />{{ t('dry.humidity', { value: fmt.number(humidity) }) }}</span>
      <Button severity="secondary" text size="small" class="kc-dry-end" :label="t('dry.stop')" :aria-label="t('dry.stopLabel', { ace: label })" :disabled="!!controlsOff" :aria-describedby="offId"
              :loading="tracker.isBusy(`dry:${unit.id}`)" :data-focus-key="`dry-stop:${unit.id}`" :data-dry-stop="unit.id" @click="stop" />
    </div>
    <div v-else class="kc-dry" data-idle>
      <span class="kc-dry-title"><OuiIcon :icon="flame" :size="14" tone="orange" />{{ t('dry.title') }}</span>
      <span v-if="humidity != null" class="oui-num oui-muted" data-test="unit-humidity"><OuiIcon :icon="drop" :size="13" tone="sky" class="kc-drop" />{{ t('dry.humidity', { value: fmt.number(humidity) }) }}</span>
      <span class="kc-dry-end kc-dry-form">
        <InputNumber :model-value="temp" :input-id="`dry-t-${unit.id}`" :min="TEMP.min" :max="TEMP.max" :use-grouping="false" suffix=" °C" :allow-empty="true" size="small"
                     :placeholder="`${TEMP.min}–${TEMP.max} °C`" :input-style="{ width: '84px' }" :aria-label="t('dry.temp')" :disabled="!!controlsOff" :pt="{ pcInputText: { root: { 'aria-describedby': offId ?? `dry-why-${unit.id}` } } }"
                     @input="e => (temp = asNumber(e.value))" @update:model-value="v => (temp = v)" />
        <InputNumber :model-value="minutes" :input-id="`dry-m-${unit.id}`" :min="MINUTES.min" :max="MINUTES.max" :use-grouping="false" suffix=" min" :allow-empty="true" size="small"
                     :placeholder="`${MINUTES.min}–${MINUTES.max} min`" :input-style="{ width: '96px' }" :aria-label="t('dry.time')" :disabled="!!controlsOff" :pt="{ pcInputText: { root: { 'aria-describedby': offId ?? `dry-why-${unit.id}` } } }"
                     @input="e => (minutes = asNumber(e.value))" @update:model-value="v => (minutes = v)" />
        <Button severity="secondary" size="small" :label="t('dry.start')" :aria-label="t('dry.startLabel', { ace: label })" :disabled="!!startWhy" :aria-describedby="offId ?? `dry-why-${unit.id}`"
                :loading="tracker.isBusy(`dry:${unit.id}`)" :data-focus-key="`dry-start:${unit.id}`" :data-dry-start="unit.id" @click="start">
          <template #icon><OuiIcon :icon="flame" :size="14" /></template></Button>
      </span>
      <span :id="`dry-why-${unit.id}`" class="kc-why" role="status">{{ hint }}</span>
    </div>
  </div>
</template>

<style>
.kc-unit { display: grid; gap: var(--oui-s2); }
.kc-dry { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oui-s1) var(--oui-s4); min-height: 38px; padding: var(--oui-s1) var(--oui-s1) var(--oui-s1) var(--oui-s2);
  border-radius: var(--oui-radius); background: var(--oui-orange-soft); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--oui-orange) 30%, transparent); }
.kc-dry strong { color: var(--oui-orange); }
.kc-dry[data-idle] { background: var(--oui-raised); box-shadow: inset 0 0 0 1px var(--oui-border); }
.kc-dry[data-stale] { background: var(--oui-raised); box-shadow: inset 0 0 0 1px var(--oui-border); }
.kc-dry[data-stale] strong { color: var(--oui-muted); }
.kc-dry-title { display: inline-flex; align-items: center; gap: var(--oui-s2); font-weight: 600; }
.kc-dry-end { margin-inline-start: auto; }
.kc-dry-form { display: inline-flex; flex-wrap: wrap; align-items: center; gap: var(--oui-s1); }
.kc-dry .kc-why { padding-inline-end: var(--oui-s2); }
.kc-drop { display: inline-block; vertical-align: -1px; margin-inline-end: 3px; }
</style>
