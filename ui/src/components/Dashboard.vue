<script setup lang="ts">
import { computed } from 'vue';
import JobCard from './JobCard.vue';
import TempPanel from './TempPanel.vue';
import MotionPanel from './MotionPanel.vue';
import CameraCard from './CameraCard.vue';
import AceCard from './AceCard.vue';
import StockCard from './StockCard.vue';
import SpoolerHint from './SpoolerHint.vue';
import UsageCard from './UsageCard.vue';
import FirstRun from './FirstRun.vue';
import { s } from '../app/store';

// Without a certificate or a printer the panels would only be empty: the one task and its recovery come instead.
const firstRun = computed(() => s.phase === 'noCertificate' || s.phase === 'noTarget');
</script>

<template>
  <FirstRun v-if="firstRun" />

  <template v-else>
    <UsageCard />
    <SpoolerHint where="dash" />

    <div class="kc-grid">
      <div class="oui-stack" data-test="machine">
        <JobCard />
        <TempPanel />
        <MotionPanel />
      </div>
      <div class="oui-stack" data-test="filament">
        <CameraCard />
        <AceCard />
      </div>
      <div class="kc-stock"><StockCard /></div>
    </div>
  </template>
</template>
