<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import { OuiEmpty, OuiIcon, OuiPanel } from '@orca-plugins/ui-foundation/src/components';
import { printer, refresh, settings } from '@orca-plugins/ui-foundation/src/icons';
import CertFinder from './CertFinder.vue';
import { s, openSettings, searchAgain, choosePrinter, tracker } from '../app/store';
import { t } from '../core/i18n';
import art from '../assets/kobra-connect.webp';

// First-run states: each is one clear task with its recovery. A printer found on the network is offered, never used by
// itself, even when it is the only one; the user picks it once.
const different = computed(() => s.candidates.some(c => c.different));
const title = computed(() => (different.value ? t('fr.pick.different') : s.candidates.length > 1 ? t('fr.pick.title') : s.candidates.length ? t('fr.pick.one') : t('fr.target.title')));
</script>

<template>
  <OuiPanel v-if="s.phase === 'noCertificate'" class="kc-first" flush :aria-label="t('fr.cert.title')" data-test="first-run-cert">
    <!-- wrapped: OuiEmpty fills its parent's height (min-height: 100%), which would push the form out of the panel -->
    <div><OuiEmpty :image="art" :title="t('fr.cert.title')">
      {{ t('fr.cert.why') }} {{ t('fr.cert.how') }}
    </OuiEmpty></div>
    <div class="kc-first-form"><CertFinder id-prefix="fr" /></div>
    <template #footer><p class="oui-meta kc-first-detail">{{ t('target.detail', { error: s.error }) }}</p></template>
  </OuiPanel>

  <OuiPanel v-else-if="s.phase === 'noTarget'" class="kc-first" flush :aria-label="title" data-test="first-run-target">
    <div><OuiEmpty :image="art" :title="title">
      <span data-test="fr-target-why">{{ s.error }}</span>
      <template v-if="!s.candidates.length">{{ ' ' + t('fr.target.body') }}</template>
      <template #actions>
        <Button :severity="s.candidates.length ? 'secondary' : undefined" :label="t('common.openSettings')" @click="openSettings('conn-h')"><template #icon><OuiIcon :icon="settings" :size="14" /></template></Button>
        <Button severity="secondary" :label="t('settings.searchAgain')" :loading="tracker.isBusy('search')" data-test="search-again" @click="searchAgain()"><template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
      </template>
    </OuiEmpty></div>
    <!-- Kobra X printers that answered: pick one once; the plugin remembers it for a kobracontrol printer preset. -->
    <ul v-if="s.candidates.length" class="kc-pick" data-test="fr-candidates">
      <li v-for="c in s.candidates" :key="c.ip">
        <OuiIcon :icon="printer" :size="16" tile tone="cobalt" />
        <span class="kc-pick-id"><span class="oui-strong">{{ c.name || t('app.printer') }}</span><span class="oui-meta oui-mono">{{ [c.model, c.ip].filter(Boolean).join(' · ') }}</span></span>
        <Button size="small" severity="secondary" :label="c.needs_allow ? t('fr.pick.allow') : t('fr.pick.use')" :loading="tracker.isBusy('choose')" :data-pick-ip="c.ip" @click="choosePrinter(c)" />
      </li>
    </ul>
  </OuiPanel>
</template>

<style>
.kc-first-form { padding: 0 var(--oui-s5) var(--oui-s5); }
.kc-first-detail { overflow-wrap: anywhere; }
.kc-pick { list-style: none; margin: 0; padding: 0 var(--oui-s4) var(--oui-s4); display: grid; gap: var(--oui-s2); }
.kc-pick > li { display: flex; align-items: center; gap: var(--oui-s3); padding: var(--oui-s2) var(--oui-s3); border-radius: var(--oui-radius); background: var(--oui-raised); }
.kc-pick-id { display: grid; flex: 1 1 auto; min-width: 0; }
</style>
