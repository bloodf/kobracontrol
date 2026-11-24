<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import Checkbox from 'primevue/checkbox';
import InputText from 'primevue/inputtext';
import Select from 'primevue/select';
import { OuiBanner, OuiEmpty, OuiHint, OuiIcon, OuiLevel, OuiPageHeader, OuiPanel, OuiSpool, OuiStatus, OuiToolbar } from '@orca-plugins/ui-foundation/src/components';
import { boxes, chevronDown, chevronRight, link as linkIcon, refresh, settings } from '@orca-plugins/ui-foundation/src/icons';
import { levelTone, spoolFraction } from '../core/spool-level';
import { s, openSettings, run, tracker, loadStock, loadSpools, controlsOff, targetKnown, printerName, stockVisible } from '../app/store';
import { config, spoolmanSet as configured } from '../app/settings';
import { ask } from '../core/dialog';
import { t, tn, tMaybe, fmt } from '../core/i18n';
import { family, groupSlots, hexOf } from '../core/logic';
import type { Slot, Spool } from '../app/types';

// The Stock tab: Spooler's stock, linked to this printer's slots. Left, where a spool can go (every slot, with what is
// in it); right, the stock with one action per row, named with the chosen slot. A link checks the spool in Spoolman
// first and always asks. The list shows only when Spooler says it is usable (`available`); otherwise the page says
// why not. The per-slot pickers stay in the dashboard's slot cards.
/** The Spoolman in use: what the stock banners are about (their dismissal comes back for another one). */
const smUrl = computed(() => s.located?.spoolman_url || config.value?.settings.spoolman_url || '');
// One visible spool source per screen: when Spooler's stock uses the same Spoolman, say so.
const source = computed(() => {
  if (!configured.value && !s.spoolsLoaded) return t('sm.notConfigured');
  if (s.spoolsRetrying) return t('sm.retrying');
  if (s.spoolsError) return t('sm.error', { error: s.spoolsError });
  if (!s.spoolsLoaded) return t('sm.notLoaded');
  const n = s.spools.length;
  return s.stock?.spooler.state === 'active' && (s.stock.same_spoolman === true || s.stock.same_spoolman === 'fallback') ? t('sm.same', { n }) : t('sm.count', { n });
});

const q = ref('');
const mat = ref<string | null>(null);
const fit = ref(false);
const slotKey = ref<number | null>(null);
const sp = computed(() => s.stock?.spooler);
const sk = computed(() => s.stock?.stock);
const rows = computed<Spool[]>(() => sk.value?.rows ?? []);
const materials = computed(() => [...new Set(rows.value.map(r => r.material).filter(Boolean))].sort().map(m => ({ value: m, label: m })));
const slotList = computed(() => s.status?.slots ?? []);
const groups = computed(() => groupSlots(slotList.value));
const groupName = (boxId: number) => (boxId < 0 ? t('ace.head') : t('ace.unit', { n: boxId + 1 }));
const slotName = (sl: Slot) => `${groupName(sl.box_id)} · ${t('slot.name', { n: sl.index + 1 })}`;
const chosen = computed(() => slotKey.value ?? groups.value[0]?.slots[0]?.global_index ?? null);
const targetSlot = computed(() => slotList.value.find(sl => sl.global_index === chosen.value));
const chosenLabel = computed(() => (targetSlot.value ? slotName(targetSlot.value) : ''));
/** On the row's button the slot alone ("Link to Slot 2"): its feeder is marked on the left, and named in full in the
 *  button's own label and in the question it asks. */
const chosenShort = computed(() => (targetSlot.value ? t('slot.name', { n: targetSlot.value.index + 1 }) : ''));
// What is in each slot: the Spoolman spool linked to it, else what the printer reports.
const inSlot = (sl: Slot) => {
  const spool = sl.spool_id != null ? s.spools.find(x => x.id === sl.spool_id) ?? rows.value.find(x => x.id === sl.spool_id) ?? null : null;
  const ready = sl.status === 5;
  return { ready, colour: ready ? spool?.colour || hexOf(sl.color) || null : null, colours: ready && spool?.colours?.length ? spool.colours : null,
    fraction: ready ? spoolFraction(spool?.remaining, spool?.initial) ?? (typeof sl.percent === 'number' ? Math.max(0, Math.min(1, sl.percent / 100)) : null) : null,
    name: spool ? spool.name : sl.material_name || sl.type || t('slot.noType'),
    meta: spool ? [spool.material, typeof spool.remaining === 'number' ? fmt.grams(spool.remaining) : ''].filter(Boolean).join(' · ') : t('slot.notLinked') };
};
const shown = computed(() => {
  const needle = q.value.trim().toLowerCase();
  const fam = fit.value && targetSlot.value?.status === 5 ? family(targetSlot.value.type) : '';
  return rows.value.filter(r => (!mat.value || r.material === mat.value) && (!fam || family(r.material) === fam)
    && (!needle || [r.name, r.vendor, r.material, r.location, '#' + r.id].join(' ').toLowerCase().includes(needle)));
});
// Group the list like Spooler's: by material, manufacturer or location (off by default); a header shows the count and what is left in the group.
type GroupBy = 'none' | 'material' | 'vendor' | 'location';
const group = ref<GroupBy>('none');
const collapsed = ref(new Set<string>());
const groupOptions = computed(() => [{ value: 'none', label: t('stock.group.none') }, { value: 'material', label: t('stock.group.material') },
  { value: 'vendor', label: t('stock.group.vendor') }, { value: 'location', label: t('stock.group.location') }]);
const groupRaw = (r: Spool) => (group.value === 'material' ? r.material : group.value === 'vendor' ? r.vendor : r.location) || '';
const groupLabel = (r: Spool) => groupRaw(r) || t(group.value === 'material' ? 'stock.group.unknownMaterial' : group.value === 'vendor' ? 'stock.group.unknownVendor' : 'stock.group.noLocation');
const sum = (xs: (number | null | undefined)[]) => { const n = xs.filter((x): x is number => typeof x === 'number'); return n.length ? n.reduce((a, b) => a + b, 0) : null; };
/** One block per group (a single headerless block when ungrouped): its rows, count and what is left together. */
const blocks = computed(() => {
  if (group.value === 'none') return [{ key: '', label: '', head: false, items: shown.value, left: null as number | null, fraction: null as number | null, open: true }];
  // Keyed by mode and raw value, never by the translated label: a missing value and a real one named like the label stay apart.
  const by = new Map<string, { label: string; items: Spool[] }>();
  for (const r of shown.value) { const k = `${group.value}:${groupRaw(r)}`; const g = by.get(k) ?? { label: groupLabel(r), items: [] }; g.items.push(r); by.set(k, g); }
  return [...by.entries()].sort(([, a], [, b]) => a.label.toLowerCase().localeCompare(b.label.toLowerCase())).map(([key, { label, items }]) => {
    const left = sum(items.map(r => r.remaining)), first = sum(items.map(r => r.initial));
    return { key, label, head: true, items, left, fraction: spoolFraction(left, first), open: !collapsed.value.has(key) };
  });
});
function toggle(key: string) { const next = new Set(collapsed.value); if (!next.delete(key)) next.add(key); collapsed.value = next; }
/** Why linking is off. A page-wide reason is the page's banner (#kc-why); one about this list is this page's (#stock-why). */
const why = computed(() => (!targetKnown.value || !s.info ? t('stock.why.connect') : controlsOff.value ? controlsOff.value : chosen.value == null ? t('stock.why.noSlot')
  : !configured.value ? t('sm.notConfigured') : s.stock?.same_spoolman === false ? t('stock.why.spoolman') : ''));
const pageWhy = computed(() => !targetKnown.value || !s.info || !!controlsOff.value);
const whyId = computed(() => (!why.value ? undefined : pageWhy.value ? 'kc-why' : 'stock-why'));
/** The one banner of this page, by weight: the two Spoolman addresses differ, linking is off, or a note. */
const note = computed(() => (!stockVisible.value ? '' : s.stock!.same_spoolman === false ? 'other' : why.value && !pageWhy.value ? 'blocked' : s.stock!.same_spoolman === 'fallback' ? 'fallback' : ''));
const slotOf = (r: Spool) => { const sl = r.bound_slot == null ? null : slotList.value.find(x => x.global_index === r.bound_slot); return sl ? slotName(sl) : ''; };
function clear() { q.value = ''; mat.value = null; fit.value = false; }
const usage = computed(() => (s.stock?.usage && s.stock.usage !== 'unknown' ? tMaybe(`stock.usage.${s.stock.usage}`, '') : ''));
/** Spooler shares no list, so the plugin lists Kobra Control's own Spoolman read. */
const own = computed(() => sk.value?.source === 'spoolman' && sk.value?.code === 'own');
const age = computed(() => (own.value ? t('stock.ownMeta', { n: rows.value.length })
  : t('stock.meta', { version: sp.value?.version, n: rows.value.length, age: fmt.ago(sk.value?.ts, s.now / 1000) })));
/** Why there is no list: the plugin's own words for Spooler's state, else that this tab needs Spooler. A Spooler that
 *  never publishes a list for Kobra Control ("unsupported") is said so, with the way out: a Spoolman address. */
const none = computed(() => s.stockError || (s.stock?.reason === 'unsupported' ? t('stock.unsupported') : '')
  || (sk.value?.state !== 'ok' && sk.value?.text) || sp.value?.text || t('spooler.noStock'));

// Refresh reads Spoolman again (the slots' links) and Spooler's stock.
const canSpools = computed(() => !controlsOff.value && configured.value);
function reload() {
  if (canSpools.value) void loadSpools(false);
  if (stockVisible.value) void loadStock(true);
}

async function link(r: Spool) {
  const slot = chosen.value, key = sk.value?.key, name = chosenLabel.value;
  if (slot == null || !key || why.value) return;
  const spool = `${r.vendor} ${r.name}`.trim();
  if (!await ask({ title: t('act.stockLink'), text: t('confirm.stockLink.text', { id: r.id, name: spool, material: r.material, slot: name, printer: printerName.value }),
    yes: t('stock.linkBtn', { slot: name }), no: t('common.goBack') })) return;
  const res = await run({ key: `bind:${slot}`, label: t('act.stockLink'), cmd: 'stock_assign', args: { slot, spool_id: r.id, key },
    okText: t('ok.bind', { slot: name, id: r.id }), timeoutMs: 60000 });
  if (res.ok) void loadSpools(true);
  void loadStock(false);
}
</script>

<template>
  <OuiPageHeader :title="t('nav.stock')" data-test="stock-head">
    <template #meta><span data-test="spool-source" :title="source">{{ source }}</span><template v-if="stockVisible"> ·
      <OuiStatus v-if="sk?.state === 'stale'" state="stale" id="stock-meta">{{ age }}</OuiStatus><span v-else id="stock-meta">{{ age }}</span></template></template>
    <template #actions>
      <OuiHint :label="t('nav.stock')"><span class="sc-hint"><span v-if="usage">{{ usage }}</span>
        <span><strong>{{ t('stock.tabs.summary') }}</strong> {{ t('stock.tabs.body') }}</span></span></OuiHint>
      <Button severity="secondary" :label="t('common.refresh')" :aria-label="t('stock.refresh')" :disabled="!canSpools && !stockVisible" :aria-describedby="controlsOff && !stockVisible ? 'kc-why' : undefined"
              :loading="tracker.isBusy('spools') || s.stockLoading" data-focus-key="sm-refresh" data-test="stock-refresh" @click="reload"><template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
    </template>
  </OuiPageHeader>

  <div class="kc-msgs" data-msgs="stock" />

  <div role="status" aria-live="polite" class="kc-live sc-notes">
    <OuiBanner :show="note === 'other'" id="stock-why" tone="error" :title="t('stock.otherSpoolman')" data-test="stock-why" dismissible :dismiss-key="`stock-other-spoolman:${smUrl}`" :close-label="t('common.close')" />
    <OuiBanner :show="note === 'blocked'" id="stock-why" tone="warn" :title="t('stock.blocked', { reason: why })" data-test="stock-why" dismissible :dismiss-key="`stock-why:${why}`" :close-label="t('common.close')" />
    <OuiBanner :show="note === 'fallback'" tone="info" :title="t('stock.fallback')" dismissible :dismiss-key="`stock-fallback:${smUrl}`" :close-label="t('common.close')" />
    <OuiBanner :show="stockVisible && own" tone="info" :title="t('stock.own')" data-test="stock-own" dismissible :dismiss-key="`stock-own:${smUrl}`" :close-label="t('common.close')" />
  </div>

  <div v-if="stockVisible" class="oui-split" data-rail data-test="stock-card">
    <OuiPanel :title="t('stock.linkTo')" :icon="linkIcon" :flush="!groups.length">
      <OuiEmpty v-if="!groups.length" compact :state="controlsOff ? 'offline' : 'empty'" :title="t('stock.why.noSlot')" />
      <div v-else class="sc-targets" role="radiogroup" :aria-label="t('stock.linkTo')" data-test="stock-slot">
        <template v-for="g in groups" :key="g.boxId">
          <p v-if="groups.length > 1" class="oui-label">{{ groupName(g.boxId) }}</p>
          <button v-for="sl in g.slots" :key="sl.global_index" type="button" role="radio" class="sc-target" :aria-checked="chosen === sl.global_index" :aria-label="slotName(sl)"
                  :data-stock-target="sl.global_index" @click="slotKey = sl.global_index">
            <span class="oui-slot-badge oui-num">{{ sl.index + 1 }}</span>
            <OuiSpool :color="inSlot(sl).colour" :colors="inSlot(sl).colours" :fraction="inSlot(sl).fraction" :size="32" />
            <span v-if="inSlot(sl).ready" class="sc-target-id"><span class="oui-strong oui-truncate">{{ inSlot(sl).name }}</span><span class="oui-meta oui-num oui-truncate">{{ inSlot(sl).meta }}</span></span>
            <span v-else class="sc-target-id oui-muted">{{ t('slot.empty') }}</span>
          </button>
        </template>
      </div>
    </OuiPanel>

    <OuiPanel flush class="sc-list">
      <OuiToolbar :summary="t('stock.count', { shown: shown.length, n: rows.length })" :label="t('stock.searchLabel')">
        <InputText v-model="q" type="search" size="small" :placeholder="t('stock.search')" :aria-label="t('stock.searchLabel')" class="sc-q" />
        <Select v-model="mat" :options="materials" option-label="label" option-value="value" show-clear size="small" :placeholder="t('stock.allMaterials')" :aria-label="t('stock.material')" />
        <Select v-model="group" :options="groupOptions" option-label="label" option-value="value" size="small" :aria-label="t('stock.group')" data-test="stock-group" />
        <label class="kc-inline" for="stock-fit"><Checkbox v-model="fit" input-id="stock-fit" binary />{{ t('stock.sameMaterial') }}</label>
      </OuiToolbar>
      <div class="sc-wrap">
        <table class="kc-table sc-table">
          <thead><tr><th scope="col">{{ t('stock.col.spool') }}</th><th scope="col" class="sc-mat">{{ t('stock.col.material') }}</th>
            <th scope="col" class="sc-in">{{ t('stock.col.loaded') }}</th><th scope="col" class="sc-left oui-num">{{ t('stock.col.left') }}</th>
            <th scope="col" class="sc-act oui-end"><span class="oui-sr">{{ t('stock.col.action') }}</span></th></tr></thead>
          <tbody>
            <template v-for="b in blocks" :key="b.key">
              <tr v-if="b.head" class="sc-grow" :data-group="b.key"><td colspan="5">
                <button type="button" class="sc-ghead" :aria-expanded="b.open" @click="toggle(b.key)">
                  <OuiIcon :icon="b.open ? chevronDown : chevronRight" :size="14" />
                  <span class="sc-gname"><strong>{{ b.label }}</strong> <span class="oui-meta">{{ tn('stock.groupCount', b.items.length) }}</span></span>
                  <span class="sc-gbar"><span class="oui-meta oui-num">{{ b.left == null ? t('common.unknown') : fmt.grams(b.left) }}</span><OuiLevel :fraction="b.fraction" :tone="levelTone(b.fraction, false)" /></span>
                </button></td></tr>
              <template v-if="b.open">
            <tr v-for="r in b.items" :key="r.id" :data-spool="r.id">
              <td><div class="sc-nm"><OuiSpool :color="r.colour" :colors="r.colours" :fraction="spoolFraction(r.remaining, r.initial)" :size="36" />
                <div class="sc-id"><p class="oui-truncate" :title="`${r.vendor} ${r.name}`"><span class="oui-strong">{{ r.name }}</span> <span class="oui-muted oui-num">#{{ r.id }}</span></p>
                  <p class="oui-meta sc-meta"><span v-if="r.use_first" class="oui-chip">{{ t('stock.useFirst') }}</span><span class="oui-truncate">{{ [r.vendor, r.location].filter(Boolean).join(' · ') }}</span></p></div></div></td>
              <td class="sc-mat"><span class="oui-chip">{{ r.material || '—' }}</span></td>
              <td class="sc-in"><span v-if="slotOf(r)" class="oui-chip" data-test="stock-in">{{ slotOf(r) }}</span><span v-else class="oui-muted">—</span></td>
              <td class="sc-left oui-num"><div class="sc-amount"><span><strong>{{ r.remaining == null ? t('common.unknown') : fmt.grams(r.remaining) }}</strong><span v-if="r.low" class="kc-low"> · {{ t('stock.low') }}</span></span>
                <OuiLevel :fraction="spoolFraction(r.remaining, r.initial)" :tone="levelTone(spoolFraction(r.remaining, r.initial), r.low)" /></div></td>
              <td class="sc-act oui-end">
                <OuiStatus v-if="r.bound_slot != null && r.bound_slot === chosen" state="ok" :data-linked="r.id">{{ t('stock.linked') }}</OuiStatus>
                <Button v-else size="small" severity="secondary" :label="t('stock.linkBtn', { slot: chosenShort })" :disabled="!!why || tracker.isBusy(`bind:${chosen}`)" :aria-describedby="whyId"
                        :data-focus-key="`stock:${r.id}`" :data-stock="r.id" :aria-label="t('stock.linkLabel', { id: r.id, name: `${r.vendor} ${r.name}`, slot: chosenLabel })" @click="link(r)">
                  <template #icon><OuiIcon :icon="linkIcon" :size="13" /></template></Button></td>
            </tr>
              </template>
            </template>
            <tr v-if="!shown.length"><td colspan="5" class="oui-muted">
              <template v-if="rows.length">{{ t('stock.noMatch') }} <Button text size="small" severity="secondary" :label="t('stock.clearFilters')" @click="clear" /></template>
              <template v-else>{{ t('stock.empty') }}</template></td></tr>
          </tbody>
        </table>
      </div>
    </OuiPanel>
  </div>

  <!-- No usable list: the page keeps its shape and says why, with the way to a Spoolman address when none is set. -->
  <OuiPanel v-else flush data-test="spoolman-card">
    <OuiEmpty :icon="boxes" :state="s.stockLoading && !s.stock ? 'loading' : 'empty'" :title="none" :text="!configured && !s.spoolsLoaded ? t('sm.help') : sp?.detail || undefined">
      <template v-if="(!configured && !s.spoolsLoaded) || s.stock?.reason === 'unsupported'" #actions>
        <Button severity="secondary" size="small" :label="t('common.openSettings')" @click="openSettings('sm-s-h')"><template #icon><OuiIcon :icon="settings" :size="14" /></template></Button>
      </template>
    </OuiEmpty>
  </OuiPanel>
</template>

<style>
.sc-hint { display: grid; gap: var(--oui-s2); }
.sc-notes:empty { display: none; }
/* Where a spool can go: one row per slot, the chosen one marked like a selected row. */
.sc-targets { display: grid; gap: var(--oui-s1); }
.sc-targets > .oui-label { margin-top: var(--oui-s1); }
.sc-target { display: flex; align-items: center; gap: var(--oui-s2); width: 100%; min-height: 48px; padding: 6px var(--oui-s2); border: 0; border-radius: var(--oui-radius); text-align: start;
  font: inherit; color: var(--oui-text); background: none; cursor: pointer; box-shadow: inset 0 0 0 1px var(--oui-border); }
.sc-target:hover { background: var(--oui-raised); }
.sc-target[aria-checked='true'] { background: var(--oui-primary-soft); box-shadow: inset 0 0 0 2px var(--oui-primary-mark); }
.sc-target-id { display: grid; min-width: 0; }
/* The list is as tall as the window under the bars above it, and scrolls inside. */
.sc-list { min-height: 320px; max-height: calc(100vh - 124px); }
@supports (height: 100dvh) { .sc-list { max-height: calc(100dvh - 124px); } }
.sc-list > .oui-panel-body { display: flex; flex-direction: column; min-height: 0; }
.sc-q { width: 240px; max-width: 100%; }
.sc-wrap { flex: 1 1 auto; min-height: 0; overflow: auto; border-top: 1px solid var(--oui-border); }
/* Fixed layout: a long spool name is cut, never widens the table. */
.sc-table { table-layout: fixed; min-width: 640px; }
.sc-mat { width: 96px; } .sc-in { width: 168px; } .sc-left { width: 132px; } .sc-act { width: 176px; }
.sc-act .p-button { max-width: 100%; }
.sc-nm { display: flex; align-items: center; gap: var(--oui-s3); min-width: 0; }
.sc-id { display: grid; gap: 1px; min-width: 0; }
.sc-meta { display: flex; align-items: center; gap: var(--oui-s1); min-width: 0; }
.sc-amount { display: grid; gap: 4px; justify-items: end; }
.sc-amount > .oui-level { width: 100%; }
.sc-ghead { display: flex; align-items: center; gap: var(--oui-s2); width: 100%; padding: 2px 0; border: 0; background: none; color: var(--oui-text); font: inherit; text-align: start; cursor: pointer; }
.sc-gname { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.sc-gbar { display: grid; gap: 4px; min-width: 90px; white-space: nowrap; text-align: end; }
</style>
