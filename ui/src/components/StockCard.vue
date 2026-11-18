<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import Checkbox from 'primevue/checkbox';
import InputText from 'primevue/inputtext';
import Select from 'primevue/select';
import { OuiBanner, OuiIcon, OuiLevel, OuiPanel, OuiSpool, OuiStatus, OuiToolbar, materialTone } from '../../shared/src/components';
import { boxes, link as linkIcon, refresh, settings, spoolman } from '../../shared/src/icons';
import { spoolFraction } from '../core/spool-level';
import { s, openSettings, run, tracker, loadStock, loadSpools, controlsOff, targetKnown, printerName, stockVisible } from '../app/store';
import { config, spoolmanSet as configured } from '../app/settings';
import { ask } from '../core/dialog';
import { t, tMaybe, fmt } from '../core/i18n';
import { family, groupSlots } from '../core/logic';
import type { Spool } from '../app/types';

// Spoolman and stock: where the slots' spools come from (the source line, Refresh spools), and Spooler's stock with
// the link to a slot. The per-slot pickers are in the slot cards. The stock list shows only when Spooler says it is
// usable (`available`); every other reason hides it.
/** The Spoolman in use: what the stock banners are about (their dismissal comes back for another one). */
const smUrl = computed(() => s.located?.spoolman_url || config.value?.settings.spoolman_url || '');
// One visible spool source per screen: when Spooler's stock uses the same Spoolman, say so.
const source = computed(() => {
  if (!configured.value && !s.spoolsLoaded) return t('sm.notConfigured');
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
const groupName = (boxId: number) => (boxId < 0 ? t('ace.head') : t('ace.unit', { n: boxId + 1 }));
const slotOptions = computed(() => groupSlots(slotList.value).flatMap(g => g.slots.map(sl => ({ value: sl.global_index, label: `${groupName(g.boxId)} · ${t('slot.name', { n: sl.index + 1 })}` }))));
const chosen = computed(() => slotKey.value ?? slotOptions.value[0]?.value ?? null);
const chosenLabel = computed(() => slotOptions.value.find(o => o.value === chosen.value)?.label ?? '');
const targetSlot = computed(() => slotList.value.find(sl => sl.global_index === chosen.value));
const shown = computed(() => {
  const needle = q.value.trim().toLowerCase();
  const fam = fit.value && targetSlot.value?.status === 5 ? family(targetSlot.value.type) : '';
  return rows.value.filter(r => (!mat.value || r.material === mat.value) && (!fam || family(r.material) === fam)
    && (!needle || [r.name, r.vendor, r.material, r.location, '#' + r.id].join(' ').toLowerCase().includes(needle)));
});
/** Why linking is off. A page-wide reason is said under the app bar (#kc-why); one about this list, here (#stock-why). */
const why = computed(() => (!targetKnown.value || !s.info ? t('stock.why.connect') : controlsOff.value ? controlsOff.value : chosen.value == null ? t('stock.why.noSlot')
  : !configured.value ? t('sm.notConfigured') : s.stock?.same_spoolman === false ? t('stock.why.spoolman') : ''));
const pageWhy = computed(() => !targetKnown.value || !s.info || !!controlsOff.value);
const whyId = computed(() => (!why.value ? undefined : pageWhy.value ? 'kc-why' : 'stock-why'));
const slotOf = (r: Spool) => (r.bound_slot == null ? '' : slotOptions.value.find(o => o.value === r.bound_slot)?.label ?? '');
function clear() { q.value = ''; mat.value = null; fit.value = false; }

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
  <OuiPanel :icon="stockVisible ? boxes : spoolman" tone="lime" flush :fill="stockVisible" aria-labelledby="stock-h" data-test="spoolman-card">
    <template #title><span id="stock-h">{{ stockVisible ? t('stock.title') : t('sm.title') }}</span></template>
    <template #meta><span data-test="spool-source" :title="source">{{ source }}</span></template>
    <template #actions>
      <Button severity="secondary" text size="small" :label="t('sm.refreshShort')" :aria-label="t('sm.refresh')" :disabled="!!controlsOff || !configured" :aria-describedby="controlsOff ? 'kc-why' : undefined"
              :loading="tracker.isBusy('spools')" data-focus-key="sm-refresh" @click="loadSpools(false)"><template #icon><OuiIcon :icon="spoolman" :size="14" /></template></Button>
      <Button v-if="stockVisible" severity="secondary" text size="small" :aria-label="t('stock.refresh')" :title="t('stock.refresh')" :loading="s.stockLoading"
              data-focus-key="stock-refresh" @click="loadStock(true)"><template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
    </template>

    <div v-if="!configured && !s.spoolsLoaded" class="oui-row kc-pad">
      <p class="oui-meta">{{ t('sm.help') }}</p>
      <Button severity="secondary" size="small" :label="t('common.openSettings')" @click="openSettings('sm-s-h')"><template #icon><OuiIcon :icon="settings" :size="14" /></template></Button>
    </div>

    <div v-if="stockVisible" class="sc-body" data-test="stock-card">
      <div role="status" aria-live="polite" class="sc-notes">
        <OuiBanner :show="s.stock!.same_spoolman === false" tone="error" :title="t('stock.otherSpoolman')" dismissible :dismiss-key="`stock-other-spoolman:${smUrl}`" :close-label="t('common.close')" />
        <OuiBanner :show="s.stock!.same_spoolman === 'fallback'" tone="info" :title="t('stock.fallback')" dismissible :dismiss-key="`stock-fallback:${smUrl}`" :close-label="t('common.close')" />
        <OuiBanner :show="!!why && !pageWhy" id="stock-why" tone="warn" data-test="stock-why" :title="t('stock.blocked', { reason: why })"
                   dismissible :dismiss-key="`stock-why:${why}`" :close-label="t('common.close')" />
      </div>
      <OuiToolbar class="sc-bar" :summary="t('stock.count', { shown: shown.length, n: rows.length })" :label="t('stock.searchLabel')">
        <InputText v-model="q" type="search" size="small" :placeholder="t('stock.search')" :aria-label="t('stock.searchLabel')" class="sc-q" />
        <Select v-model="mat" :options="materials" option-label="label" option-value="value" show-clear size="small" :placeholder="t('stock.allMaterials')" :aria-label="t('stock.material')" />
        <label class="kc-inline" for="stock-fit"><Checkbox v-model="fit" input-id="stock-fit" binary />{{ t('stock.sameMaterial') }}</label>
        <template #end>
          <span class="kc-inline"><span id="stock-head-l">{{ t('stock.linkTo') }}</span>
            <Select :model-value="chosen" :options="slotOptions" option-label="label" option-value="value" size="small" aria-labelledby="stock-head-l" data-test="stock-slot"
                    @update:model-value="v => (slotKey = v)" /></span>
        </template>
      </OuiToolbar>
      <div class="sc-wrap kc-scroll">
        <table class="kc-table sc-table">
          <thead><tr><th scope="col">{{ t('stock.col.spool') }}</th><th scope="col" class="sc-mat">{{ t('stock.col.material') }}</th>
            <th scope="col" class="sc-loc">{{ t('stock.col.location') }}</th><th scope="col" class="sc-left oui-num">{{ t('stock.col.left') }}</th>
            <th scope="col" class="sc-act oui-end"><span class="oui-sr">{{ t('stock.col.action') }}</span></th></tr></thead>
          <tbody>
            <tr v-for="r in shown" :key="r.id">
              <td><div class="sc-nm"><OuiSpool :color="r.colour" :colors="r.colours" :fraction="spoolFraction(r.remaining, r.initial)" :size="40" />
                <div class="sc-id"><p class="oui-truncate" :title="`${r.vendor} ${r.name}`"><span class="oui-strong">{{ r.name }}</span> <span class="oui-muted oui-num">#{{ r.id }}</span></p>
                  <p class="oui-meta sc-meta"><span v-if="slotOf(r)" class="oui-chip" data-tone="accent" data-solid>{{ t('stock.on', { slot: slotOf(r) }) }}</span>
                    <span v-if="r.use_first" class="oui-chip">{{ t('stock.useFirst') }}</span><span class="oui-truncate">{{ r.vendor }}</span></p></div></div></td>
              <td class="sc-mat"><span class="oui-chip" :data-tone="materialTone(r.material)">{{ r.material || '—' }}</span></td>
              <td class="sc-loc" :class="{ 'oui-muted': !r.location }">{{ r.location || '—' }}</td>
              <td class="sc-left oui-num"><div class="sc-amount"><span :class="{ 'kc-low': r.low }">{{ r.remaining == null ? '—' : fmt.grams(r.remaining) }}<template v-if="r.low"> · {{ t('stock.low') }}</template></span>
                <OuiLevel :fraction="spoolFraction(r.remaining, r.initial)" :tone="r.low ? 'low' : 'normal'" /></div></td>
              <td class="sc-act oui-end"><Button size="small" severity="secondary" text :label="t('stock.link')" :disabled="!!why || tracker.isBusy(`bind:${chosen}`)" :aria-describedby="whyId"
                          :data-focus-key="`stock:${r.id}`" :data-stock="r.id" :aria-label="t('stock.linkLabel', { id: r.id, name: `${r.vendor} ${r.name}`, slot: chosenLabel })" @click="link(r)">
                <template #icon><OuiIcon :icon="linkIcon" :size="14" /></template></Button></td>
            </tr>
            <tr v-if="!shown.length"><td colspan="5" class="oui-muted">
              <template v-if="rows.length">{{ t('stock.noMatch') }} <Button text size="small" severity="secondary" :label="t('stock.clearFilters')" @click="clear" /></template>
              <template v-else>{{ t('stock.empty') }}</template></td></tr>
          </tbody>
        </table>
      </div>
      <div class="sc-foot">
        <p class="oui-meta" id="stock-meta">
          <OuiStatus v-if="sk?.state === 'stale'" state="stale">{{ t('stock.meta', { version: sp?.version, n: rows.length, age: fmt.ago(sk?.ts, s.now / 1000) }) }}</OuiStatus>
          <template v-else>{{ t('stock.meta', { version: sp?.version, n: rows.length, age: fmt.ago(sk?.ts, s.now / 1000) }) }}</template></p>
        <p v-if="s.stock?.usage && s.stock.usage !== 'unknown'" class="oui-meta">{{ tMaybe(`stock.usage.${s.stock.usage}`, '') }}</p>
        <details class="sc-tabs kc-disclose"><summary>{{ t('stock.tabs.summary') }}</summary><p class="oui-meta">{{ t('stock.tabs.body') }}</p></details>
      </div>
    </div>
  </OuiPanel>
</template>

<style>
.sc-body { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.sc-notes { display: grid; gap: var(--oui-s2); }
.sc-notes:empty { display: none; }
.sc-notes .oui-banner { margin: var(--oui-s3) var(--oui-s3) 0; }
.sc-bar { border-bottom: 1px solid var(--oui-border); }
.sc-q { width: 220px; max-width: 100%; }
.sc-wrap { flex: 1 1 auto; min-height: 0; max-height: 360px; }
/* Fixed layout: a long spool name is cut, never widens the table. */
.sc-table { table-layout: fixed; min-width: 560px; }
.sc-mat { width: 84px; } .sc-loc { width: 110px; } .sc-left { width: 108px; } .sc-act { width: 92px; }
.sc-nm { display: flex; align-items: center; gap: var(--oui-s3); min-width: 0; }
.sc-id { display: grid; gap: 1px; min-width: 0; }
.sc-meta { display: flex; align-items: center; gap: var(--oui-s1); min-width: 0; }
.sc-amount { display: grid; gap: 4px; }
.sc-foot { display: grid; gap: var(--oui-s1); padding: var(--oui-s2) var(--oui-s4); border-top: 1px solid var(--oui-border); }
.sc-tabs p { max-width: 96ch; }
/* Wide: the stock is a narrow third column; the location goes and the table fits it. */
@container oui-page (min-width: 1500px) { .sc-loc { display: none; } .sc-table { min-width: 0; } .sc-mat { width: 72px; } .sc-left { width: 92px; } .sc-act { width: 108px; } }
</style>
