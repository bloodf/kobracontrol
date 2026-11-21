<script setup lang="ts">
import { computed } from 'vue';
import { OuiEmpty, OuiPanel, OuiReadout, OuiSpark } from '@orca-plugins/ui-foundation/src/components';
import { bed, fan, nozzle, thermometer } from '@orca-plugins/ui-foundation/src/icons';
import { s, link, reported, stale } from '../app/store';
import { t, fmt } from '../core/i18n';

// The readings at a glance: nozzle, bed and fan, each with its target and, in a big enough widget, its last ten minutes.
// Small, it is compact: the values only (container query on the widget, below). Its settings say which readings show.
const props = withDefaults(defineProps<{ config?: { nozzle?: boolean; bed?: boolean; fan?: boolean } }>(), { config: () => ({}) });
const st = computed(() => s.status);
const deg = (v?: number) => (reported.value && v != null ? fmt.number(v, 1) : null);
const target = (v?: number) => (!reported.value ? undefined : v ? t('temps.targetIs', { target: fmt.number(v, 0) }) : t('temps.heaterOff'));
const items = computed(() => [
  props.config.nozzle !== false && { id: 'nozzle', icon: nozzle, label: t('temps.nozzle'), value: deg(st.value?.nozzle_temp), unit: '°C', sub: target(st.value?.nozzle_target), history: s.history.nozzle },
  props.config.bed !== false && { id: 'bed', icon: bed, label: t('temps.bed'), value: deg(st.value?.bed_temp), unit: '°C', sub: target(st.value?.bed_target), history: s.history.bed },
  props.config.fan !== false && { id: 'fan', icon: fan, label: t('fan.label'), value: reported.value && st.value ? Math.round(st.value.fan_pct) : null, unit: '%', sub: undefined, history: undefined },
].filter(x => !!x));
</script>
<template>
  <OuiPanel :icon="thermometer" tone="orange" :title="t('widget.temps')" :flush="!st" data-test="temps-card">
    <OuiEmpty v-if="!st" compact :state="link === 'offline' ? 'offline' : 'loading'" :title="t('status.noStatus')" />
    <div v-else class="kc-temps">
      <div v-for="i in items" :key="i.id" class="kc-temp" :data-temp="i.id">
        <OuiReadout :icon="i.icon" :label="i.label" :value="i.value" :unit="i.unit" :sub="i.sub" :stale="stale" size="md" />
        <OuiSpark v-if="(i.history ?? []).length > 1" class="kc-temp-spark" :values="i.history!" tone="orange" :label="i.label" :width="120" :height="32" />
      </div>
    </div>
  </OuiPanel>
</template>
<style>
.kc-temps { display: grid; gap: var(--oui-s3); grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
.kc-temp { display: grid; gap: var(--oui-s2); align-content: start; }
/* Compact in a small widget: the values in one row, without targets and charts. */
@container oui-widget (max-width: 320px) or (max-height: 120px) {
  .kc-temps { grid-template-columns: repeat(auto-fit, minmax(72px, 1fr)); gap: var(--oui-s2); }
  .kc-temp .oui-readout-sub, .kc-temp-spark { display: none; }
}
</style>
