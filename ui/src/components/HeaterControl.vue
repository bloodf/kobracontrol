<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import InputNumber from 'primevue/inputnumber';
import { OuiIcon, OuiSpark, type OuiTone } from '../../shared/src/components';
import { bed, nozzle } from '../../shared/src/icons';
import { s, run, tracker, controlsOff, printerName, reported, stale } from '../app/store';
import { ask } from '../core/dialog';
import { t, fmt, locale } from '../core/i18n';
import { acceptDot } from '../core/decimal-input';
import { heaterPhase, parseTarget } from '../core/logic';

// '.' and the locale's own sign both type a decimal (PrimeVue alone reads only the locale's; '100.4' became 1004).
const dot = computed(() => acceptDot(locale.value));

// One heater: what it reads, what it is set to, and the field to change it. Safety rules kept here: a blank field
// never sends 0, an out-of-range value is refused with the real limit from config (not clamped), heating always asks
// first, Off needs no question, and nothing is sent while the printer doesn't allow heating (`heatWhy`).
// foundation-gap: OuiSetpoint (4.0.1) owns its draft, has no v-model, no confirm hook before `set`, no refusal
// message for an out-of-range value and no id on its field, so these rules can't run inside it. 4.0.2 should add
// v-model, an async `before-set` guard that may cancel, `inputId` and an error line.
const props = defineProps<{ id: 'nozzle' | 'bed'; heatWhy: string; whyId?: string }>();
const name = computed(() => t(props.id === 'bed' ? 'temps.bed' : 'temps.nozzle'));
const temp = computed(() => (props.id === 'bed' ? s.status?.bed_temp : s.status?.nozzle_temp));
const target = computed(() => (props.id === 'bed' ? s.status?.bed_target : s.status?.nozzle_target));
const max = computed(() => (props.id === 'bed' ? s.limits.bed_max : s.limits.nozzle_max));
const key = 'temp:' + props.id;

// InputNumber commits its model on blur; the typed value is tracked on every input so the buttons react at once.
const draft = ref<number | null>(null);
const asNumber = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const parsed = computed(() => parseTarget(draft.value, max.value));
const invalid = computed(() => parsed.value.kind === 'invalid');
const setOff = computed(() => !!props.heatWhy || parsed.value.kind === 'empty' || invalid.value || tracker.isBusy(key));
const describedBy = computed(() => (invalid.value ? 'temp-why-' + props.id : props.whyId));

// Numbers are real only after the printer has reported once: blank is a dash, never 0. Last known values lose their colour.
const phase = computed(() => (stale.value || !reported.value ? null : heaterPhase(temp.value, target.value)));
const tone = computed<OuiTone>(() => (phase.value ? ({ heating: 'orange', target: 'success', cooling: 'sky', off: 'sky' } as const)[phase.value] : 'neutral'));
const reading = computed(() => (reported.value && temp.value != null ? fmt.number(temp.value, 1) : '—'));
const targetText = computed(() => (reported.value && target.value ? t('temps.targetIs', { target: fmt.number(target.value, 1) })
  : reported.value && target.value === 0 ? t('temps.heaterOff') : t('temps.targetIs', { target: '—' })));

async function turnOff() {
  await run({ key, label: t('act.temperature', { heater: name.value }), cmd: 'set_temp', args: { [props.id]: 0 }, okText: t('ok.off', { heater: name.value }) });
}
async function setTemp() {
  const p = parsed.value;
  if (props.heatWhy) return;
  if (p.kind === 'off') return turnOff();
  if (p.kind !== 'heat') return;
  const value = p.value;
  if (!await ask({ title: t('confirm.heat.title', { heater: name.value }), text: t('confirm.heat.text', { heater: name.value, printer: printerName.value, value }),
    yes: t('confirm.heat.yes', { value }), no: t('common.goBack') })) return;
  const r = await run({ key, label: t('act.temperature', { heater: name.value }), cmd: 'set_temp', args: { [props.id]: value },
    okText: t('ok.heat', { heater: name.value, value }) });
  if (r.ok) draft.value = null;
}
</script>

<template>
  <div class="kc-heat" :data-heater-row="id">
    <div class="kc-heat-row">
      <span class="kc-line-label"><OuiIcon :icon="id === 'bed' ? bed : nozzle" :size="14" tile :tone="tone" />{{ name }}</span>
      <span class="kc-heat-read oui-num" :data-tone="tone">
        <strong>{{ reading }}<span class="kc-heat-unit">°C</span></strong>
        <span class="oui-meta">{{ targetText }}<template v-if="phase && phase !== 'off'"> · <span class="kc-heat-phase">{{ t(`temps.phase.${phase}`) }}</span></template></span>
      </span>
      <OuiSpark v-if="(s.history[id] ?? []).length > 1" class="kc-heat-spark" :values="s.history[id] ?? []" :tone="tone" :target="target || null" :width="88" :height="28" :label="t('temps.history', { heater: name })" />
      <span v-else class="kc-heat-spark" aria-hidden="true" />
      <span class="kc-heat-set">
        <InputNumber v-bind="dot" :locale="locale" :max-fraction-digits="1" :model-value="draft" :input-id="'temp-' + id" :min="0" :max="max" :use-grouping="false" :allow-empty="true" size="small"
                     :input-style="{ width: '72px' }" :placeholder="t('temps.range', { min: 0, max })" :aria-label="t('temps.target', { heater: name })"
                     :pt="{ pcInputText: { root: { 'aria-describedby': describedBy } } }" :invalid="invalid" :disabled="!!heatWhy"
                     @input="e => (draft = asNumber(e.value))" @update:model-value="v => (draft = v)" @keydown.enter="setTemp" />
        <Button severity="secondary" size="small" :label="t('temps.set')" :aria-label="t('temps.setFor', { heater: name })" :disabled="setOff" :aria-describedby="describedBy"
                :loading="tracker.isBusy(key)" :data-focus-key="'set-' + id" :data-set="id" @click="setTemp" />
        <Button severity="secondary" text size="small" :label="t('temps.off')" :aria-label="t('temps.offFor', { heater: name })" :aria-describedby="whyId"
                :disabled="!!heatWhy || tracker.isBusy(key)" :data-focus-key="'off-' + id" :data-off="id" @click="turnOff" />
      </span>
    </div>
    <p :id="'temp-why-' + id" class="kc-why" data-tone="danger" role="status">{{ invalid ? t('temps.invalid', { min: 0, max }) : '' }}</p>
  </div>
</template>

<style>
.kc-heat { container: kc-heat / inline-size; }
.kc-heat-row { display: grid; grid-template-columns: minmax(84px, 1fr) minmax(108px, auto) minmax(0, 1fr) auto; align-items: center; gap: var(--oui-s2) var(--oui-s3); min-height: 52px; }
.kc-heat-read { display: grid; line-height: 1.25; }
.kc-heat-read strong { font-size: var(--oui-text-xl); line-height: 1.15; font-weight: 700; letter-spacing: -.01em; color: var(--oui-tone); }
.kc-heat-unit { margin-inline-start: .2em; font-size: .6em; font-weight: 600; }
.kc-heat-phase { font-weight: 600; color: var(--oui-tone); }
.kc-heat-spark { justify-self: start; }
.kc-heat-set { display: inline-flex; align-items: center; gap: var(--oui-s1); }
@container kc-heat (max-width: 520px) { .kc-heat-spark { display: none; } .kc-heat-row { grid-template-columns: minmax(84px, 1fr) minmax(96px, 1fr) auto; } }
@container kc-heat (max-width: 400px) { .kc-heat-row { grid-template-columns: minmax(0, 1fr) auto; } .kc-heat-set { grid-column: 1 / -1; justify-content: flex-end; } }
</style>
