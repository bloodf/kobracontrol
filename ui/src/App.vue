<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from 'vue';
import { OuiAppBar, OuiStatus, type OuiState } from '../shared/src/components';
import { dashboard, files, settings } from '../shared/src/icons';
import ConfirmDialog from './components/ConfirmDialog.vue';
import PageMessages from './components/PageMessages.vue';
import Dashboard from './components/Dashboard.vue';
import FilesView from './components/FilesView.vue';
import SettingsView from './components/SettingsView.vue';
import { s, start, lease, link, type Link } from './app/store';
import { installSettings } from './app/settings';
import { t } from './core/i18n';

const stop = start();
const stopSettings = installSettings();
onBeforeUnmount(stopSettings);
onBeforeUnmount(stop);
watch(() => s.tab, () => lease());

// The page's one connection state (store.link): the same word the banner, the job and the controls go by.
const STATE: Record<Link, OuiState> = { connecting: 'connecting', connected: 'ok', offline: 'offline', noCertificate: 'warn', noTarget: 'idle' };
const tabs = computed(() => [
  { value: 'dash', icon: dashboard, label: t('nav.dash') },
  { value: 'files', icon: files, label: t('nav.files') },
  { value: 'settings', icon: settings, label: t('nav.settings') },
]);
</script>

<template>

  <OuiAppBar v-model="s.tab" :name="t('app.brand')" :tabs="tabs" :tabs-label="t('nav.label')">
    <template #mark>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 6H7L4 9V15L7 18H10M14 6H17L20 9V15L17 18H14M4 12H20" /></svg>
    </template>
    <template #status>
      <OuiStatus :state="STATE[link]" data-test="link">{{ t(`link.${link}`) }}</OuiStatus>
      <span v-if="s.info" class="oui-truncate kc-addr">{{ s.info.printer }} · {{ s.info.address }}</span>
    </template>
  </OuiAppBar>

  <PageMessages />

  <main v-show="s.tab === 'dash'" class="oui-page" role="tabpanel" aria-labelledby="oui-tab-dash"><Dashboard /></main>
  <main v-show="s.tab === 'files'" class="oui-page" role="tabpanel" aria-labelledby="oui-tab-files"><FilesView /></main>
  <main v-show="s.tab === 'settings'" role="tabpanel" aria-labelledby="oui-tab-settings"><SettingsView /></main>

  <ConfirmDialog />

</template>
