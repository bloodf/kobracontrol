<script setup lang="ts">
import { computed } from 'vue';
import Message from 'primevue/message';
import Button from 'primevue/button';
import { s, hello, link, printerName, statusAge, STALE_STATUS_S } from '../app/store';
import { t, fmt } from '../core/i18n';

// When the plugin tries again by itself: shown so the page never has to flip to "Connecting" between attempts.
const retryIn = computed(() => (s.retryAt ? Math.max(0, Math.ceil(s.retryAt - s.now / 1000)) : 0));
</script>
<template>
  <div role="status" aria-live="polite" data-test="target-banner">
    <!-- No certificate / no printer: the Dashboard shows the one task; the other tabs say what is missing. -->
    <Message v-if="link === 'noCertificate' && s.tab !== 'dash'" severity="warn">
      <strong>{{ t('fr.cert.title') }}</strong>
      <p class="tb-p">{{ t('banner.cert') }}</p>
      <Button size="small" :label="t('banner.toDashboard')" @click="s.tab = 'dash'" />
    </Message>
    <Message v-else-if="link === 'noTarget' && s.tab !== 'dash'" severity="warn">
      <strong>{{ t('fr.target.title') }}</strong>
      <p class="tb-p">{{ t('banner.target') }}</p>
      <Button v-if="s.tab !== 'settings'" size="small" :label="t('common.openSettings')" @click="s.tab = 'settings'" />
    </Message>
    <Message v-else-if="link === 'offline'" severity="error">
      <strong>{{ t('target.offline.title') }}</strong>
      <p class="tb-p">{{ t('target.offline.body', { printer: printerName, error: s.offline || s.error }) }}</p>
      <p v-if="retryIn" class="tb-p oui-meta" data-test="retry-in">{{ t('target.retryIn', { n: retryIn }) }}</p>
      <Button size="small" severity="secondary" outlined :label="t('common.retry')" @click="hello(true)" />
    </Message>
    <Message v-else-if="link === 'connecting'" severity="secondary">{{ t('target.connecting') }}</Message>
    <Message v-else-if="s.status && statusAge > STALE_STATUS_S" severity="warn">{{ t('target.stale', { age: fmt.ago(s.statusAt / 1000, s.now / 1000) }) }}</Message>
    <!-- Not part of the chain above: a changed printer certificate is shown on every tab while it lasts. -->
    <Message v-if="s.status?.tls?.changed_from" severity="warn" data-test="tls-changed">
      <strong>{{ t('tls.changed.title') }}</strong>
      <p class="tb-p">{{ t('tls.changed.body', { printer: printerName }) }}</p>
    </Message>
  </div>
</template>
<style scoped>.tb-p { margin: 4px 0 8px; }</style>
