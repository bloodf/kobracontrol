<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import Button from 'primevue/button';
import { OuiBanner, OuiIcon, OuiPanel } from '../../shared/src/components';
import { check, eye, spoolman, warning } from '../../shared/src/icons';
import { s, run, tracker } from '../app/store';
import { ask } from '../core/dialog';
import { t, tn, fmt } from '../core/i18n';
import type { UsageEntry } from '../app/types';

// Prints whose filament use still has to be booked in Spoolman, or failed to book. Failed ones stay listed with their
// identity until the user marks them checked; marking is local and audited by the plugin (usage_ack); nothing is booked
// again from here. One banner says it; Review opens the list with "I checked it in Spoolman". Closing a banner holds
// for the entries it names: a new unconfirmed or waiting print brings it back.
const u = computed(() => s.usage);
const failed = computed(() => u.value?.unconfirmed ?? []);
const waiting = computed(() => u.value?.pending ?? []);
const show = computed(() => !!(failed.value.length || waiting.value.length || u.value?.save_error || u.value?.restore_notice || s.usageError));
const fileName = (file: string | undefined) => (file ? file.split('/').pop() : '') || t('common.unknown');
const when = (e: UsageEntry) => (e.at ? fmt.dateTime(e.at) : t('usage.unknownTime'));
const slotName = (g: number | string) => {
  const sl = s.status?.slots.find(x => x.global_index === Number(g));
  const n = sl ? sl.index + 1 : Number(g) + 1;
  return sl && sl.box_id >= 0 ? `${t('ace.unit', { n: sl.box_id + 1 })} · ${t('slot.name', { n })}` : t('slot.name', { n });
};
const grams = (g: Record<string, number>) => fmt.list(Object.entries(g).map(([k, v]) => fmt.pair(slotName(k), `${fmt.number(v, 1)} g`)));
const open = ref(false);
watch(() => failed.value.length, n => { if (!n) open.value = false; });
const first = computed(() => {
  const e = failed.value[0];
  if (!e) return '';
  return [fileName(e.file), `${fmt.number(e.grams ?? 0, 1)} g`, e.spool != null ? t('usage.spool', { id: e.spool }) : t('usage.noSpool'), e.error,
    failed.value.length > 1 ? t('usage.more', { n: failed.value.length - 1 }) : ''].filter(Boolean).join(' · ');
});

async function ack(e: UsageEntry) {
  const slot = slotName(e.slot);
  if (!await ask({ title: t('confirm.ack.title'), text: t('confirm.ack.text', { grams: fmt.number(e.grams ?? 0, 1), slot, file: fileName(e.file) }),
    yes: t('confirm.ack.yes'), no: t('common.goBack') })) return;
  const r = await run({ key: `ack:${e.id}`, label: t('act.usageAck'), cmd: 'usage_ack', args: { id: e.id } });
  if (r.ok) s.usage = r.result;
}
</script>

<template>
  <!-- v-show, not v-if: the banners stay mounted so a closed one is forgotten when its condition clears. -->
  <div v-show="show" class="oui-stack" data-test="usage-card">
    <div role="alert" class="kc-live uc-alerts">
      <OuiBanner :show="!!s.usageError" tone="error" :title="t('usage.loadError', { error: s.usageError })" dismissible :dismiss-key="`usage-load:${s.usageError}`" :close-label="t('common.close')" />
      <OuiBanner :show="!!u?.save_error" tone="error" :title="t('usage.saveError', { error: u?.save_error })" dismissible :dismiss-key="`usage-save:${u?.save_error}`" :close-label="t('common.close')" />
      <OuiBanner :show="!!u?.restore_notice" tone="warn" :title="t('usage.notice', { text: u?.restore_notice })" dismissible :dismiss-key="`usage-restore:${u?.restore_notice}`" :close-label="t('common.close')" />
    </div>

    <OuiBanner :show="failed.length > 0" tone="warn" :title="tn('usage.banner', failed.length)" data-test="usage-banner"
               dismissible :dismiss-key="`unconfirmed:${failed.map(e => e.id).join(',')}`" :close-label="t('common.close')">
      {{ first }}
      <template #actions>
        <Button size="small" severity="secondary" :label="open ? t('usage.hide') : t('usage.review')" :aria-expanded="open" aria-controls="usage-list"
                data-focus-key="usage-review" data-test="usage-review" @click="open = !open"><template #icon><OuiIcon :icon="eye" :size="14" /></template></Button>
      </template>
    </OuiBanner>

    <OuiBanner :show="waiting.length > 0" tone="info" :icon="spoolman" :title="tn('usage.tracking', waiting.length)" data-test="usage-pending"
               dismissible :dismiss-key="`usage-pending:${waiting.map(w => w.printer + '|' + w.file).join(',')}`" :close-label="t('common.close')">
      <template v-for="(w, i) in waiting" :key="w.printer + w.file"><template v-if="i"> · </template><strong>{{ fileName(w.file) }}</strong> ({{ grams(w.grams) }})</template>
    </OuiBanner>

    <OuiPanel v-if="open && failed.length" id="usage-list" :icon="warning" tone="warn" flush aria-labelledby="usage-h" :hint="t('usage.intro')" :hint-label="t('usage.title')">
      <template #title><span id="usage-h">{{ t('usage.title') }}</span></template>
      <template #meta><span class="oui-chip" data-tone="warn">{{ tn('usage.count', failed.length) }}</span></template>
      <div class="oui-table-wrap">
        <table class="kc-table">
          <thead><tr><th scope="col">{{ t('usage.col.file') }}</th><th scope="col">{{ t('usage.col.slot') }}</th><th scope="col" class="oui-num">{{ t('usage.col.grams') }}</th>
            <th scope="col">{{ t('usage.col.spool') }}</th><th scope="col">{{ t('usage.col.when') }}</th><th scope="col">{{ t('usage.col.why') }}</th>
            <th scope="col" class="oui-end"><span class="oui-sr">{{ t('usage.col.action') }}</span></th></tr></thead>
          <tbody>
            <tr v-for="e in failed" :key="e.id">
              <td class="uc-file"><span class="oui-strong">{{ fileName(e.file) }}</span><div class="oui-meta">{{ e.printer_name || e.printer }}</div></td>
              <td>{{ slotName(e.slot) }}</td>
              <td class="oui-num">{{ fmt.number(e.grams ?? 0, 1) }} g</td>
              <td :class="{ 'oui-muted': e.spool == null }">{{ e.spool != null ? '#' + e.spool : t('usage.noSpool') }}</td>
              <td>{{ when(e) }}</td>
              <td class="oui-meta uc-why">{{ e.error }}</td>
              <td class="oui-end"><Button size="small" severity="secondary" :label="t('usage.ack')" :loading="tracker.isBusy(`ack:${e.id}`)"
                          :aria-label="t('usage.ackLabel', { slot: slotName(e.slot), file: fileName(e.file) })" :data-focus-key="`ack:${e.id}`" :data-ack="e.id" @click="ack(e)">
                <template #icon><OuiIcon :icon="check" :size="14" /></template></Button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </OuiPanel>

    <!-- What was marked checked recently, whether or not anything is still unconfirmed. -->
    <details v-if="u?.acknowledged.length" class="kc-disclose uc-history" data-test="usage-recent"><summary>{{ t('usage.recent', { total: u.acknowledged_total }) }}</summary>
      <ul class="oui-meta uc-recent"><li v-for="e in u.acknowledged" :key="e.id">{{ fileName(e.file) }} · {{ slotName(e.slot) }} · {{ fmt.number(e.grams ?? 0, 1) }} g ·
        {{ t('usage.checkedAt', { when: e.acknowledged_at ? fmt.dateTime(e.acknowledged_at) : t('usage.unknownTime') }) }}</li></ul></details>
  </div>
</template>

<style>
.uc-file, .uc-why { overflow-wrap: anywhere; max-width: 260px; }
.uc-alerts:empty { display: none; }   /* no stack gap for an empty live region; it comes back with its first message */
.uc-history { padding-inline: var(--oui-s2); }
.uc-recent { margin: 0; padding-inline-start: var(--oui-s4); }
</style>
