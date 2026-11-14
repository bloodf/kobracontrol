<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import Select from 'primevue/select';
import Icon from './Icon.vue';
import LevelBar from './LevelBar.vue';
import { spoolFraction, spoolPaint } from '../core/spool-level';
import { s, run, tracker, controlsOff, loadSpools } from '../app/store';
import { config } from '../app/settings';
import { ask } from '../core/dialog';
import { t, fmt } from '../core/i18n';
import { family, groupSlots, hexOf } from '../core/logic';
import type { Slot, Spool } from '../app/types';

const slots = computed(() => s.status?.slots ?? []);
const groups = computed(() => groupSlots(slots.value));
const groupName = (boxId: number) => (boxId < 0 ? t('ace.head') : t('ace.unit', { n: boxId + 1 }));
const nameOf = (sl: Slot) => `${groupName(sl.box_id)} · ${t('slot.name', { n: sl.index + 1 })}`;
const configured = computed(() => !!(config.value?.settings.spoolman_url));
// One visible spool source per screen: when Spooler's stock uses the same Spoolman, say so.
const source = computed(() => {
  if (s.spoolsError) return t('sm.error', { error: s.spoolsError });
  if (!s.spoolsLoaded) return configured.value ? t('sm.notLoaded') : t('sm.notConfigured');
  const n = s.spools.length;
  return s.stock?.spooler.state === 'active' && s.stock.same_spoolman === true ? t('sm.same', { n }) : t('sm.count', { n });
});
const label = (sp: Spool) => t('pick.option', { id: sp.id, vendor: sp.vendor, name: sp.name, material: sp.material, grams: fmt.grams(sp.remaining) });
const swatch = (sp: Spool | null) => (!sp ? 'transparent' : spoolPaint(sp.colour, sp.colours) || 'transparent');
const find = (id: number | null) => (id == null ? null : s.spools.find(x => x.id === id) ?? null);
const fractionOf = (sp: Spool | null) => (sp ? spoolFraction(sp.remaining, sp.initial) : null);

function groupsFor(sl: Slot) {
  const fam = sl.status === 5 && sl.type ? family(sl.type) : '';
  const fit = s.spools.filter(sp => !fam || family(sp.material) === fam);
  const rest = s.spools.filter(sp => !fit.includes(sp));
  const opt = (sp: Spool) => ({ value: sp.id, label: label(sp), sp });
  return [
    { label: t('pick.fit'), items: [{ value: 0, label: t('pick.none'), sp: null }, ...fit.map(opt)] },
    ...(rest.length ? [{ label: t('pick.other'), items: rest.map(opt) }] : []),
  ];
}
async function choose(sl: Slot, id: number | null) {
  const name = nameOf(sl);
  if (!id) {
    const was = sl.spool_id;
    if (was == null) return;
    if (!await ask({ title: t('act.unbind', { slot: name }), text: t('confirm.unbind.text', { id: was, slot: name }), yes: t('confirm.unbind.yes'), no: t('common.goBack') })) return;
    const r = await run({ key: `bind:${sl.global_index}`, label: t('act.unbind', { slot: name }), cmd: 'unbind', args: { slot: sl.global_index }, okText: t('ok.unbind', { slot: name }) });
    if (!r.ok) void loadSpools(true);
    return;
  }
  if (!await ask({ title: t('act.bind', { slot: name }), text: t('confirm.bind.text', { slot: name, id }), yes: t('confirm.bind.yes', { slot: name }), no: t('common.goBack') })) return;
  const r = await run({ key: `bind:${sl.global_index}`, label: t('act.bind', { slot: name }), cmd: 'bind', args: { slot: sl.global_index, spool_id: id },
    okText: t('ok.bind', { slot: name, id }), timeoutMs: 60000 });
  if (!r.ok) void loadSpools(true);
}
</script>

<template>
  <section class="kc-card" aria-labelledby="sm-h" data-test="spoolman-card">
    <div class="kc-row sm-head">
      <h2 id="sm-h"><Icon name="icon/spoolman" /> {{ t('sm.title') }}</h2>
      <span class="oui-meta" data-test="spool-source">{{ source }}</span><span class="kc-spacer" />
      <Button severity="secondary" outlined :disabled="!!controlsOff" :loading="tracker.isBusy('spools')" data-focus-key="sm-refresh" @click="loadSpools(false)">
        <Icon name="icon/spoolman" /><span>{{ t('sm.refresh') }}</span></Button>
    </div>
    <p v-if="!slots.length" class="oui-muted">{{ t('ace.noStatus') }}</p>
    <template v-else>
      <p v-if="!configured && !s.spoolsLoaded" class="oui-meta sm-p">{{ t('sm.help') }}
        <Button text size="small" :label="t('common.openSettings')" @click="s.tab = 'settings'" /></p>
      <div v-for="g in groups" :key="g.boxId" class="sm-group">
        <h3 class="sm-g">{{ groupName(g.boxId) }}</h3>
        <div v-for="sl in g.slots" :key="sl.global_index" class="sm-row" :data-sm-slot="sl.global_index">
          <span class="sm-slot"><span class="kc-sw" :style="{ background: sl.status === 5 ? hexOf(sl.color) || 'transparent' : 'transparent' }" />
            <span :id="`sm-l-${sl.global_index}`">{{ t('slot.name', { n: sl.index + 1 }) }}</span></span>
          <Select v-if="s.spools.length" :model-value="sl.spool_id ?? 0" :options="groupsFor(sl)" option-group-label="label" option-group-children="items"
                  option-label="label" option-value="value" filter :filter-placeholder="t('pick.filter')" :aria-label="t('pick.label', { slot: nameOf(sl) })"
                  :disabled="!!controlsOff || tracker.isBusy(`bind:${sl.global_index}`)" class="sm-pick" :data-focus-key="`pick:${sl.global_index}`" :data-pick="sl.global_index"
                  @update:model-value="(v: number | null) => choose(sl, v)">
            <template #value="{ value }">
              <span class="sm-opt"><span class="kc-sw" :style="{ background: swatch(find(value)) }" />
                <span class="sm-opt-t">{{ value ? (find(value) ? label(find(value)!) : t('pick.unknown', { id: value })) : t('pick.choose') }}</span></span>
            </template>
            <template #option="{ option }">
              <span class="sm-opt"><span class="kc-sw" :style="{ background: swatch(option.sp) }" />
                <span class="sm-opt-t">{{ option.label }}</span></span>
            </template>
          </Select>
          <span v-else class="oui-muted">{{ t('sm.noSpools') }}</span>
          <LevelBar v-if="fractionOf(find(sl.spool_id)) !== null" class="sm-bar" :pct="Math.round(fractionOf(find(sl.spool_id))! * 100)"
                    :paint="spoolPaint(find(sl.spool_id)?.colour, find(sl.spool_id)?.colours) || '#888'" :level="find(sl.spool_id)?.low ? 'low' : ''" />
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.sm-head h2 { margin: 0; display: flex; gap: 8px; align-items: center; }
.sm-p { margin: 8px 0; }
.sm-group { margin-top: 12px; }
.sm-g { margin: 0 0 4px; }
.sm-row { display: grid; grid-template-columns: 110px minmax(0, 1fr) 120px; gap: 8px; align-items: center; padding: 4px 0; }
.sm-slot { display: inline-flex; align-items: center; gap: 6px; }
.sm-pick { width: 100%; min-width: 0; }
.sm-opt { display: inline-flex; align-items: center; gap: 6px; min-width: 0; max-width: 100%; }
.sm-opt-t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sm-bar { height: 8px; }
@media (max-width: 640px) { .sm-row { grid-template-columns: minmax(0, 1fr); } }
</style>
