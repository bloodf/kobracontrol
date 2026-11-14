<script setup lang="ts">
import Button from 'primevue/button';
import Icon from './Icon.vue';
import CertFinder from './CertFinder.vue';
import { s, hello } from '../app/store';
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
        <h2 id="fr-h">{{ t('fr.target.title') }}</h2>
        <p>{{ t('fr.target.body') }}</p>
        <ol class="fr-steps"><li>{{ t('fr.target.step1') }}</li><li>{{ t('fr.target.step2') }}</li></ol>
      </div>
    </div>
    <div class="kc-row"><Button :label="t('common.openSettings')" @click="s.tab = 'settings'" />
      <Button severity="secondary" outlined :label="t('common.retry')" @click="hello()" /></div>
    <p class="oui-meta fr-detail">{{ t('target.detail', { error: s.error }) }}</p>
  </section>
</template>

<style scoped>
.fr { display: grid; gap: 12px; max-width: 760px; }
.fr-top { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.fr-text { flex: 1 1 320px; min-width: 0; }
.fr-text h2 { margin: 0 0 8px; }
.fr-text p { margin: 0 0 8px; }
.fr-steps { margin: 0; padding-left: 20px; }
.fr-detail { margin: 0; overflow-wrap: anywhere; }
</style>
