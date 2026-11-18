<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import Button from 'primevue/button';
import Select from 'primevue/select';
import { OuiLevel, OuiSlot, OuiStatus, OuiSwatch, type OuiState } from '../../shared/src/components';
import { s, run, tracker, controlsOff, printerName, loadSpools, stale } from '../app/store';
import { ask } from '../core/dialog';
import { t, fmt } from '../core/i18n';
import { family, hexOf } from '../core/logic';
import { slotFraction } from '../core/spool-level';
import type { Slot, Spool } from '../app/types';

// One slot as an object card: its filament colour across the top, the drawn spool, the amount left, the Spoolman spool
// it books on (the per-slot picker, folded in here), then Edit, Feed and Retract. Feed and retract ask first; linking
// and unlinking a spool ask first; an edit doesn't.
const props = defineProps<{ slot: Slot; label: string }>();
const TYPES = ['PLA', 'PLA+', 'PLA-CF', 'PETG', 'PETG-CF', 'ABS', 'ASA', 'TPU', 'PA', 'PA-CF', 'PC', 'PVA', 'HIPS'];
const key = computed(() => props.slot.global_index);
const ready = computed(() => props.slot.status === 5);
const loaded = computed(() => s.status?.loaded_slot === key.value);
const colour = computed(() => hexOf(props.slot.color));
const linked = computed(() => (props.slot.spool_id != null ? s.spools.find(x => x.id === props.slot.spool_id) ?? null : null));
const typeName = computed(() => [props.slot.brand, props.slot.material_name || props.slot.type].filter(Boolean).join(' ') || t('slot.noType'));
// The name is the Spoolman spool when one is linked, else what the printer reports for the slot.
const name = computed(() => (!ready.value ? null : linked.value ? `${linked.value.vendor} ${linked.value.name}`.trim() : typeName.value));
const meta = computed(() => (!ready.value ? null : linked.value ? [linked.value.material, `#${linked.value.id}`].join(' · ')
  : [props.slot.type || t('slot.noType'), props.slot.spool_id != null ? t('pick.unknown', { id: props.slot.spool_id }) : t('slot.notLinked')].join(' · ')));
// The level comes from the linked Spoolman spool, else from what the printer reports for the slot (percent), else unknown.
const reportedPct = computed(() => (typeof props.slot.percent === 'number' ? Math.max(0, Math.min(100, props.slot.percent)) : null));
const level = computed(() => slotFraction(linked.value, props.slot.percent));
const state = computed<{ state: OuiState; text: string } | null>(() => {
  const a = props.slot.activity;
  if (a === 'loading') return { state: 'busy', text: t('slot.loading') };
  if (a === 'unloading') return { state: 'busy', text: t('slot.unloading') };
  if (loaded.value) return { state: stale.value ? 'stale' : 'ok', text: t('slot.loadedHere') };
  if (ready.value && linked.value?.low) return { state: 'warn', text: t('slot.low') };
  return null;
});

const editWhy = computed(() => controlsOff.value || (s.status && !s.status.can.feed ? t('reason.noFeed') : ''));
const feedWhy = computed(() => controlsOff.value || (s.status && !s.status.can.feed ? t('reason.noFeed')
  : !ready.value ? t('reason.slotEmpty') : tracker.isBusy(`feed:${key.value}`) ? t('reason.pending') : ''));
// Disabled controls point at the reason: the page's (#kc-why), the panel's (#feed-why), or this slot's line.
const whyId = (why: string) => (!why ? undefined : controlsOff.value ? 'kc-why' : s.status && !s.status.can.feed ? 'feed-why' : !ready.value ? `slot-why-${key.value}` : undefined);
async function feed() {
  const n = props.label;
  if (!await ask({ title: t('confirm.feed.title', { slot: n }), text: t('confirm.feed.text', { slot: n, printer: printerName.value }),
    yes: t('confirm.feed.yes', { slot: n }), no: t('common.goBack') })) return;
  await run({ key: `feed:${key.value}`, label: t('act.feed', { slot: n }), cmd: 'slot_feed', args: { slot: key.value }, okText: t('ok.feed', { slot: n }), timeoutMs: 120000 });
}
async function retract() {
  const n = props.label;
  if (!await ask({ title: t('confirm.retract.title', { slot: n }), text: t('confirm.retract.text', { slot: n, printer: printerName.value }),
    yes: t('confirm.retract.yes', { slot: n }), no: t('common.goBack') })) return;
  await run({ key: `feed:${key.value}`, label: t('act.retract', { slot: n }), cmd: 'slot_retract', args: { slot: key.value }, okText: t('ok.retract', { slot: n }), timeoutMs: 120000 });
}

// ---------------------------------------------------------------- edit form (survives status refreshes)
const editing = ref(false);
const form = reactive({ type: 'PLA', colour: '#ffffff' });
const types = computed(() => (form.type && !TYPES.includes(form.type) ? [form.type, ...TYPES] : TYPES));
function startEdit() {
  Object.assign(form, { type: props.slot.type || 'PLA', colour: colour.value || '#ffffff' });
  editing.value = true;
}
async function saveEdit() {
  const r = await run({ key: `edit:${key.value}`, label: t('act.slotSet', { slot: props.label }), cmd: 'slot_set',
    args: { slot: key.value, type: form.type, colour: form.colour }, okText: t('ok.slotSet', { slot: props.label }), timeoutMs: 30000 });
  if (r.ok) editing.value = false;
}

// ---------------------------------------------------------------- the Spoolman spool this slot books on
const spoolLabel = (sp: Spool) => t('pick.option', { id: sp.id, vendor: sp.vendor, name: sp.name, material: sp.material, grams: fmt.grams(sp.remaining) });
const find = (id: number | null) => (id == null ? null : s.spools.find(x => x.id === id) ?? null);
const pickGroups = computed(() => {
  const fam = ready.value && props.slot.type ? family(props.slot.type) : '';
  const fit = s.spools.filter(sp => !fam || family(sp.material) === fam);
  const rest = s.spools.filter(sp => !fit.includes(sp));
  const opt = (sp: Spool) => ({ value: sp.id, label: spoolLabel(sp), sp });
  return [
    { label: t('pick.fit'), items: [{ value: 0, label: t('pick.none'), sp: null }, ...fit.map(opt)] },
    ...(rest.length ? [{ label: t('pick.other'), items: rest.map(opt) }] : []),
  ];
});
async function choose(id: number | null) {
  const slotName = props.label, sl = props.slot;
  if (!id) {
    const was = sl.spool_id;
    if (was == null) return;
    if (!await ask({ title: t('act.unbind', { slot: slotName }), text: t('confirm.unbind.text', { id: was, slot: slotName }), yes: t('confirm.unbind.yes'), no: t('common.goBack') })) return;
    const r = await run({ key: `bind:${sl.global_index}`, label: t('act.unbind', { slot: slotName }), cmd: 'unbind', args: { slot: sl.global_index }, okText: t('ok.unbind', { slot: slotName }) });
    if (!r.ok) void loadSpools(true);
    return;
  }
  if (!await ask({ title: t('act.bind', { slot: slotName }), text: t('confirm.bind.text', { slot: slotName, id }), yes: t('confirm.bind.yes', { slot: slotName }), no: t('common.goBack') })) return;
  const r = await run({ key: `bind:${sl.global_index}`, label: t('act.bind', { slot: slotName }), cmd: 'bind', args: { slot: sl.global_index, spool_id: id },
    okText: t('ok.bind', { slot: slotName, id }), timeoutMs: 60000 });
  if (!r.ok) void loadSpools(true);
}
</script>

<template>
  <OuiSlot class="kc-slot" :label="String(slot.index + 1)" :name="name" :material="meta" :color="ready ? colour || null : null"
           :colors="ready && linked?.colours?.length ? linked.colours : null" :remaining="ready ? level ?? 0 : null" :initial="1"
           :active="loaded && !stale" :empty-label="t('slot.empty')"
           :aria-label="label" :data-slot="key">
    <template v-if="state" #state><OuiStatus :state="state.state" :title="state.text" data-test="slot-state">{{ state.text }}</OuiStatus></template>
    <!-- OuiSlot draws its spool from remaining / initial and fakes a level when that is unknown, so it gets the chosen
         fraction (an unknown one as 0: the same bare reel) and the amount is written here. -->
    <template #amount>
      <div class="oui-slot-amount">
        <p v-if="typeof linked?.remaining === 'number'" class="oui-num"><strong>{{ fmt.number(Math.round(linked.remaining), 0) }}</strong> g<span
          v-if="typeof linked.initial === 'number'" class="oui-muted"> / {{ fmt.grams(linked.initial) }}</span></p>
        <p v-else-if="reportedPct !== null" class="oui-num"><strong>{{ reportedPct }}%</strong><span v-if="typeof slot.weight === 'number'" class="oui-muted"> · {{ fmt.grams(slot.weight) }}</span></p>
        <p v-else class="oui-muted">{{ t('slot.weightUnknown') }}</p>
        <OuiLevel :fraction="level" :tone="linked?.low ? 'low' : 'normal'" />
      </div>
    </template>

    <span class="oui-sr">{{ t('slot.name', { n: slot.index + 1 }) }}</span>
    <p v-if="!ready && !controlsOff" :id="`slot-why-${key}`" class="oui-meta">{{ t('reason.slotEmpty') }}</p>

    <form v-if="editing" class="sl-form" @submit.prevent="saveEdit">
      <p class="oui-label">{{ t('slot.editTitle', { slot: label }) }}</p>
      <div class="sl-grid">
        <label :id="`e${key}-tl`">{{ t('slot.material') }}</label>
        <Select v-model="form.type" :options="types" size="small" :aria-labelledby="`e${key}-tl`" :data-edit-type="key" />
        <label :for="`e${key}-c`">{{ t('slot.colour') }}</label>
        <span class="sl-colour-field"><input :id="`e${key}-c`" v-model="form.colour" type="color" class="sl-colour"><OuiSwatch :color="form.colour" /></span>
      </div>
      <div class="oui-row">
        <Button type="submit" size="small" :label="t('common.save')" :loading="tracker.isBusy(`edit:${key}`)" :disabled="!!editWhy" />
        <Button severity="secondary" text size="small" :label="t('common.cancel')" @click="editing = false" />
      </div>
    </form>

    <Select v-else-if="s.spools.length" :model-value="slot.spool_id ?? 0" :options="pickGroups" option-group-label="label" option-group-children="items"
            option-label="label" option-value="value" filter :filter-placeholder="t('pick.filter')" :aria-label="t('pick.label', { slot: label })" size="small"
            :disabled="!!controlsOff || tracker.isBusy(`bind:${key}`)" :aria-describedby="controlsOff ? 'kc-why' : undefined" class="sl-pick"
            :data-focus-key="`pick:${key}`" :data-pick="key" @update:model-value="(v: number | null) => choose(v)">
      <template #value="{ value }">
        <span class="sl-opt"><OuiSwatch v-if="find(value)" :color="find(value)!.colour ?? null" :colors="find(value)!.colours ?? null" />
          <span class="oui-truncate">{{ value ? (find(value) ? spoolLabel(find(value)!) : t('pick.unknown', { id: value })) : t('pick.choose') }}</span></span>
      </template>
      <template #option="{ option }">
        <span class="sl-opt"><OuiSwatch v-if="option.sp" :color="option.sp.colour ?? null" :colors="option.sp.colours ?? null" />
          <span class="oui-truncate">{{ option.label }}</span></span>
      </template>
    </Select>

    <template #actions>
      <Button size="small" severity="secondary" text :label="t('slot.edit')" :aria-label="t('slot.editLabel', { slot: label })" :disabled="!!editWhy || editing"
              :aria-describedby="whyId(editWhy)" :data-focus-key="`edit:${key}`" :data-edit="key" @click="startEdit" />
      <Button size="small" severity="secondary" text :label="t('slot.feed')" :aria-label="t('slot.feedLabel', { slot: label })" :disabled="!!feedWhy" :aria-describedby="whyId(feedWhy)"
              :loading="tracker.isBusy(`feed:${key}`)" :data-focus-key="`feed:${key}`" :data-feed="key" @click="feed" />
      <Button size="small" severity="secondary" text :label="t('slot.retract')" :aria-label="t('slot.retractLabel', { slot: label })" :disabled="!!feedWhy" :aria-describedby="whyId(feedWhy)"
              :loading="tracker.isBusy(`feed:${key}`)" :data-focus-key="`retract:${key}`" :data-retract="key" @click="retract" />
    </template>
  </OuiSlot>
</template>

<style>
.kc-slot .oui-slot-state { min-width: 0; }
.kc-slot .oui-slot-state > .oui-status { max-width: 100%; }
.kc-slot .oui-slot-state .oui-status-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sl-pick { width: 100%; min-width: 0; }
.sl-opt { display: inline-flex; align-items: center; gap: 6px; min-width: 0; max-width: 100%; }
.sl-form { display: grid; gap: var(--oui-s2); padding: var(--oui-s2); border-radius: var(--oui-radius); background: var(--oui-inset); }
.sl-grid { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--oui-s2); align-items: center; }
.sl-colour-field { display: inline-flex; align-items: center; gap: var(--oui-s2); }
.sl-colour { width: 44px; height: 26px; padding: 0; border: 1px solid var(--oui-control-border); border-radius: var(--oui-radius-sm); background: none; }
</style>
