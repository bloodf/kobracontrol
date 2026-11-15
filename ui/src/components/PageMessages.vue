<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import { OuiBanner, OuiIcon } from '../../shared/src/components';
import { dashboard, refresh, settings, shieldCheck, x } from '../../shared/src/icons';
import { s, tracker, hello, link, printerName, statusAge, STALE_STATUS_S } from '../app/store';
import { t, fmt } from '../core/i18n';

// What the whole page has to say, once, under the app bar on every tab: why the printer's controls are off and what
// each command answered. Controls that are off for one of these reasons point at it (#kc-why) instead of repeating it.
// No certificate / no printer: the Dashboard shows the one task itself; the other tabs say what is missing here.
const retryIn = computed(() => (s.retryAt ? Math.max(0, Math.ceil(s.retryAt - s.now / 1000)) : 0));
const TONE = { error: 'error', unknown: 'warn', success: 'success', info: 'info' } as const;
const lasting = computed(() => tracker.notices.filter(n => n.kind === 'error' || n.kind === 'unknown'));
const passing = computed(() => tracker.notices.filter(n => n.kind === 'success' || n.kind === 'info'));
const waiting = computed(() => [...tracker.pending.values()].filter(p => p.key !== 'spools'));
/** "Pause failed: timeout" reads as a title and its detail. */
const split = (text: string) => { const i = text.indexOf(': '); return i < 0 ? [text, ''] : [text.slice(0, i + 1), text.slice(i + 2)]; };
</script>

<template>
  <div class="kc-top">
    <div class="kc-live" role="status" aria-live="polite" data-test="target-banner">

      <OuiBanner v-if="link === 'noCertificate' && s.tab !== 'dash'" id="kc-why" tone="warn" :title="t('fr.cert.title')">
        {{ t('banner.cert') }}
        <template #actions><Button size="small" severity="secondary" :label="t('banner.toDashboard')" @click="s.tab = 'dash'"><template #icon><OuiIcon :icon="dashboard" :size="14" /></template></Button></template>
      </OuiBanner>

      <OuiBanner v-else-if="link === 'noTarget' && s.tab !== 'dash'" id="kc-why" tone="warn" :title="t('fr.target.title')">
        {{ t('banner.target') }}
        <template v-if="s.tab !== 'settings'" #actions>
          <Button size="small" severity="secondary" :label="t('common.openSettings')" @click="s.tab = 'settings'"><template #icon><OuiIcon :icon="settings" :size="14" /></template></Button>
        </template>
      </OuiBanner>

      <OuiBanner v-else-if="link === 'offline'" id="kc-why" tone="error" :title="t('target.offline.title')">
        {{ t('target.offline.body', { printer: printerName, error: s.offline || s.error }) }}
        <span v-if="retryIn" class="oui-meta" data-test="retry-in">{{ t('target.retryIn', { n: retryIn }) }}</span>
        <template #actions>
          <Button v-if="s.tab !== 'settings'" size="small" severity="secondary" text :label="t('banner.connSettings')" @click="s.tab = 'settings'" />
          <Button size="small" severity="secondary" :label="t('common.retry')" @click="hello(true)"><template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
        </template>
      </OuiBanner>

      <OuiBanner v-else-if="link === 'connecting'" id="kc-why" tone="neutral" :title="t('target.connecting')" />

      <OuiBanner v-else-if="link === 'connected' && !s.status?.connected" id="kc-why" tone="neutral" :title="t('reason.waiting') + '.'" />

      <OuiBanner v-else-if="s.status && statusAge > STALE_STATUS_S" tone="warn" :title="t('target.stale', { age: fmt.ago(s.statusAt / 1000, s.now / 1000) })" />

      <!-- Not part of the chain above: a changed printer certificate is shown on every tab while it lasts. -->
      <OuiBanner v-if="s.status?.tls?.changed_from" tone="warn" :icon="shieldCheck" :title="t('tls.changed.title')" data-test="tls-changed">
        {{ t('tls.changed.body', { printer: printerName }) }}
      </OuiBanner>

    </div>

    <section class="notices" :aria-label="t('msg.region')">
      <!-- Errors and unknown outcomes stay until dismissed and are announced at once. -->
      <div role="alert" class="kc-live">
        <OuiBanner v-for="n in lasting" :key="n.id" :tone="TONE[n.kind]" :title="split(n.text)[0]">
          {{ split(n.text)[1] }} <span class="oui-meta">{{ fmt.time(n.at / 1000) }}</span>
          <template #actions><Button text severity="secondary" size="small" :label="t('common.dismiss')" @click="tracker.dismiss(n.id)"><template #icon><OuiIcon :icon="x" :size="14" /></template></Button></template>
        </OuiBanner>
      </div>
      <div role="status" aria-live="polite" class="kc-live">
        <OuiBanner v-for="p in waiting" :key="'p-' + p.key" tone="neutral" :title="split(t('msg.waiting', { action: p.label }))[0]">{{ split(t('msg.waiting', { action: p.label }))[1] }}</OuiBanner>
        <OuiBanner v-for="n in passing" :key="n.id" :tone="TONE[n.kind]" :title="split(n.text)[0]">
          {{ split(n.text)[1] }}
          <template #actions><Button text severity="secondary" size="small" :label="t('common.dismiss')" @click="tracker.dismiss(n.id)"><template #icon><OuiIcon :icon="x" :size="14" /></template></Button></template>
        </OuiBanner>
      </div>
    </section>
  </div>
</template>
