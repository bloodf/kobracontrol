<script setup lang="ts">
import { computed } from 'vue';
import StatusCard from './StatusCard.vue';
import CameraCard from './CameraCard.vue';
import AceCard from './AceCard.vue';
import SpoolmanCard from './SpoolmanCard.vue';
import StockCard from './StockCard.vue';
import SpoolerHint from './SpoolerHint.vue';
import FirstRun from './FirstRun.vue';
import { s } from '../app/store';

// Without a certificate or a printer the cards would only be empty: the one task and its recovery come instead.
const firstRun = computed(() => s.phase === 'noCertificate' || s.phase === 'noTarget');
</script>
<template>
  <div class="db">
    <FirstRun v-if="firstRun" />
    <template v-else>
      <div class="db-grid">
        <StatusCard />
        <div class="db-side">
          <CameraCard />
        </div>
      </div>
      <AceCard />
      <SpoolmanCard />
      <SpoolerHint where="dash" />
      <StockCard />
    </template>
  </div>
</template>
<style scoped>
.db { display: grid; gap: 16px; }
.db-grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr); gap: 16px; align-items: start; }
.db-side { display: grid; gap: 16px; min-width: 0; }
@media (max-width: 900px) { .db-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
