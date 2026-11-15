<script setup lang="ts">
import Message from 'primevue/message';
import Button from 'primevue/button';
import { s, hello, printerName, statusAge, STALE_STATUS_S } from '../app/store';
import { t, fmt } from '../core/i18n';
</script>
<template>
  <div role="status" aria-live="polite" data-test="target-banner">
    <!-- No certificate / no printer: the Dashboard shows the one task; the other tabs say what is missing. -->
    <Message v-if="s.phase === 'noCertificate' && s.tab !== 'dash'" severity="warn">
      <strong>{{ t('fr.cert.title') }}</strong>
      <p class="tb-p">{{ t('banner.cert') }}</p>
      <Button size="small" :label="t('banner.toDashboard')" @click="s.tab = 'dash'" />
    </Message>
    <Message v-else-if="s.phase === 'noTarget' && s.tab !== 'dash'" severity="warn">
      <strong>{{ t('fr.target.title') }}</strong>
      <p class="tb-p">{{ t('banner.target') }}</p>
      <Button v-if="s.tab !== 'settings'" size="small" :label="t('common.openSettings')" @click="s.tab = 'settings'" />
    </Message>
    <Message v-else-if="s.phase === 'unreachable' || s.offline" severity="error">
      <strong>{{ t('target.offline.title') }}</strong>
      <p class="tb-p">{{ t('target.offline.body', { printer: printerName, error: s.offline || s.error }) }}</p>
      <Button size="small" severity="secondary" outlined :label="t('common.retry')" @click="hello()" />
    </Message>
    <Message v-else-if="s.phase === 'connecting'" severity="secondary">{{ t('target.connecting') }}</Message>
    <Message v-else-if="s.status && statusAge > STALE_STATUS_S" severity="warn">{{ t('target.stale', { age: fmt.ago(s.statusAt / 1000, s.now / 1000) }) }}</Message>
    <!-- Not part of the chain above: a changed printer certificate is shown on every tab while it lasts. -->
    <Message v-if="s.status?.tls?.changed_from" severity="warn" data-test="tls-changed">
      <strong>{{ t('tls.changed.title') }}</strong>
      <p class="tb-p">{{ t('tls.changed.body', { printer: printerName }) }}</p>
    </Message>
  </div>
</template>
<style scoped>.tb-p { margin: 4px 0 8px; }</style>
