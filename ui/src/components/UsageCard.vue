<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import Message from 'primevue/message';
import Icon from './Icon.vue';
import { s, run } from '../app/store';
import { ask } from '../core/dialog';
import { t, tn, fmt } from '../core/i18n';
import type { UsageEntry } from '../app/types';

// Prints whose filament use still has to be booked in Spoolman, or failed to book. Failed ones stay listed with
// their identity until the user marks them checked. Marking is local and audited by the plugin (usage_ack);
// nothing is booked again from here.
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
const grams = (g: Record<string, number>) => Object.entries(g).map(([k, v]) => `${slotName(k)}: ${fmt.number(v, 1)} g`).join(', ');

async function ack(e: UsageEntry) {
  const slot = slotName(e.slot);
  if (!await ask({ title: t('confirm.ack.title'), text: t('confirm.ack.text', { grams: fmt.number(e.grams ?? 0, 1), slot, file: fileName(e.file) }),
    yes: t('confirm.ack.yes'), no: t('common.goBack') })) return;
  const r = await run({ key: `ack:${e.id}`, label: t('act.usageAck'), cmd: 'usage_ack', args: { id: e.id } });
  if (r.ok) s.usage = r.result;
}
</script>
<template>
  <section v-if="show" class="kc-card uc" :class="{ warn: failed.length || u?.save_error || s.usageError }" aria-labelledby="usage-h" data-test="usage-card">
    <h2 id="usage-h"><Icon name="icon/spoolman" /> {{ t('usage.title') }}
      <span v-if="failed.length" class="kc-pill">{{ tn('usage.count', failed.length) }}</span></h2>
    <div role="alert" class="uc-notes">
      <Message v-if="s.usageError" severity="error">{{ t('usage.loadError', { error: s.usageError }) }}</Message>
      <Message v-if="u?.save_error" severity="error">{{ t('usage.saveError', { error: u.save_error }) }}</Message>
      <Message v-if="u?.restore_notice" severity="warn">{{ t('usage.notice', { text: u.restore_notice }) }}</Message>
    </div>
    <template v-if="waiting.length">
      <p class="uc-intro">{{ tn('usage.tracking', waiting.length) }}</p>
      <ul class="uc-wait" data-test="usage-pending"><li v-for="w in waiting" :key="w.printer + w.file"><strong>{{ fileName(w.file) }}</strong>
        <span class="oui-meta"> · {{ grams(w.grams) }}</span></li></ul>
    </template>
    <template v-if="failed.length">
      <p class="uc-intro">{{ t('usage.intro') }}</p>
      <div class="oui-table-wrap">
        <table class="kc-table">
          <thead><tr><th scope="col">{{ t('usage.col.file') }}</th><th scope="col">{{ t('usage.col.slot') }}</th><th scope="col">{{ t('usage.col.grams') }}</th>
            <th scope="col">{{ t('usage.col.spool') }}</th><th scope="col">{{ t('usage.col.when') }}</th><th scope="col">{{ t('usage.col.why') }}</th>
            <th scope="col">{{ t('usage.col.action') }}</th></tr></thead>
          <tbody>
            <tr v-for="e in failed" :key="e.id">
              <td class="uc-file">{{ fileName(e.file) }}<div class="oui-meta">{{ e.printer_name || e.printer }}</div></td>
              <td>{{ slotName(e.slot) }}</td>
              <td class="kc-num">{{ fmt.number(e.grams ?? 0, 1) }} g</td>
              <td>{{ e.spool != null ? '#' + e.spool : t('usage.noSpool') }}</td>
              <td>{{ when(e) }}</td>
              <td class="oui-meta uc-why">{{ e.error }}</td>
              <td><Button size="small" severity="secondary" outlined :label="t('usage.ack')"
                          :aria-label="t('usage.ackLabel', { slot: slotName(e.slot), file: fileName(e.file) })" :data-focus-key="`ack:${e.id}`" :data-ack="e.id" @click="ack(e)" /></td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <details v-if="u?.acknowledged.length" class="uc-recent"><summary>{{ t('usage.recent', { total: u.acknowledged_total }) }}</summary>
      <ul><li v-for="e in u.acknowledged" :key="e.id">{{ fileName(e.file) }} · {{ slotName(e.slot) }} · {{ fmt.number(e.grams ?? 0, 1) }} g ·
        {{ t('usage.checkedAt', { when: e.acknowledged_at ? fmt.dateTime(e.acknowledged_at) : t('usage.unknownTime') }) }}</li></ul></details>
  </section>
</template>
<style scoped>
.uc.warn { border-color: var(--oui-warning); }
.uc h2 { flex-wrap: wrap; }
.uc-notes { display: grid; gap: 8px; } .uc-notes:empty { display: none; }
.uc-intro { margin: 8px 0; }
.uc-wait { margin: 0 0 8px; padding-left: 20px; }
.uc-file, .uc-why { overflow-wrap: anywhere; max-width: 260px; }
.uc-recent summary { cursor: pointer; color: var(--p-primary-color); }
</style>
