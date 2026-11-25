<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import KcAlert from './KcAlert.vue';
import { printer } from '@orca-plugins/ui-foundation/src/icons';
import * as bridge from '../core/bridge';
import { config } from '../app/settings';
import { openSettings } from '../app/store';
import { t } from '../core/i18n';

// How to print from OrcaSlicer's own Print and Send with a Kobra X preset that does not use the kobracontrol printer
// agent yet. An OctoPrint physical printer is called out: the Kobra X has no OctoPrint server, so OrcaSlicer only says
// "Could not connect to OctoPrint". The steps hint closes for the session, or for good with "Don't show again"; the
// OctoPrint warning comes back while the preset still sends to OctoPrint.
const setup = computed(() => config.value?.setup ?? null);
const viaAgent = computed(() => setup.value?.agent === 'kobracontrol');
const octoprint = computed(() => !!setup.value?.kobra && !viaAgent.value && setup.value?.host_type === 'octoprint' && !!setup.value?.host);
// Another agent (Kobralink's "moonraker", say) is told by the page's own notice (store.otherAgent).
const steps = computed(() => !!setup.value?.kobra && !setup.value?.agent && !octoprint.value && !config.value?.settings.setup_hint_dismissed);
const dismiss = () => bridge.post({ type: 'save_settings', settings: { setup_hint_dismissed: true } });
</script>

<template>
  <KcAlert :show="octoprint" :icon="printer" tone="warn" :title="t('setup.octo.title')" data-test="setup-octoprint"
             :dismiss-key="`setup-octoprint:${setup?.host}`">
    {{ t('setup.octo.body', { host: setup?.host ?? '' }) }}
    <ol class="kc-steps"><li>{{ t('req.agents.step1') }}</li><li>{{ t('req.agents.step2') }}</li></ol>
    <p class="kc-steps-alt">{{ t('setup.octo.bridge') }}</p>
    <template #actions><Button size="small" severity="secondary" :label="t('setup.octo.bridgeBtn')" data-test="setup-octo-bridge" @click="openSettings('bridge-h')" /></template>
  </KcAlert>
  <KcAlert :show="steps" :icon="printer" tone="info" :title="t('setup.title')" data-test="setup-steps"
             dismiss-key="setup-steps">
    {{ t('setup.body') }}
    <ol class="kc-steps"><li>{{ t('req.agents.step1') }}</li><li>{{ t('req.agents.step2') }}</li></ol>
    <template #actions><Button size="small" severity="secondary" text :label="t('spooler.dismiss')" data-test="setup-dismiss" @click="dismiss" /></template>
  </KcAlert>
</template>

<style>
.kc-steps { margin: var(--oui-s1) 0 0; padding-inline-start: 1.25em; }
.kc-steps-alt { margin: var(--oui-s1) 0 0; }
</style>
