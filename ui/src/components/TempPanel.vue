<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import InputNumber from 'primevue/inputnumber';
import Select from 'primevue/select';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiIcon, OuiPanel, OuiStatus } from '../../shared/src/components';
import { fan, light, speed, thermometer } from '../../shared/src/icons';
import HeaterControl from './HeaterControl.vue';
import { s, run, tracker, controlsOff, printing, reported, stale } from '../app/store';
import { t, tMaybe, fmt, locale } from '../core/i18n';
import { acceptDot } from '../core/decimal-input';
import { parseWhole } from '../core/logic';

// '.' and the locale's own sign both type a decimal (PrimeVue alone reads only the locale's; '100.4' became 1004).
const dot = computed(() => acceptDot(locale.value));

// Temperature and air: the two heaters, then fan, speed mode and light as rows. A reason that concerns this panel only
// (the printer doesn't allow heating) is said once, in its footer; the page-level reasons are under the app bar (#kc-why).
const st = computed(() => s.status);
const heatNo = computed(() => !controlsOff.value && !!st.value && !st.value.can.heat);
const heatWhy = computed(() => controlsOff.value || (heatNo.value ? t('reason.noHeat') : ''));
const whyId = computed(() => (controlsOff.value ? 'kc-why' : heatNo.value ? 'heat-why' : undefined));
const offId = computed(() => (controlsOff.value ? 'kc-why' : undefined));
const asNumber = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

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
  <OuiPanel :title="t('temps.panel')" :icon="thermometer" tone="orange" data-test="temps">
    <template v-if="stale" #meta><OuiStatus state="stale">{{ t('status.lastKnownShort') }}</OuiStatus></template>
    <div class="kc-rows">
      <HeaterControl id="nozzle" :heat-why="heatWhy" :why-id="whyId" />
      <HeaterControl id="bed" :heat-why="heatWhy" :why-id="whyId" />

      <div class="kc-line">
        <label for="fan" class="kc-line-label"><OuiIcon :icon="fan" :size="14" tile tone="sky" />{{ t('fan.label') }}</label>
        <InputNumber v-bind="dot" :locale="locale" :max-fraction-digits="1" :model-value="fanDraft" input-id="fan" :min="0" :max="100" :step="5" :suffix="fmt.percent('')" :use-grouping="false" :allow-empty="true" size="small"
                     :placeholder="reported && st ? fmt.percent(st.fan_pct) : '—'" :disabled="!!controlsOff" :input-style="{ width: '72px' }"
                     :pt="{ pcInputText: { root: { 'aria-describedby': controlsOff ? 'kc-why' : 'fan-why' } } }"
                     @input="e => (fanDraft = asNumber(e.value))" @update:model-value="v => (fanDraft = v)" @keydown.enter="setFan" />
        <Button severity="secondary" size="small" :label="t('fan.set')" :disabled="!!controlsOff || fanValue == null" :aria-describedby="offId" :loading="tracker.isBusy('fan')"
                data-focus-key="fan" @click="setFan" />
        <span id="fan-why" class="kc-why" data-tone="danger">{{ fanDraft != null && fanValue == null ? t('fan.invalid') : '' }}</span>
      </div>

      <div class="kc-line">
        <span id="speed-l" class="kc-line-label"><OuiIcon :icon="speed" :size="14" tile tone="cobalt" />{{ t('speed.label') }}</span>
        <Select v-model="speedDraft" :options="speedOptions" option-label="label" option-value="value" :placeholder="speedNow" aria-labelledby="speed-l" size="small"
                :disabled="!!speedWhy" class="kc-speed" data-test="speed" />
        <Button severity="secondary" size="small" :label="t('common.apply')" :disabled="!!speedWhy || speedDraft == null" :aria-describedby="speedWhy ? (controlsOff ? 'kc-why' : 'speed-why') : undefined"
                :loading="tracker.isBusy('speed')" data-focus-key="speed" @click="setSpeed" />
        <span v-if="speedWhy && !controlsOff" id="speed-why" class="kc-why" data-test="speed-why">{{ speedWhy }}</span>
      </div>

      <div class="kc-line">
        <label for="light" class="kc-line-label"><OuiIcon :icon="light" :size="14" tile tone="lime" />{{ t('light.label') }}</label>
        <ToggleSwitch input-id="light" :model-value="!!st?.light_on" :disabled="!!controlsOff || tracker.isBusy('light')" :aria-describedby="offId" @update:model-value="setLight" />
      </div>
    </div>
    <template v-if="heatNo" #footer><p id="heat-why" class="oui-meta" data-test="heat-why">{{ t('reason.noHeat') }}.</p></template>
  </OuiPanel>
</template>

<style>
.kc-speed { min-width: 140px; }
</style>
