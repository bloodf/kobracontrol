<script setup lang="ts">
import { computed } from 'vue';
import Icon from './Icon.vue';
import SlotTile from './SlotTile.vue';
import AceUnitControls from './AceUnitControls.vue';
import { s, controlsOff } from '../app/store';
import { t } from '../core/i18n';
import { groupSlots } from '../core/logic';

const groups = computed(() => groupSlots(s.status?.slots ?? []));
const unitOf = (boxId: number) => s.status?.ace_units.find(u => u.id === boxId) ?? null;
const groupName = (boxId: number) => (boxId < 0 ? t('ace.head') : t('ace.unit', { n: boxId + 1 }));
const slotName = (index: number) => t('slot.name', { n: index + 1 });
const modeText = computed(() => (s.status ? t(`ace.mode.${s.status.mode}` as 'ace.mode.toolhead') : ''));
</script>

<template>
  <section class="kc-card" aria-labelledby="ace-h" data-test="ace-card">
    <div class="kc-row">
      <h2 id="ace-h" class="ace-h"><Icon name="icon/ace" /> {{ t('ace.title') }}</h2>
      <span class="oui-meta" data-test="ace-mode">{{ modeText }}</span>
    </div>
    <p v-if="!s.status" class="oui-muted">{{ t('ace.noStatus') }}</p>
    <p v-else-if="!groups.length" class="oui-muted">{{ t('ace.noSlots') }}</p>
    <p v-if="s.status && !s.status.can.feed && !controlsOff" class="kc-why" data-test="feed-why">{{ t('reason.noFeed') }}</p>
    <p v-if="s.status?.box_set_failed" class="kc-err" role="alert">{{ t('ace.setFailed') }}</p>
    <div v-for="g in groups" :key="g.boxId" class="ace-group" :data-box="g.boxId">
      <h3 class="ace-g">{{ groupName(g.boxId) }}</h3>
      <AceUnitControls v-if="unitOf(g.boxId)" :unit="unitOf(g.boxId)!" :label="groupName(g.boxId)" />
      <div class="ace-grid">
        <SlotTile v-for="sl in g.slots" :key="sl.global_index" :slot="sl" :label="`${groupName(g.boxId)} · ${slotName(sl.index)}`" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.ace-h { margin: 0; display: flex; gap: 8px; align-items: center; }
.ace-group { margin-top: 16px; }
.ace-g { margin: 0 0 4px; }
.ace-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(264px, 1fr)); gap: 12px; }
</style>
