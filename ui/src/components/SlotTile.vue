<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue';
import Button from 'primevue/button';
import Select from 'primevue/select';
import { OuiIcon, OuiLevel, OuiPresetMatch, OuiSlot, OuiSpoolPick, OuiStatus, OuiSwatch, type OuiSpoolPickLabels, type OuiState } from '@orca-plugins/ui-foundation/src/components';
import { chevronDown, edit as editIcon, warning } from '@orca-plugins/ui-foundation/src/icons';
import { s, run, tracker, busy, controlsOff, printerName, linkSpool, stale, whyId as pageWhy, pickPreset } from '../app/store';
import { presetLabels } from '../core/match';
import type { MessageKey } from '../core/messages';
import { ask } from '../core/dialog';
import { t, fmt } from '../core/i18n';
import { family, hexOf } from '../core/logic';
import { levelTone, slotFraction } from '../core/spool-level';
import type { Slot, Spool } from '../app/types';

// One slot as a neutral card: a strip of its filament colour across the top, the drawn spool, the amount left with its
// level (green, amber when low, red when almost empty), the Spoolman spool it books on (the per-slot picker), then
// Feed, Retract and Edit. Feed and retract ask first; linking and unlinking a spool ask first; an edit doesn't.
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

// The OrcaSlicer preset this slot is reported as to the Device tab (its sync from AMS loads it), and Change. The card shows
// a clean name only (no score, reasons or source); a close call gets one warning icon. Labels map back to full names.
const match = computed(() => (ready.value ? s.matches[String(key.value)] ?? null : null));
const labels = computed(() => presetLabels([...(match.value?.name ? [match.value.name] : []), ...(match.value?.candidates ?? []).map(c => c.name)]));
const shown = (name: string | null | undefined) => (name ? labels.value.get(name) ?? name : name);
const candidates = computed(() => (!match.value || match.value.source === 'linked' ? []
  : match.value.candidates.map(c => ({ name: shown(c.name)! }))));
const pickShown = (label: string | null) => {
  const full = label === null ? null : [...labels.value].find(([, v]) => v === label)?.[0] ?? label;
  return pickPreset(key.value, full);
};
const matchLabels = computed(() => ({ change: t('match.change'), none: t('match.none'), score: '', auto: t('match.auto'), autoHint: t('match.autoHint') }));
const editOff = computed(() => !!controlsOff.value || busy.value.feed);
const feedOff = computed(() => editOff.value || !ready.value || tracker.isBusy(`feed:${key.value}`));
// Disabled controls point at the reason: the page's (#kc-why), the printer's (#kc-busy), or this slot's own (it is empty).
const whyId = computed(() => pageWhy(busy.value.feed) ?? (!ready.value ? `slot-why-${key.value}` : undefined));
// The printer unloads whatever is loaded, whichever slot is asked: with another slot loaded, Retract is that slot's.
const otherLoaded = computed(() => (s.status?.loaded_slot ?? -1) >= 0 && !loaded.value);
const retractWhy = computed(() => whyId.value ?? (otherLoaded.value ? `slot-other-${key.value}` : undefined));
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
// The compact line shows the linked spool; it opens the shared colour-first picker (OuiSpoolPick) under it, over the card
// like Change's list. The picker draws one swatch per colour, not a row per spool, and only while it is open: a colour
// with one spool picks it, with several a dialog lists them fullest first. Material chips replace the old "same material /
// other materials" groups and start at the slot's material family; "No spool" unlinks.
const spoolLabel = (sp: Spool) => t('pick.option', { id: sp.id, vendor: sp.vendor, name: sp.name, material: sp.material, grams: fmt.grams(sp.remaining) });
// The material family on its own: every status refresh gives the slot a new object.
const fam = computed(() => (ready.value && props.slot.type ? family(props.slot.type) : ''));
const picking = ref(false);
const pickFam = ref('');
const trigger = ref<HTMLButtonElement | null>(null);
const panel = ref<HTMLElement | null>(null);
// Spools as the picker groups them: the material is the family, so the chips read PLA, PETG, ... (read only while open).
const pickSpools = computed(() => s.spools.map(sp => ({ ...sp, material: family(sp.material) })));
const pickLabels = computed<OuiSpoolPickLabels>(() => ({ label: t('pick.label', { slot: props.label }), spools: t('pick.count'), noColour: t('pick.noColour'),
  choose: t('pick.dialog'), unknown: t('slot.weightUnknown'), empty: t('pick.empty'), search: t('pick.filter'), noMatch: t('pick.noMatch'),
  allMaterials: t('pick.allMaterials'), none: t('pick.none') }));
async function openPick() {
  if (picking.value) { closePick(); return; }
  pickFam.value = fam.value;
  picking.value = true;
  await nextTick();
  const box = panel.value, r = trigger.value?.getBoundingClientRect();
  if (box && r) box.toggleAttribute('data-up', innerHeight - r.bottom < box.offsetHeight + GAP && r.top > innerHeight - r.bottom);
  box?.querySelector<HTMLElement>('.oui-spick-q, [data-colour][tabindex="0"]')?.focus();
}
function closePick() {
  picking.value = false;
  trigger.value?.focus();
}
// A press outside the open picker closes it; its own dialog of one colour's spools is outside the card but belongs to it.
function outside(e: Event) {
  const at = e.target as Element | null;
  if (!at || panel.value?.contains(at) || trigger.value?.contains(at) || at.closest?.('.p-dialog-mask')) return;
  picking.value = false;
}
watch(picking, on => document[on ? 'addEventListener' : 'removeEventListener']('pointerdown', outside, true));
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside, true));
function picked(id: number | string | null) {
  closePick();
  void choose(id == null ? null : Number(id));
}
async function choose(id: number | null) {
  const slotName = props.label, sl = props.slot;
  if (id === sl.spool_id) return;
  if (!id) {
    const was = sl.spool_id;
    if (was == null) return;
    if (!await ask({ title: t('act.unbind', { slot: slotName }), text: t('confirm.unbind.text', { id: was, slot: slotName }), yes: t('confirm.unbind.yes'), no: t('common.goBack') })) return;
    await linkSpool(sl.global_index, null, { label: t('act.unbind', { slot: slotName }), okText: t('ok.unbind', { slot: slotName }) });
    return;
  }
  if (!await ask({ title: t('act.bind', { slot: slotName }), text: t('confirm.bind.text', { slot: slotName, id }), yes: t('confirm.bind.yes', { slot: slotName }), no: t('common.goBack') })) return;
  await linkSpool(sl.global_index, id, { label: t('act.bind', { slot: slotName }), okText: t('ok.bind', { slot: slotName, id }) });
}

// Change's candidate list floats over the card (see .sl-match CSS). Once it opens, give it the room the viewport has: below the
// preset line when that fits, else above it, and never taller than the side it sits on, so no option is cut off at the edge.
// ponytail: measured on open only; a scroll or resize while it is open keeps that placement, close and reopen to re-measure.
const GAP = 8, MAX = 260;
async function placeList(e: MouseEvent) {
  const host = (e.currentTarget as HTMLElement).querySelector<HTMLElement>('.oui-match');
  if (!host || !(e.target as HTMLElement).closest('.oui-match-change')) return;
  await nextTick();
  const list = host.querySelector<HTMLElement>('.oui-match-list');
  if (!list) { host.removeAttribute('data-up'); return; }
  const r = host.getBoundingClientRect(), below = innerHeight - r.bottom - GAP, above = r.top - GAP, want = Math.min(MAX, list.scrollHeight);
  const up = below < want && above > below;
  host.toggleAttribute('data-up', up);
  list.style.maxHeight = `${Math.max(0, Math.min(MAX, up ? above : below))}px`;
}
</script>

<template>
  <OuiSlot class="kc-slot" :label="String(slot.index + 1)" :name="name" :material="meta" :color="ready ? colour || null : null"
           :colors="ready && linked?.colours?.length ? linked.colours : null" :remaining="ready ? level : null" :initial="1"
           :active="loaded && !stale" :empty-label="t('slot.empty')"
           :aria-label="label" :data-slot="key">
    <template v-if="state" #state><OuiStatus :state="state.state" :title="state.text" data-test="slot-state">{{ state.text }}</OuiStatus></template>
    <!-- OuiSlot draws its spool from remaining / initial: it gets the chosen fraction (null when unknown: the full reel in
         the slot's colour with the unknown badge) and the amount is written here. -->
    <template #amount>
      <div class="oui-slot-amount">
        <p v-if="typeof linked?.remaining === 'number'" class="oui-num"><strong>{{ fmt.number(Math.round(linked.remaining), 0) }}</strong> g<span
          v-if="typeof linked.initial === 'number'" class="oui-muted"> / {{ fmt.grams(linked.initial) }}</span></p>
        <p v-else-if="reportedPct !== null" class="oui-num"><strong>{{ reportedPct }}%</strong><span v-if="typeof slot.weight === 'number'" class="oui-muted"> · {{ fmt.grams(slot.weight) }}</span></p>
        <p v-else class="oui-muted">{{ t('slot.weightUnknown') }}</p>
        <OuiLevel :fraction="level" :tone="levelTone(level, linked?.low)" />
      </div>
    </template>

    <span class="oui-sr">{{ t('slot.name', { n: slot.index + 1 }) }}</span>
    <span v-if="!ready" :id="`slot-why-${key}`" class="oui-sr">{{ t('reason.slotEmpty') }}</span>
    <span v-else-if="otherLoaded" :id="`slot-other-${key}`" class="oui-sr">{{ t('reason.otherLoaded') }}</span>

    <form v-if="editing" class="sl-form" @submit.prevent="saveEdit">
      <p class="oui-label">{{ t('slot.editTitle', { slot: label }) }}</p>
      <div class="sl-grid">
        <label :id="`e${key}-tl`">{{ t('slot.material') }}</label>
        <Select v-model="form.type" :options="types" size="small" :aria-labelledby="`e${key}-tl`" :data-edit-type="key" />
        <label :for="`e${key}-c`">{{ t('slot.colour') }}</label>
        <span class="sl-colour-field"><input :id="`e${key}-c`" v-model="form.colour" type="color" class="sl-colour"><OuiSwatch :color="form.colour" /></span>
      </div>
      <div class="oui-row">
        <Button type="submit" severity="secondary" size="small" :label="t('common.save')" :loading="tracker.isBusy(`edit:${key}`)" :disabled="editOff" />
        <Button severity="secondary" text size="small" :label="t('common.cancel')" @click="editing = false" />
      </div>
    </form>

    <div v-else-if="s.spools.length" class="sl-pick" :data-open="picking || undefined">
      <button ref="trigger" type="button" class="sl-pick-btn" :aria-label="t('pick.label', { slot: label })" :aria-expanded="picking" aria-haspopup="true"
              :disabled="!!controlsOff || tracker.isBusy(`bind:${key}`)" :aria-describedby="pageWhy(false)" :data-focus-key="`pick:${key}`" :data-pick="key" @click="openPick">
        <OuiSwatch v-if="linked" :color="linked.colour ?? null" :colors="linked.colours ?? null" />
        <span class="oui-truncate">{{ slot.spool_id == null ? t('pick.choose') : linked ? spoolLabel(linked) : t('pick.unknown', { id: slot.spool_id }) }}</span>
        <OuiIcon :icon="chevronDown" :size="14" />
      </button>
      <div v-if="picking" ref="panel" class="sl-pick-panel" :data-pick-panel="key">
        <OuiSpoolPick v-model:material="pickFam" :spools="pickSpools" :labels="pickLabels" :selected="slot.spool_id ?? null" :grams="fmt.grams"
                      @pick="picked" @close="closePick" />
      </div>
    </div>

    <div v-if="match && !editing" class="sl-match" :data-match="key" @click="placeList">
      <p class="oui-label sl-match-title" :title="match.name || undefined">{{ t('match.title') }}
        <span v-if="match.name && !match.confident" class="sl-match-warn" role="img" :aria-label="t('match.unsure')" :title="t('match.unsure')"><OuiIcon :icon="warning" :size="13" /></span></p>
      <OuiPresetMatch :name="shown(match.name)" :remembered="match.source === 'remembered' && !!match.remembered_key"
                      :candidates="candidates"
                      :labels="matchLabels" :busy="s.matchBusy" @pick="pickShown" />
    </div>

    <template #actions>
      <Button size="small" severity="secondary" :label="t('slot.feed')" :aria-label="t('slot.feedLabel', { slot: label })" :disabled="feedOff" :aria-describedby="whyId"
              :loading="tracker.isBusy(`feed:${key}`)" :data-focus-key="`feed:${key}`" :data-feed="key" @click="feed" />
      <Button size="small" severity="secondary" :label="t('slot.retract')" :aria-label="t('slot.retractLabel', { slot: label })" :disabled="feedOff || otherLoaded" :aria-describedby="retractWhy"
              :loading="tracker.isBusy(`feed:${key}`)" :data-focus-key="`retract:${key}`" :data-retract="key" @click="retract" />
      <span class="oui-spacer" />
      <Button size="small" severity="secondary" text :aria-label="t('slot.editLabel', { slot: label })" :title="t('slot.edit')" :disabled="editOff || editing"
              :aria-describedby="pageWhy(busy.feed)" :data-focus-key="`edit:${key}`" :data-edit="key" @click="startEdit"><template #icon><OuiIcon :icon="editIcon" :size="14" /></template></Button>
    </template>
  </OuiSlot>
</template>

<style>
/* A dense card: tighter spacing, a smaller spool beside the name and material, one-line names and a slimmer amount;
   the actions stay at the foot of a card stretched by its row. */
.oui-slot.kc-slot { gap: 6px; padding: 6px 4px; }
.oui-slot.kc-slot .oui-slot-head { min-height: 20px; }
.oui-slot.kc-slot .oui-slot-main { gap: var(--oui-s2); }
.oui-slot.kc-slot .oui-slot-main .oui-spool { width: 36px !important; height: 36px !important; flex: none; }
.oui-slot.kc-slot .oui-slot-name { -webkit-line-clamp: 1; line-clamp: 1; line-height: 1.3; }
.oui-slot.kc-slot .oui-slot-amount { gap: 3px; line-height: 18px; }
.oui-slot.kc-slot .oui-slot-amount strong { font-size: var(--oui-text-md); }
.oui-slot.kc-slot .oui-slot-extra { gap: 6px; }
.oui-slot.kc-slot .oui-slot-actions { padding-top: 0; }

.kc-slot .oui-slot-state { min-width: 0; }
.kc-slot .oui-slot-state > .oui-status { max-width: 100%; }
.kc-slot .oui-slot-state .oui-status-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sl-pick { position: relative; min-width: 0; }
.orca-ui .sl-pick-btn { display: flex; align-items: center; gap: 6px; width: 100%; min-width: 0; height: 28px; padding: 0 var(--oui-s2); border: 1px solid var(--oui-control-border);
  border-radius: var(--oui-radius-sm); background: var(--oui-control); color: var(--oui-text); font: inherit; font-size: var(--oui-text-sm); text-align: start; cursor: pointer; }
.orca-ui .sl-pick-btn > .oui-truncate { flex: 1; min-width: 0; }
.orca-ui .sl-pick-btn:disabled { opacity: .6; cursor: default; }
.orca-ui .sl-pick-btn:focus-visible { outline: 2px solid var(--oui-primary-mark); outline-offset: 1px; }
/* The picker floats over the card under its line, as wide as the card, like Change's list: opening it never grows the slot. */
.kc-slot:has(.sl-pick[data-open]), .kc-group:has(.sl-pick[data-open]) { position: relative; z-index: 30; }
.sl-pick-panel { position: absolute; inset-inline: 0; top: calc(100% + 2px); z-index: 1; padding: var(--oui-s2); border-radius: var(--oui-radius-sm);
  background: var(--oui-surface); box-shadow: 0 0 0 1px var(--oui-border), 0 8px 24px rgb(0 0 0 / .28); }
.sl-match { display: grid; gap: 2px; padding-top: 6px; border-top: 1px solid var(--oui-border); }
.sl-match .oui-match-name { font-size: var(--oui-text-sm); }
.sl-match-title { display: flex; align-items: center; gap: 4px; }
.sl-match-warn { display: inline-flex; color: var(--oui-warning); cursor: help; }
/* Narrow cards (four ACE columns, three holders): the shared side group is flex: none and keeps its one-line width, so the
   score chip and Change spilled out of the card. Let it shrink and wrap inside the card instead. */
.sl-match .oui-match-head { min-width: 0; }
.sl-match .oui-match-side { flex: 0 1 auto; min-width: 0; max-width: 100%; }
/* Change's candidate list is a popup over the card, not a block in it: opening it must not grow the slot, its row or the dashboard.
   It hangs under the preset line, as wide as the card, scrolls when there are many, and lifts the open card above its neighbours. */
.kc-slot:has(.oui-match[data-open]), .kc-group:has(.oui-match[data-open]) { position: relative; z-index: 30; }
.sl-match .oui-match { position: relative; }
.sl-match .oui-match-list { position: absolute; inset-inline: 0; top: 100%; z-index: 1; max-height: min(260px, 50vh); overflow-y: auto; overscroll-behavior: contain;
  background: var(--oui-surface); box-shadow: 0 0 0 1px var(--oui-border), 0 8px 24px rgb(0 0 0 / .28); }
.sl-pick-panel[data-up] { top: auto; bottom: calc(100% + 2px); }
.sl-match .oui-match[data-up] .oui-match-list { top: auto; bottom: 100%; }
.sl-form { display: grid; gap: var(--oui-s2); padding: var(--oui-s2); border-radius: var(--oui-radius); background: var(--oui-inset); }
.sl-grid { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--oui-s2); align-items: center; }
.sl-colour-field { display: inline-flex; align-items: center; gap: var(--oui-s2); }
.sl-colour { width: 44px; height: 26px; padding: 0; border: 1px solid var(--oui-control-border); border-radius: var(--oui-radius-sm); background: none; }
</style>
