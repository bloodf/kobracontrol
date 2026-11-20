<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from 'vue';
import { OuiAppBar, OuiStatus, OuiToastHost, type OuiState } from '../shared/src/components';
import { dashboard, files, settings, spool } from '../shared/src/icons';
import ConfirmDialog from './components/ConfirmDialog.vue';
import PageMessages from './components/PageMessages.vue';
import Dashboard from './components/Dashboard.vue';
import StockView from './components/StockView.vue';
import FilesView from './components/FilesView.vue';
import SettingsView from './components/SettingsView.vue';
import { s, start, lease, link, stockVisible, type Link } from './app/store';
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
  { value: 'stock', icon: spool, label: t('nav.stock'), count: stockVisible.value ? s.stock!.stock.rows.length : undefined },
  { value: 'files', icon: files, label: t('nav.files') },
  { value: 'settings', icon: settings, label: t('nav.settings') },
]);
</script>

<template>

  <OuiAppBar v-model="s.tab" :name="t('app.brand')" :tabs="tabs" :tabs-label="t('nav.label')">
    <template #mark>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 6H7L4 9V15L7 18H10M14 6H17L20 9V15L17 18H14M4 12H20" /></svg>
    </template>
    <template #status><OuiStatus :state="STATE[link]" data-test="link">{{ t(`link.${link}`) }}</OuiStatus></template>
  </OuiAppBar>

  <!-- One main landmark; each view inside it is the tab panel of its tab: page header, the page's messages, content. -->
  <main class="kc-main">
    <div v-show="s.tab === 'dash'" class="oui-page" role="tabpanel" aria-labelledby="oui-tab-dash" data-view="dash"><Dashboard /></div>
    <div v-show="s.tab === 'stock'" class="oui-page" role="tabpanel" aria-labelledby="oui-tab-stock" data-view="stock"><StockView /></div>
    <div v-show="s.tab === 'files'" class="oui-page kc-files" role="tabpanel" aria-labelledby="oui-tab-files" data-view="files"><FilesView /></div>
    <div v-show="s.tab === 'settings'" role="tabpanel" aria-labelledby="oui-tab-settings" data-view="settings">
      <div class="kc-msgs kc-msgs-settings" data-msgs="settings" />
      <SettingsView />
    </div>
  </main>

  <!-- What the whole page has to say, once: it sits under the page header of the tab that is open (its .kc-msgs). -->
  <Teleport defer :to="`[data-msgs='${s.tab}']`"><PageMessages /></Teleport>

  <ConfirmDialog />

  <!-- What commands answered, bottom-left; on Settings it sits above the save bar. -->
  <OuiToastHost :close-label="t('common.close')" :label="t('msg.toasts')" />

</template>
