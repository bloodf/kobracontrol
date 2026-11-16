<script setup lang="ts">
import { computed } from 'vue';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiEmpty, OuiPanel, OuiStatus } from '../../shared/src/components';
import { ace } from '../../shared/src/icons';
import SlotTile from './SlotTile.vue';
import AceUnitControls from './AceUnitControls.vue';
import { s, run, tracker, controlsOff, stale } from '../app/store';
import { t } from '../core/i18n';
import { groupSlots } from '../core/logic';

// Filament: one group per feeder (the print head, each ACE), its auto-feed and drying strip, then one object card per
// slot with its filament colour, spool, amount, Spoolman spool and actions. Why feeding is off right now is said once,
// in the footer.
const groups = computed(() => groupSlots(s.status?.slots ?? []));
const unitOf = (boxId: number) => s.status?.ace_units.find(u => u.id === boxId) ?? null;
const groupName = (boxId: number) => (boxId < 0 ? t('ace.head') : t('ace.unit', { n: boxId + 1 }));
const slotName = (index: number) => t('slot.name', { n: index + 1 });
const modeText = computed(() => (s.status ? t(`ace.mode.${s.status.mode}` as 'ace.mode.toolhead') : ''));
const setAuto = (id: number, on: boolean) => run({ key: `auto:${id}`, label: t('act.autoFeed', { ace: groupName(id) }), cmd: 'auto_feed', args: { ace: id, on } });
const feedNo = computed(() => !!s.status && !s.status.can.feed && !controlsOff.value);
</script>

<template>
  <OuiPanel :title="t('ace.title')" :icon="ace" tone="magenta" data-test="ace-card">
    <template #meta><span data-test="ace-mode">{{ modeText }}</span><template v-if="stale"> · <OuiStatus state="stale">{{ t('status.lastKnownShort') }}</OuiStatus></template></template>
    <OuiEmpty v-if="!s.status" compact :icon="ace" tone="magenta" :title="t('ace.noStatus')" />
    <OuiEmpty v-else-if="!groups.length" compact :icon="ace" tone="magenta" :title="t('ace.noSlots')" />
    <div v-else class="oui-stack">
      <section v-for="g in groups" :key="g.boxId" class="kc-group" :data-box="g.boxId" :aria-labelledby="`ace-g-${g.boxId}`">
        <div class="kc-group-head">
          <h3 :id="`ace-g-${g.boxId}`" class="ace-g oui-label">{{ groupName(g.boxId) }}</h3>
          <label v-if="unitOf(g.boxId)" class="kc-inline" :for="`auto-${g.boxId}`">{{ t('ace.autoFeed') }}
            <ToggleSwitch :input-id="`auto-${g.boxId}`" :model-value="unitOf(g.boxId)!.auto_feed" :disabled="!!controlsOff || tracker.isBusy(`auto:${g.boxId}`)"
                          :aria-describedby="controlsOff ? 'kc-why' : undefined" :data-auto="g.boxId" @update:model-value="(on: boolean) => setAuto(g.boxId, on)" /></label>
        </div>
        <AceUnitControls v-if="unitOf(g.boxId)" :unit="unitOf(g.boxId)!" :label="groupName(g.boxId)" />
        <div class="oui-cards">
          <SlotTile v-for="sl in g.slots" :key="sl.global_index" :slot="sl" :label="`${groupName(g.boxId)} · ${slotName(sl.index)}`" />
        </div>
      </section>
    </div>
    <template v-if="feedNo || s.status?.box_set_failed" #footer>
      <p v-if="feedNo" id="feed-why" class="oui-meta" data-test="feed-why">{{ t('reason.noFeed') }}.</p>
      <p v-if="s.status?.box_set_failed" class="kc-why" data-tone="danger" role="alert">{{ t('ace.setFailed') }}</p>
    </template>
  </OuiPanel>
</template>

<style>
.kc-group { display: grid; gap: var(--oui-s2); }
.kc-group-head { display: flex; align-items: center; justify-content: space-between; gap: var(--oui-s2); min-height: 28px; }
.kc-group + .kc-group { padding-top: var(--oui-s3); border-top: 1px solid var(--oui-border); }
</style>
