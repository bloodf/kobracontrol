<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import InputNumber from 'primevue/inputnumber';
import Select from 'primevue/select';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiControlRow, OuiEmpty, OuiPanel, OuiStatus } from '../../shared/src/components';
import { fan, light, speed, thermometer } from '../../shared/src/icons';
import HeaterControl from './HeaterControl.vue';
import { s, run, tracker, busy, controlsOff, link, printing, reported, stale, whyId } from '../app/store';
import { t, tMaybe, fmt, locale } from '../core/i18n';
import { acceptDot } from '../core/decimal-input';
import { parseWhole } from '../core/logic';

// '.' and the locale's own sign both type a decimal (PrimeVue alone reads only the locale's; '100.4' became 1004).
const dot = computed(() => acceptDot(locale.value));

// One Controls module, grouped by task: Temperature (the two heaters) and Machine (fan, speed mode, light), every row
// on the same columns. Why a control is off is said once, in the page's banner (#kc-why, or #kc-busy when the printer
// doesn't allow heating now); the speed mode's own condition (it needs a running print) is behind the module's (i).
const st = computed(() => s.status);
const heatOff = computed(() => !!controlsOff.value || busy.value.heat);
const offId = computed(() => whyId(false));
const asNumber = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

const SPEED_MODES = [1, 2, 3];
const speedDraft = ref<number | null>(null);
const speedOptions = computed(() => SPEED_MODES.map(n => ({ value: n, label: t(`speed.mode.${n}` as 'speed.mode.1') })));
const speedNow = computed(() => (st.value?.speed_mode ? tMaybe(`speed.mode.${st.value.speed_mode}`, t('speed.modeN', { n: st.value.speed_mode })) : '—'));
const speedWhy = computed(() => controlsOff.value || (!printing.value ? t('reason.noPrint') : ''));
const fanNow = computed(() => (reported.value && st.value ? fmt.percent(st.value.fan_pct) : '—'));
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
  <OuiPanel :title="t('controls.title')" :icon="thermometer" tone="orange" :flush="!st" :hint="t('controls.hint')" data-test="temps">
    <template v-if="stale" #meta><OuiStatus state="stale">{{ t('status.lastKnownShort') }}</OuiStatus></template>
    <OuiEmpty v-if="!st" compact :state="link === 'offline' ? 'offline' : 'loading'" :title="t('status.noStatus')" />
    <div v-else class="oui-controls">
      <div class="oui-controls-group">
        <p class="oui-label">{{ t('controls.temperature') }}</p>
        <HeaterControl id="nozzle" :off="heatOff" :why-id="whyId(busy.heat)" />
        <HeaterControl id="bed" :off="heatOff" :why-id="whyId(busy.heat)" />
      </div>

      <div class="oui-controls-group">
        <p class="oui-label">{{ t('controls.machine') }}</p>
        <OuiControlRow :label="t('fan.label')" :icon="fan" tone="sky" for="fan">
          <template #value><span v-if="fanDraft != null && fanValue == null" id="fan-why" class="kc-err" role="status">{{ t('fan.invalid') }}</span><template v-else>{{ fanNow }}</template></template>
          <InputNumber v-bind="dot" :locale="locale" :max-fraction-digits="1" :model-value="fanDraft" input-id="fan" :min="0" :max="100" :step="5" :suffix="fmt.percent('')" :use-grouping="false" :allow-empty="true" size="small"
                       placeholder="0–100" :disabled="!!controlsOff" :input-style="{ width: '72px' }"
                       :pt="{ pcInputText: { root: { 'aria-describedby': offId ?? 'fan-why' } } }"
                       @input="e => (fanDraft = asNumber(e.value))" @update:model-value="v => (fanDraft = v)" @keydown.enter="setFan" />
          <Button severity="secondary" size="small" :label="t('fan.set')" :disabled="!!controlsOff || fanValue == null" :aria-describedby="offId" :loading="tracker.isBusy('fan')"
                  data-focus-key="fan" @click="setFan" />
        </OuiControlRow>

        <OuiControlRow :label="t('speed.label')" :icon="speed" tone="cobalt">
          <span v-if="speedWhy && !controlsOff" id="speed-why" class="oui-sr" data-test="speed-why">{{ speedWhy }}</span>
          <Select v-model="speedDraft" :options="speedOptions" option-label="label" option-value="value" :placeholder="speedNow" :aria-label="t('speed.label')" size="small"
                  :disabled="!!speedWhy" class="kc-speed" data-test="speed" />
          <Button severity="secondary" size="small" :label="t('common.apply')" :disabled="!!speedWhy || speedDraft == null" :aria-describedby="speedWhy ? (offId ?? 'speed-why') : undefined"
                  :loading="tracker.isBusy('speed')" data-focus-key="speed" @click="setSpeed" />
        </OuiControlRow>

        <OuiControlRow :label="t('light.label')" :icon="light" tone="lime" :value="st.light_on ? t('common.on') : t('common.off')" for="light">
          <ToggleSwitch input-id="light" :model-value="!!st.light_on" :disabled="!!controlsOff || tracker.isBusy('light')" :aria-describedby="offId" @update:model-value="setLight" />
        </OuiControlRow>
      </div>
    </div>
  </OuiPanel>
</template>

<style>
.kc-speed { min-width: 124px; }
</style>
