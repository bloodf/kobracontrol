<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import SpoolFigure from './SpoolFigure.vue';
import LevelBar from './LevelBar.vue';
import { spoolFraction, spoolPaint } from '../core/spool-level';
import InputText from 'primevue/inputtext';
import Select from 'primevue/select';
import Checkbox from 'primevue/checkbox';
import Message from 'primevue/message';
import Icon from './Icon.vue';
import { s, run, tracker, loadStock, loadSpools, controlsOff, targetKnown, printerName, stockVisible } from '../app/store';
import { ask } from '../core/dialog';
import { t, tMaybe, fmt } from '../core/i18n';
import { family, groupSlots } from '../core/logic';
import type { Spool } from '../app/types';

const q = ref('');
const mat = ref<string | null>(null);
const fit = ref(false);
const slotKey = ref<number | null>(null);
const sp = computed(() => s.stock?.spooler);
const sk = computed(() => s.stock?.stock);
const usable = stockVisible;
/** Notes shown above the list. */
const notes = computed(() => (s.stock!.same_spoolman === false ? [{ sev: 'error', text: t('stock.otherSpoolman') }] : []));
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
const filtered = computed(() => !!(q.value.trim() || mat.value || fit.value));
/** Visible reason when linking is off (U06/B-06): disabled buttons can't show a tooltip by keyboard. */
const why = computed(() => (!targetKnown.value || !s.info ? t('stock.why.connect') : controlsOff.value ? controlsOff.value : chosen.value == null ? t('stock.why.noSlot')
  : s.stock?.same_spoolman === false ? t('stock.why.spoolman') : ''));
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
  <section v-if="stockVisible" class="kc-card" aria-labelledby="stock-h" data-test="stock-card">
    <div class="kc-row sc-head">
      <h2 id="stock-h"><Icon name="icon/filament-spool" /> {{ t('stock.title') }}</h2>
      <span v-if="usable" class="oui-meta" id="stock-meta">{{ t('stock.meta', { version: sp?.version, n: rows.length, age: fmt.ago(sk?.ts, s.now / 1000) }) }}</span>
      <span class="kc-spacer" />
      <Button severity="secondary" outlined :label="t('stock.refresh')" :loading="s.stockLoading" data-focus-key="stock-refresh" @click="loadStock(true)" />
    </div>
    <div role="status" aria-live="polite" class="sc-notes">
      <Message v-for="nt in notes" :key="nt.text" :severity="nt.sev">{{ nt.text }}</Message>
      <Message v-if="usable && why" severity="warn" data-test="stock-why">{{ t('stock.blocked', { reason: why }) }}</Message>
    </div>
    <template v-if="usable">
      <div class="kc-row sc-filters">
        <InputText v-model="q" type="search" :placeholder="t('stock.search')" :aria-label="t('stock.searchLabel')" class="sc-q" />
        <Select v-model="mat" :options="materials" option-label="label" option-value="value" show-clear :placeholder="t('stock.allMaterials')" :aria-label="t('stock.material')" />
        <span class="kc-row"><Checkbox v-model="fit" input-id="stock-fit" binary /><label for="stock-fit">{{ t('stock.sameMaterial') }}</label></span>
        <span class="kc-spacer" />
        <label id="stock-head-l">{{ t('stock.linkTo') }}</label>
        <Select :model-value="chosen" :options="slotOptions" option-label="label" option-value="value" aria-labelledby="stock-head-l" data-test="stock-slot" @update:model-value="v => (slotKey = v)" />
      </div>
      <div class="sc-wrap">
        <table class="kc-table">
          <thead><tr><th scope="col">{{ t('stock.col.spool') }}</th><th scope="col">{{ t('stock.col.material') }}</th><th scope="col">{{ t('stock.col.left') }}</th>
            <th scope="col" class="sc-loc">{{ t('stock.col.location') }}</th><th scope="col">{{ t('stock.col.action') }}</th></tr></thead>
          <tbody>
            <tr v-for="r in shown" :key="r.id">
              <td><span class="sc-nm"><SpoolFigure :paint="spoolPaint(r.colour, r.colours)" :fraction="spoolFraction(r.remaining, r.initial) ?? 1" :size="40" />
                <span><strong>{{ r.vendor }} {{ r.name }}</strong> <span class="oui-muted">#{{ r.id }}</span>
                  <span v-if="r.use_first" class="kc-pill sc-chip">{{ t('stock.useFirst') }}</span>
                  <span v-if="slotOf(r)" class="kc-pill sc-chip on">{{ t('stock.on', { slot: slotOf(r) }) }}</span></span></span></td>
              <td>{{ r.material }}</td>
              <td class="kc-num sc-left" :class="{ 'kc-warn': r.low }">{{ fmt.grams(r.remaining) }}<template v-if="r.low"> · {{ t('stock.low') }}</template>
                <LevelBar v-if="spoolFraction(r.remaining, r.initial) !== null" class="sc-bar" :pct="Math.round(spoolFraction(r.remaining, r.initial)! * 100)"
                          :paint="spoolPaint(r.colour, r.colours) || '#888'" :level="r.low ? 'low' : ''" /></td>
              <td class="sc-loc oui-muted">{{ r.location }}</td>
              <td><Button size="small" severity="secondary" outlined :disabled="!!why || tracker.isBusy(`bind:${chosen}`)" :data-focus-key="`stock:${r.id}`" :data-stock="r.id"
                          :aria-label="t('stock.linkLabel', { id: r.id, name: `${r.vendor} ${r.name}`, slot: chosenLabel })" @click="link(r)">
                <Icon name="icon/link" /><span>{{ t('stock.linkBtn', { slot: chosenLabel }) }}</span></Button></td>
            </tr>
            <tr v-if="!shown.length"><td colspan="5" class="oui-muted">
              <template v-if="rows.length">{{ t('stock.noMatch') }} <Button text size="small" :label="t('stock.clearFilters')" @click="clear" /></template>
              <template v-else>{{ t('stock.empty') }}</template></td></tr>
          </tbody>
        </table>
      </div>
      <p v-if="s.stock?.usage && s.stock.usage !== 'unknown'" class="oui-meta">{{ tMaybe(`stock.usage.${s.stock.usage}`, '') }}</p>
    </template>
    <details class="sc-tabs"><summary>{{ t('stock.tabs.summary') }}</summary><p>{{ t('stock.tabs.body') }}</p></details>
  </section>
</template>

<style scoped>
.sc-head h2 { margin: 0; display: flex; gap: 8px; align-items: center; }
.sc-notes { display: grid; gap: 8px; margin: 8px 0; }
.sc-notes:empty { display: none; }
.sc-filters { margin-bottom: 8px; }
.sc-q { min-width: 240px; }
.sc-wrap { max-height: 360px; overflow: auto; }
.sc-wrap thead th { position: sticky; top: 0; background: var(--oui-surface); z-index: 1; }
.sc-nm { display: flex; align-items: center; gap: 8px; min-width: 0; overflow-wrap: anywhere; }
.sc-chip { font-size: 12px; margin-left: 4px; }
.sc-chip.on { border-color: var(--p-primary-color); color: var(--p-primary-color); }
.sc-tabs { margin-top: 12px; }
.sc-tabs summary { cursor: pointer; color: var(--p-primary-color); }
.sc-tabs p { margin: 8px 0 0; }
@media (max-width: 640px) { .sc-loc { display: none; } .sc-q { flex: 1 1 100%; min-width: 0; } }

.sc-left { min-width: 96px; }
.sc-bar { margin-top: 4px; height: 6px; }
</style>
