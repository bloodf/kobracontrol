<script setup lang="ts">
import Button from 'primevue/button';
import Icon from './Icon.vue';
import CertFinder from './CertFinder.vue';
import { s, searchAgain, choosePrinter, tracker } from '../app/store';
import { t } from '../core/i18n';
</script>

<!-- First-run states: each is one clear task with its recovery. -->
<template>
  <section v-if="s.phase === 'noCertificate'" class="kc-card fr" aria-labelledby="fr-h" data-test="first-run-cert">
    <div class="fr-top"><Icon name="spot/not-connected" :size="96" />
      <div class="fr-text">
        <h2 id="fr-h">{{ t('fr.cert.title') }}</h2>
        <p>{{ t('fr.cert.why') }}</p>
        <p>{{ t('fr.cert.how') }}</p>
      </div>
    </div>
    <CertFinder id-prefix="fr" />
    <p class="oui-meta fr-detail">{{ t('target.detail', { error: s.error }) }}</p>
  </section>
  <section v-else-if="s.phase === 'noTarget'" class="kc-card fr" aria-labelledby="fr-h" data-test="first-run-target">
    <div class="fr-top"><Icon name="spot/not-connected" :size="96" />
      <div class="fr-text">
        <h2 id="fr-h">{{ s.candidates.length ? t('fr.pick.title') : t('fr.target.title') }}</h2>
        <p data-test="fr-target-why">{{ s.error }}</p>
        <p v-if="!s.candidates.length">{{ t('fr.target.body') }}</p>
      </div>
    </div>
    <!-- Several Kobra X answered: pick one once; the plugin remembers it for this printer preset. -->
    <ul v-if="s.candidates.length" class="fr-pick" data-test="fr-candidates">
      <li v-for="c in s.candidates" :key="c.ip" class="kc-row">
        <span><strong>{{ c.name || t('app.printer') }}</strong> <span class="oui-meta">{{ c.model }} · {{ c.ip }}</span></span>
        <span class="kc-spacer" />
        <Button size="small" :label="t('fr.pick.use')" :loading="tracker.isBusy('choose')" :data-pick-ip="c.ip" @click="choosePrinter(c.ip)" />
      </li>
    </ul>
    <div class="kc-row"><Button :label="t('settings.searchAgain')" :loading="tracker.isBusy('search')" data-test="search-again" @click="searchAgain()" />
      <Button severity="secondary" outlined :label="t('common.openSettings')" @click="s.tab = 'settings'" /></div>
  </section>
</template>

<style scoped>
.fr { display: grid; gap: 12px; max-width: 760px; }
.fr-top { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.fr-text { flex: 1 1 320px; min-width: 0; }
.fr-text h2 { margin: 0 0 8px; }
.fr-text p { margin: 0 0 8px; }
.fr-pick { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.fr-detail { margin: 0; overflow-wrap: anywhere; }
</style>
