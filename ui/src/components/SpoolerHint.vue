<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import KcAlert from './KcAlert.vue';
import { spool } from '@orca-plugins/ui-foundation/src/icons';
import * as bridge from '../core/bridge';
import { config } from '../app/settings';
import { t } from '../core/i18n';

// Spooler, the sibling plugin: suggested on the Dashboard while it is not installed. The close button hides it for
// this session; "Don't show again" for good. Settings lists it with what Kobra Control needs on this computer.
const sp = computed(() => config.value?.spooler ?? null);
const show = computed(() => !!sp.value && !sp.value.installed && !sp.value.dismissed);
const dismiss = () => bridge.post({ type: 'save_settings', settings: { spooler_hint_dismissed: true } });
</script>

<template>
  <KcAlert :show="show" :icon="spool" tone="info" :title="t('spooler.title')" :dismiss-key="`spooler-suggest:${sp?.url}`">
    {{ t('spooler.suggest') }} <a :href="sp?.url">{{ sp?.url }}</a>
    <template #actions><Button size="small" severity="secondary" text :label="t('spooler.dismiss')" @click="dismiss" /></template>
  </KcAlert>
</template>
