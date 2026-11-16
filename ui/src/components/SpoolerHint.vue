<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import { OuiBanner } from '../../shared/src/components';
import { spool } from '../../shared/src/icons';
import * as bridge from '../core/bridge';
import { config } from '../app/settings';
import { stockVisible } from '../app/store';
import { t } from '../core/i18n';

// Spooler, the sibling plugin: suggested once on the Dashboard (until dismissed), stated in Settings.
const props = defineProps<{ where: 'dash' | 'settings' }>();
const sp = computed(() => config.value?.spooler ?? null);
const show = computed(() => !!sp.value && (props.where === 'settings' || (!sp.value.installed && !sp.value.dismissed)));
const dismiss = () => bridge.post({ type: 'save_settings', settings: { spooler_hint_dismissed: true } });
</script>

<template>
  <template v-if="show && sp">
    <div v-if="sp.installed" class="oui-stack sph">
      <p>{{ t('spooler.installed') }}</p>
      <p v-if="where === 'settings' && !stockVisible" class="oui-meta" data-test="spooler-no-stock">{{ t('spooler.noStock') }}</p>
    </div>
    <OuiBanner v-else :icon="spool" tone="info" :title="t('spooler.title')">
      {{ t('spooler.suggest') }} <a :href="sp.url">{{ sp.url }}</a>
      <template v-if="!sp.dismissed" #actions><Button size="small" severity="secondary" text :label="t('spooler.dismiss')" @click="dismiss" /></template>
    </OuiBanner>
  </template>
</template>
