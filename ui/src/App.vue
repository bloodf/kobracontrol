<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from 'vue';
import Tabs from 'primevue/tabs';
import TabList from 'primevue/tablist';
import Tab from 'primevue/tab';
import TabPanels from 'primevue/tabpanels';
import TabPanel from 'primevue/tabpanel';
import Icon from './components/Icon.vue';
import ConfirmDialog from './components/ConfirmDialog.vue';
import NoticeArea from './components/NoticeArea.vue';
import TargetBanner from './components/TargetBanner.vue';
import Dashboard from './components/Dashboard.vue';
import FilesView from './components/FilesView.vue';
import SettingsView from './components/SettingsView.vue';
import { s, start, lease, link } from './app/store';
import { installSettings } from './app/settings';
import { t } from './core/i18n';

const stop = start();
const stopSettings = installSettings();
onBeforeUnmount(stopSettings);
onBeforeUnmount(stop);
watch(() => s.tab, () => lease());

const linkText = computed(() => t(`link.${link.value}`));
const linkOk = computed(() => link.value === 'connected');
const sections = [
  { value: 'dash', icon: 'icon/dashboard', label: 'nav.dash' },
  { value: 'files', icon: 'icon/files', label: 'nav.files' },
  { value: 'settings', icon: 'icon/settings', label: 'nav.settings' },
] as const;
</script>

<template>
  <Tabs v-model:value="s.tab" class="kc-shell">
    <header class="oui-header kc-head">
      <span class="kc-brand">
        <svg viewBox="0 0 24 24" aria-hidden="true" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="4"/><path d="M8 8v8M8 12l4-4M8 12l4 4M16 8v8"/></svg>
        <h1>{{ t('app.brand') }}</h1>
      </span>
      <span class="kc-pill" :class="{ ok: linkOk }" data-test="link">{{ linkText }}</span>
      <span v-if="s.info" class="oui-meta kc-addr">{{ s.info.printer }} · {{ s.info.address }}</span>
      <TabList class="kc-nav" :aria-label="t('nav.label')">
        <Tab v-for="sec in sections" :key="sec.value" :value="sec.value" :data-tab="sec.value">
          <Icon :name="sec.icon" /> <span>{{ t(sec.label) }}</span>
        </Tab>
      </TabList>
    </header>
    <main class="kc-main">
      <TargetBanner />
      <NoticeArea />
      <TabPanels class="kc-panels">
        <TabPanel value="dash"><Dashboard /></TabPanel>
        <TabPanel value="files"><FilesView /></TabPanel>
        <TabPanel value="settings"><SettingsView /></TabPanel>
      </TabPanels>
    </main>
    <ConfirmDialog />
  </Tabs>
</template>

<style>
html, body, #app { min-height: 100%; }
body { background: var(--oui-background); }
.kc-shell { display: flex; flex-direction: column; min-height: 100vh; background: var(--oui-background); }
.kc-head { position: sticky; top: 0; z-index: 5; }
.kc-brand { display: inline-flex; align-items: center; gap: 8px; }
.kc-brand h1 { margin: 0; font-size: 20px; }
.kc-pill { white-space: nowrap; padding: 2px 10px; border-radius: 999px; border: 1px solid var(--oui-border); font-size: 12px; }
.kc-pill.ok { border-color: var(--p-primary-color); color: var(--p-primary-color); }
.kc-addr { overflow-wrap: anywhere; }
.kc-nav { margin-left: auto; min-width: 0; }
.kc-nav .p-tab { display: inline-flex; gap: 6px; align-items: center; }
.kc-main { flex: 1; padding: 16px; display: flex; flex-direction: column; min-width: 0; }
.kc-main > * { margin-bottom: 16px; }
.kc-main > :empty { margin-bottom: 0; }   /* live regions stay in the DOM, without leaving a gap */
.kc-panels.p-tabpanels { padding: 0; background: transparent; }
.kc-card { padding: 16px; background: var(--oui-surface); border: 1px solid var(--oui-border); border-radius: 12px; min-width: 0; }
.kc-card > h2 { display: flex; align-items: center; gap: 8px; margin: 0 0 12px; }
.kc-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.kc-spacer { flex: 1; }
.kc-sw { display: inline-block; flex: none; width: 16px; height: 16px; border-radius: 50%; border: 1px solid var(--oui-control-border, var(--oui-border)); }
.kc-why { color: var(--oui-muted); font-size: 12px; }
.kc-table { width: 100%; border-collapse: collapse; }
.kc-table th, .kc-table td { padding: 8px; border-bottom: 1px solid var(--oui-border); text-align: left; vertical-align: middle; }
.kc-table th { color: var(--oui-muted); font-size: 12px; font-weight: 600; }
.kc-warn { color: var(--oui-warning); }
.kc-err { color: var(--oui-danger); }
.kc-num { font-variant-numeric: tabular-nums; white-space: nowrap; }
@media (max-width: 720px) { .kc-main { padding: 12px; } .kc-nav { margin-left: 0; width: 100%; overflow-x: auto; } }
</style>
