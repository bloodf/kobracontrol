<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import InputNumber from 'primevue/inputnumber';
import { OuiIcon, OuiStatus } from '@orca-plugins/ui-foundation/src/components';
import { drop, flame } from '@orca-plugins/ui-foundation/src/icons';
import { run, tracker, busy, controlsOff, printerName, stale, whyId } from '../app/store';
import { ask } from '../core/dialog';
import { t, fmt, locale } from '../core/i18n';
import { acceptDot } from '../core/decimal-input';
import { parseWhole } from '../core/logic';
import type { AceUnit } from '../app/types';

// '.' and the locale's own sign both type a decimal (PrimeVue alone reads only the locale's; '100.4' became 1004).
const dot = computed(() => acceptDot(locale.value));

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
// Off for the page's reason (#kc-why) or because the printer does not allow heating now (#kc-busy); a value outside
// the printer's limits is refused here, with the limits.
const startOff = computed(() => !!controlsOff.value || busy.value.heat || tempValue.value == null || minutesValue.value == null || tracker.isBusy(`dry:${props.unit.id}`));
const invalid = computed(() => ((temp.value != null && tempValue.value == null) ? t('dry.tempInvalid', TEMP)
  : (minutes.value != null && minutesValue.value == null) ? t('dry.timeInvalid', MINUTES) : ''));
const offId = computed(() => whyId(busy.value.heat));

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
  <div class="kc-dry" :data-unit="unit.id" :data-stale="stale || undefined" :role="drying ? 'status' : undefined" :data-test="drying ? 'drying' : undefined">
    <template v-if="drying">
      <OuiStatus :state="stale ? 'stale' : 'busy'">{{ t('dry.running', { temp: fmt.number(d.target_temp) }) }}</OuiStatus>
      <span v-if="inside != null" class="oui-num"><strong>{{ t('dry.now', { temp: fmt.number(inside, 1) }) }}</strong></span>
      <span class="oui-num oui-muted">{{ d.remain_time ? t('dry.left', { time: fmt.duration(d.remain_time * 60) }) : '—' }}</span>
      <span v-if="humidity != null" class="oui-num oui-muted"><OuiIcon :icon="drop" :size="13" tone="sky" class="kc-drop" />{{ t('dry.humidity', { value: fmt.number(humidity) }) }}</span>
      <span class="oui-spacer" />
      <Button severity="secondary" size="small" :label="t('dry.stop')" :aria-label="t('dry.stopLabel', { ace: label })" :disabled="!!controlsOff" :aria-describedby="whyId(false)"
              :loading="tracker.isBusy(`dry:${unit.id}`)" :data-focus-key="`dry-stop:${unit.id}`" :data-dry-stop="unit.id" @click="stop" />
    </template>
    <template v-else>
      <OuiIcon :icon="flame" :size="14" tile tone="orange" /><span class="oui-strong">{{ t('dry.title') }}</span>
      <span v-if="humidity != null" class="oui-num oui-muted" data-test="unit-humidity"><OuiIcon :icon="drop" :size="13" tone="sky" class="kc-drop" />{{ t('dry.humidity', { value: fmt.number(humidity) }) }}</span>
      <span :id="`dry-why-${unit.id}`" class="kc-err" role="status">{{ invalid }}</span>
      <span class="oui-spacer" />
      <InputNumber v-bind="dot" :locale="locale" :max-fraction-digits="1" :model-value="temp" :input-id="`dry-t-${unit.id}`" :min="TEMP.min" :max="TEMP.max" :use-grouping="false" suffix=" °C" :allow-empty="true" size="small"
                   :placeholder="`${TEMP.min}–${TEMP.max} °C`" :input-style="{ width: '92px' }" :aria-label="t('dry.temp')" :disabled="!!controlsOff || busy.heat" :pt="{ pcInputText: { root: { 'aria-describedby': offId ?? `dry-why-${unit.id}` } } }"
                   @input="e => (temp = asNumber(e.value))" @update:model-value="v => (temp = v)" />
      <InputNumber v-bind="dot" :locale="locale" :max-fraction-digits="1" :model-value="minutes" :input-id="`dry-m-${unit.id}`" :min="MINUTES.min" :max="MINUTES.max" :use-grouping="false" :suffix="' ' + t('unit.min')" :allow-empty="true" size="small"
                   :placeholder="`${MINUTES.min}–${MINUTES.max} ${t('unit.min')}`" :input-style="{ width: '112px' }" :aria-label="t('dry.time')" :disabled="!!controlsOff || busy.heat" :pt="{ pcInputText: { root: { 'aria-describedby': offId ?? `dry-why-${unit.id}` } } }"
                   @input="e => (minutes = asNumber(e.value))" @update:model-value="v => (minutes = v)" />
      <Button severity="secondary" size="small" :label="t('dry.start')" :aria-label="t('dry.startLabel', { ace: label })" :disabled="startOff" :aria-describedby="offId ?? `dry-why-${unit.id}`"
              :loading="tracker.isBusy(`dry:${unit.id}`)" :data-focus-key="`dry-start:${unit.id}`" :data-dry-start="unit.id" @click="start" />
    </template>
  </div>
</template>

<style>
/* One ACE's drying, as a strip over its slots: neutral, with the state as a chip. Heat is the only colour in it. */
.kc-dry { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oui-s2) var(--oui-s3); min-height: 40px; padding: 4px var(--oui-s2); border-radius: var(--oui-radius);
  background: var(--oui-raised); box-shadow: inset 0 0 0 1px var(--oui-border); }
.kc-dry strong { color: var(--oui-orange); }
.kc-dry[data-stale] strong { color: var(--oui-muted); }
.kc-drop { display: inline-block; vertical-align: -2px; margin-inline-end: 3px; }
</style>
