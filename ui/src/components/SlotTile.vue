<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import Button from 'primevue/button';
import Select from 'primevue/select';
import Icon from './Icon.vue';
import SpoolFigure from './SpoolFigure.vue';
import LevelBar from './LevelBar.vue';
import { spoolFraction } from '../core/spool-level';
import { s, run, tracker, controlsOff, printerName } from '../app/store';
import { ask } from '../core/dialog';
import { t, fmt } from '../core/i18n';
import { hexOf } from '../core/logic';
import type { Slot } from '../app/types';

const props = defineProps<{ slot: Slot; label: string }>();
const TYPES = ['PLA', 'PLA+', 'PLA-CF', 'PETG', 'PETG-CF', 'ABS', 'ASA', 'TPU', 'PA', 'PA-CF', 'PC', 'PVA', 'HIPS'];
const key = computed(() => props.slot.global_index);
const ready = computed(() => props.slot.status === 5);
const loaded = computed(() => s.status?.loaded_slot === key.value);
const colour = computed(() => hexOf(props.slot.color));
const stateText = computed(() => {
  const a = props.slot.activity;
  if (a === 'loading') return t('slot.loading');
  if (a === 'unloading') return t('slot.unloading');
  if (loaded.value) return t('slot.loadedHere');
  return ready.value ? t('slot.ready') : t('slot.empty');
});
const linked = computed(() => (props.slot.spool_id != null ? s.spools.find(x => x.id === props.slot.spool_id) ?? null : null));
const fraction = computed(() => (!ready.value ? 0 : linked.value ? spoolFraction(linked.value.remaining, linked.value.initial) ?? 1 : 1));
const pct = computed(() => (linked.value ? (() => { const f = spoolFraction(linked.value.remaining, linked.value.initial); return f === null ? null : Math.round(f * 100); })() : null));

const editWhy = computed(() => controlsOff.value || (s.status && !s.status.can.feed ? t('reason.noFeed') : ''));
const feedWhy = computed(() => controlsOff.value || (s.status && !s.status.can.feed ? t('reason.noFeed')
  : !ready.value ? t('reason.slotEmpty') : tracker.isBusy(`feed:${key.value}`) ? t('reason.pending') : ''));
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
</script>

<template>
  <article class="sl" :class="{ loaded }" :aria-labelledby="`sl-${key}`" :data-slot="key">
    <template v-if="!editing">
      <div class="sl-top">
        <SpoolFigure class="sl-spool" :paint="ready ? colour : ''" :fraction="fraction" :size="56" />
        <div class="sl-name">
          <strong :id="`sl-${key}`">{{ t('slot.name', { n: slot.index + 1 }) }}</strong>
          <div class="sl-state" data-test="slot-state">{{ stateText }}</div>
          <div class="sl-mat"><template v-if="ready"><span class="kc-sw" :style="{ background: colour || 'transparent' }" /> {{ slot.type || t('slot.noType') }}</template><template v-else>&nbsp;</template></div>
        </div>
      </div>
      <div class="sl-level">
        <template v-if="ready && linked">
          <div class="kc-num"><strong :class="{ 'kc-warn': linked.low }">{{ fmt.grams(linked.remaining) }}</strong>
            <span v-if="pct !== null" class="oui-muted"> · {{ pct }}%</span></div>
          <LevelBar :pct="pct" :paint="colour || '#888'" :level="linked.low ? 'low' : ''" />
        </template>
        <p v-else-if="!ready && !controlsOff" class="kc-why">{{ t('reason.slotEmpty') }}</p>
      </div>
      <div class="kc-row sl-actions">
        <Button size="small" severity="secondary" outlined :label="t('slot.edit')" :aria-label="t('slot.editLabel', { slot: label })" :disabled="!!editWhy"
                :data-focus-key="`edit:${key}`" :data-edit="key" @click="startEdit" />
        <Button size="small" severity="secondary" outlined :aria-label="t('slot.feedLabel', { slot: label })" :disabled="!!feedWhy" :loading="tracker.isBusy(`feed:${key}`)"
                :data-focus-key="`feed:${key}`" :data-feed="key" @click="feed"><Icon name="icon/load-filament" /><span>{{ t('slot.feed') }}</span></Button>
        <Button size="small" severity="secondary" outlined :aria-label="t('slot.retractLabel', { slot: label })" :disabled="!!feedWhy" :loading="tracker.isBusy(`feed:${key}`)"
                :data-focus-key="`retract:${key}`" :data-retract="key" @click="retract"><Icon name="icon/unload-filament" /><span>{{ t('slot.retract') }}</span></Button>
      </div>
    </template>
    <form v-else class="sl-form" @submit.prevent="saveEdit">
      <strong :id="`sl-${key}`">{{ t('slot.editTitle', { slot: label }) }}</strong>
      <div class="sl-grid">
        <label :id="`e${key}-tl`">{{ t('slot.material') }}</label><Select v-model="form.type" :options="types" :aria-labelledby="`e${key}-tl`" :data-edit-type="key" />
        <label :for="`e${key}-c`">{{ t('slot.colour') }}</label><input :id="`e${key}-c`" v-model="form.colour" type="color" class="sl-colour">
      </div>
      <div class="kc-row">
        <Button type="submit" :label="t('common.save')" :loading="tracker.isBusy(`edit:${key}`)" :disabled="!!editWhy" />
        <Button severity="secondary" outlined :label="t('common.cancel')" @click="editing = false" />
      </div>
    </form>
  </article>
</template>

<style scoped>
.sl { min-width: 0; border: 1px solid var(--oui-border); border-radius: 12px; padding: 12px; background: var(--oui-surface); display: flex; flex-direction: column; gap: 8px; }
.sl.loaded { border-color: var(--p-primary-color); }
.sl-top { display: flex; align-items: flex-start; gap: 8px; min-width: 0; min-height: 56px; }
.sl-level { min-height: 38px; }
.sl-level p { margin: 0; }
.sl-mat { min-height: 1.4em; }
.sl-actions { margin-top: auto; }
.sl-spool { margin: -2px 0 0; }
.sl-name { min-width: 0; overflow-wrap: anywhere; }
.sl-state { color: var(--oui-muted); font-size: 12px; }
.sl-actions :deep(.p-button) { gap: 4px; }
.sl-form { display: grid; gap: 8px; }
.sl-grid { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; align-items: center; }
.sl-colour { width: 44px; height: 32px; padding: 0; border: 1px solid var(--oui-control-border, var(--oui-border)); border-radius: 6px; background: none; }
</style>
