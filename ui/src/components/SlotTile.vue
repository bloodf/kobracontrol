<script setup lang="ts">
import { computed, nextTick, reactive, ref } from 'vue';
import Button from 'primevue/button';
import Select from 'primevue/select';
import { fuzzyFilter, longList, OuiIcon, OuiLevel, OuiPresetMatch, OuiSlot, OuiStatus, OuiSwatch, type OuiState } from '@orca-plugins/ui-foundation/src/components';
import { edit as editIcon } from '@orca-plugins/ui-foundation/src/icons';
import { s, run, tracker, busy, controlsOff, printerName, loadSpools, stale, whyId as pageWhy, pickPreset } from '../app/store';
import { reasonTexts } from '../core/match';
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

// The OrcaSlicer preset this slot is reported as to the Device tab (its sync from AMS loads it), why, and Change.
const match = computed(() => (ready.value ? s.matches[String(key.value)] ?? null : null));
const words = (reasons: unknown) => reasonTexts(reasons, (code, v) => t(`match.r.${code}` as MessageKey, { v }));
const BADGES: Record<string, MessageKey> = { remembered: 'match.remembered', linked: 'match.linked', spooler: 'match.spooler' };
const candidates = computed(() => (!match.value || match.value.source === 'linked' ? [] : [
  ...match.value.candidates.map(c => ({ name: c.name, score: c.score, reasons: words(c.reasons) })),
  ...(match.value.ofd ?? []).map(c => ({ name: c.name, score: c.score, reasons: words(c.reasons), badge: t('ofd.badge'), note: t('ofd.note') }))]));
const matchLabels = computed(() => ({ change: t('match.change'), none: t('match.none'), score: t('match.score'), auto: t('match.auto'), autoHint: t('match.autoHint') }));
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
const spoolLabel = (sp: Spool) => t('pick.option', { id: sp.id, vendor: sp.vendor, name: sp.name, material: sp.material, grams: fmt.grams(sp.remaining) });
const find = (id: number | null) => (id == null ? null : s.spools.find(x => x.id === id) ?? null);
// The picker's search: brand, name and material by fuzzyFilter (foundation: case and accents ignored, letters in order, best
// first). A query that is only a number is a spool's id and matches that spool exactly ("12" or "#12"), never a neighbour
// (#120) and never a brand or name with that digit in it ("3D Fuel"). While it is typed the list is only the hits, without
// "no spool" (Enter on the first hit must never unlink), and nothing is bound until one is chosen.
// ponytail: Select still runs its own "contains" pass; every option carries the typed text as `q` so it keeps all of ours.
const query = ref('');
const hits = computed(() => {
  const m = /^#?(\d+)$/.exec(query.value.trim());
  const byId = m ? s.spools.filter(sp => sp.id === Number(m[1])) : [];
  const fuzzy = m ? [] : fuzzyFilter(s.spools, query.value, sp => [sp.vendor, sp.name, sp.material].filter(Boolean).join(' ')).map(r => r.item);
  return [...byId, ...fuzzy.filter(sp => !byId.includes(sp))];
});
// The material family on its own: every status refresh gives the slot a new object, and the spool list below (thousands of
// spools) must not be rebuilt for it, only for a different family, other spools or another search.
const fam = computed(() => (ready.value && props.slot.type ? family(props.slot.type) : ''));
const pickGroups = computed(() => {
  const searching = !!query.value.trim();
  const list = searching ? hits.value : s.spools;
  const fit: Spool[] = [], rest: Spool[] = [];
  for (const sp of list) (!fam.value || family(sp.material) === fam.value ? fit : rest).push(sp);
  const opt = (sp: Spool) => ({ value: sp.id, label: spoolLabel(sp), sp, q: query.value });
  return searching
    ? [...(fit.length ? [{ label: t('pick.fit'), items: fit.map(opt) }] : []), ...(rest.length ? [{ label: t('pick.other'), items: rest.map(opt) }] : [])]
    : [
      { label: t('pick.fit'), items: [{ value: 0, label: t('pick.none'), sp: null, q: '' }, ...fit.map(opt)] },
      ...(rest.length ? [{ label: t('pick.other'), items: rest.map(opt) }] : []),
    ];
});
const pickRows = computed(() => pickGroups.value.reduce((n, g) => n + 1 + g.items.length, 0));
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

    <Select v-else-if="s.spools.length" :model-value="slot.spool_id ?? 0" :options="pickGroups" option-group-label="label" option-group-children="items"
            option-label="label" option-value="value" :virtual-scroller-options="longList(pickRows, 32)" filter :filter-fields="['q']" reset-filter-on-hide
            :filter-placeholder="t('pick.filter')" :aria-label="t('pick.label', { slot: label })" size="small"
            :disabled="!!controlsOff || tracker.isBusy(`bind:${key}`)" :aria-describedby="pageWhy(false)" class="sl-pick"
            :data-focus-key="`pick:${key}`" :data-pick="key" @update:model-value="(v: number | null) => choose(v)" @filter="(e: { value: string }) => (query = e.value)" @hide="query = ''">
      <template #value="{ value }">
        <span class="sl-opt"><OuiSwatch v-if="find(value)" :color="find(value)!.colour ?? null" :colors="find(value)!.colours ?? null" />
          <span class="oui-truncate">{{ value ? (find(value) ? spoolLabel(find(value)!) : t('pick.unknown', { id: value })) : t('pick.choose') }}</span></span>
      </template>
      <template #option="{ option }">
        <span class="sl-opt"><OuiSwatch v-if="option.sp" :color="option.sp.colour ?? null" :colors="option.sp.colours ?? null" />
          <span class="oui-truncate">{{ option.label }}</span></span>
      </template>
    </Select>

    <div v-if="match && !editing" class="sl-match" :data-match="key" @click="placeList">
      <p class="oui-label">{{ t('match.title') }}</p>
      <OuiPresetMatch :name="match.name" :score="match.score" :confident="match.confident" :reasons="words(match.reasons)"
                      :badge="BADGES[match.source] ? t(BADGES[match.source]) : undefined" :remembered="match.source === 'remembered' && !!match.remembered_key"
                      :candidates="candidates"
                      :labels="matchLabels" :busy="s.matchBusy" @pick="name => pickPreset(key, name, match?.ofd?.find(c => c.name === name))" />
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
.sl-pick { width: 100%; min-width: 0; }
.sl-match { display: grid; gap: 2px; padding-top: 6px; border-top: 1px solid var(--oui-border); }
.sl-match .oui-match-name { font-size: var(--oui-text-sm); }
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
.sl-match .oui-match[data-up] .oui-match-list { top: auto; bottom: 100%; }
.sl-opt { display: inline-flex; align-items: center; gap: 6px; min-width: 0; max-width: 100%; }
.sl-form { display: grid; gap: var(--oui-s2); padding: var(--oui-s2); border-radius: var(--oui-radius); background: var(--oui-inset); }
.sl-grid { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--oui-s2); align-items: center; }
.sl-colour-field { display: inline-flex; align-items: center; gap: var(--oui-s2); }
.sl-colour { width: 44px; height: 26px; padding: 0; border: 1px solid var(--oui-control-border); border-radius: var(--oui-radius-sm); background: none; }
</style>
