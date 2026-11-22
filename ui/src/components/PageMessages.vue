<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import { OuiBanner, OuiIcon } from '@orca-plugins/ui-foundation/src/components';
import { dashboard, refresh, settings, play, shieldCheck, upload } from '@orca-plugins/ui-foundation/src/icons';
import { s, openSettings, tracker, hello, link, printerName, run, statusAge, busy, STALE_STATUS_S } from '../app/store';
import { t, fmt } from '../core/i18n';

// What the whole page has to say, once, under the page header of the open tab: why the printer's controls are off and
// which commands are still waiting for the printer (what they answered is a toast). Controls that are off for one of
// these reasons point at it (#kc-why, or #kc-busy for what a connected printer refuses while it works) instead of
// repeating it. No certificate / no printer: the Dashboard shows the one task
// itself; the other tabs say what is missing here. Every banner can be closed; its key names the condition, so it
// stays closed while that lasts and comes back when it changes (another address, another error, another command).
const retryIn = computed(() => (s.retryAt ? Math.max(0, Math.ceil(s.retryAt - s.now / 1000)) : 0));
const where = computed(() => s.info?.address ?? '');
const waiting = computed(() => [...tracker.pending.values()].filter(p => p.key !== 'spools'));
/** "Pause failed: timeout" reads as a title and its detail. */
// An Upload and Print from OrcaSlicer (upload bridge) never starts by itself: it waits here for Start.
const waitingPrint = computed(() => s.status?.bridge_pending ?? null);
function startWaiting(): void {
  const id = waitingPrint.value?.id;
  if (id) void run({ key: 'bridge-start', label: t('bridge.start'), cmd: 'bridge_start', args: { id }, okText: t('ok.print'), timeoutMs: 60000 });
}
function cancelWaiting(): void {
  const id = waitingPrint.value?.id;
  if (id) void run({ key: 'bridge-cancel', label: t('act.bridgeCancel'), cmd: 'bridge_cancel', args: { id }, okText: t('ok.bridgeCancel') });
}
// What a connected printer refuses while it works, for the tab that is open: the dashboard's controls, or starting a
// print on Files. One sentence each, in one banner. It is not one of the chained link banners below: its reasons are
// empty whenever one of those says more (offline, connecting, no status), and an old status must not hide it, as the
// controls it turns off point at it.
const busyWhy = computed(() => {
  const b = busy.value, st = s.status;
  const list = s.tab === 'dash' ? [b.feed && t('reason.noFeed'), b.move && t('reason.noMove'), b.heat && t('reason.noHeat'), b.print && t('reason.noDeviceChange'),
    st?.state === 'printing' && st.preparing && !st.can.pause && fmt.pair(t('act.pause'), t('reason.preparing'))]
    : s.tab === 'files' ? [b.print && t('reason.noPrintNow')] : [];
  return list.filter((x): x is string => !!x);
});
/** Which of the chained link banners applies (one at a time). Each banner is bound to its own case with `show`, so closing
 * one holds while that case lasts and is forgotten when it clears: the same problem coming back later shows again. */
const top = computed(() => (link.value === 'noCertificate' ? 'cert' : link.value === 'noTarget' ? 'target' : link.value === 'offline' ? 'offline'
  : link.value === 'connecting' ? 'connecting' : link.value === 'connected' && !s.status?.connected ? 'noStatus'
  : s.status && statusAge.value > STALE_STATUS_S ? 'stale' : ''));
const model = computed(() => { const p = s.status?.connected ? s.status.profile : undefined; return p && (!p.known || !p.verified) ? p : null; });
const split = (text: string) => { const i = text.indexOf(': '); return i < 0 ? [text, ''] : [text.slice(0, i + 1), text.slice(i + 2)]; };
</script>

<template>
  <div class="kc-top">
    <div class="kc-live" role="status" aria-live="polite" data-test="target-banner">

      <OuiBanner :show="busyWhy.length > 0" id="kc-busy" tone="info" :title="t(s.status?.state === 'printing' ? 'busy.printing' : 'busy.other')" data-test="busy-banner"
                 dismissible :dismiss-key="`busy:${where}:${s.tab}:${busyWhy.join('|')}`" :close-label="t('common.close')">
        {{ busyWhy.map(text => t('fmt.sentence', { text })).join(' ') }}
      </OuiBanner>

      <!-- A model never tried with Kobra Control (experimental), or one it has no profile for (read-only). -->
      <OuiBanner :show="!!model" :tone="model?.known ? 'info' : 'warn'" data-test="model-banner"
                 :title="t(model?.known ? 'model.experimental.title' : 'model.unknown.title', { name: model?.name || '' })"
                 dismissible :dismiss-key="`model:${model?.mode_id}:${model?.known}`" :close-label="t('common.close')">
        {{ t(model?.known ? 'model.experimental.body' : 'model.unknown.body', { name: model?.name || '', code: model?.mode_id || '' }) }}
      </OuiBanner>

      <!-- The Dashboard shows these tasks itself; hidden there, not cleared, so a closed one stays closed. -->
      <div v-show="s.tab !== 'dash'" style="display: contents">
      <OuiBanner :show="top === 'cert'" id="kc-why" tone="warn" :title="t('fr.cert.title')"
                 dismissible dismiss-key="no-certificate" :close-label="t('common.close')">
        {{ t('banner.cert') }}
        <template #actions><Button size="small" severity="secondary" :label="t('banner.toDashboard')" @click="s.tab = 'dash'"><template #icon><OuiIcon :icon="dashboard" :size="14" /></template></Button></template>
      </OuiBanner>

      <OuiBanner :show="top === 'target'" id="kc-why" tone="warn" :title="t('fr.target.title')"
                 dismissible dismiss-key="no-target" :close-label="t('common.close')">
        {{ t('banner.target') }}
        <template v-if="s.tab !== 'settings'" #actions>
          <Button size="small" severity="secondary" :label="t('common.openSettings')" @click="openSettings('conn-h')"><template #icon><OuiIcon :icon="settings" :size="14" /></template></Button>
        </template>
      </OuiBanner>
      </div>

      <OuiBanner :show="top === 'offline'" id="kc-why" tone="error" :title="t('target.offline.title')"
                 dismissible :dismiss-key="`offline:${where}:${s.offline || s.error}`" :close-label="t('common.close')">
        {{ t('target.offline.body', { printer: printerName, error: s.offline || s.error }) }}
        <span v-if="retryIn" class="oui-meta" data-test="retry-in">{{ t('target.retryIn', { n: retryIn }) }}</span>
        <template #actions>
          <Button v-if="s.tab !== 'settings'" size="small" severity="secondary" text :label="t('banner.connSettings')" @click="openSettings('conn-h')" />
          <Button size="small" severity="secondary" :label="t('common.retry')" @click="hello(true)"><template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
        </template>
      </OuiBanner>

      <OuiBanner :show="top === 'connecting'" id="kc-why" tone="neutral" :title="t('target.connecting')"
                 dismissible :dismiss-key="`connecting:${where}`" :close-label="t('common.close')" />

      <OuiBanner :show="top === 'noStatus'" id="kc-why" tone="neutral" :title="t('reason.waiting') + '.'"
                 dismissible :dismiss-key="`no-status:${where}`" :close-label="t('common.close')" />

      <!-- Keyed on the printer, not the status time: closed, it stays closed while the status stays stale. -->
      <OuiBanner :show="top === 'stale'" tone="warn" :title="top === 'stale' ? t('target.stale', { age: fmt.ago(s.statusAt / 1000, s.now / 1000) }) : ''"
                 dismissible :dismiss-key="`stale:${where}`" :close-label="t('common.close')" />

      <OuiBanner v-if="waitingPrint" tone="info" :icon="upload" :title="t('bridge.pending.title')" data-test="bridge-pending">
        {{ t('bridge.pending.body', { name: waitingPrint.name }) }}
        <span v-if="!s.status?.can.print" id="kc-bridge-why" class="oui-meta">{{ t('bridge.pending.notIdle') }}</span>
        <template #actions>
          <Button size="small" severity="secondary" text :label="t('bridge.dontPrint')" :loading="tracker.isBusy('bridge-cancel')" data-test="bridge-cancel" @click="cancelWaiting" />
          <Button size="small" :label="t('bridge.start')" :disabled="!s.status?.can.print" :aria-describedby="s.status?.can.print ? undefined : 'kc-bridge-why'"
                  :loading="tracker.isBusy('bridge-start')" data-test="bridge-start" @click="startWaiting"><template #icon><OuiIcon :icon="play" :size="14" /></template></Button>
        </template>
      </OuiBanner>

      <!-- Not part of the chain above: a changed printer certificate is shown on every tab until closed. -->
      <OuiBanner :show="!!s.status?.tls?.changed_from" tone="warn" :icon="shieldCheck" :title="t('tls.changed.title')" data-test="tls-changed"
                 dismissible :dismiss-key="`tls-changed:${s.status?.tls?.fingerprint}`" :close-label="t('common.close')">
        {{ t('tls.changed.body', { printer: printerName }) }}
      </OuiBanner>

    </div>

    <section class="notices" :aria-label="t('msg.region')">
      <div role="status" aria-live="polite" class="kc-live">
        <OuiBanner v-for="p in waiting" :key="'p-' + p.key" tone="neutral" :title="split(t('msg.waiting', { action: p.label }))[0]"
                   dismissible :dismiss-key="`waiting:${p.key}:${p.startedAt}`" :close-label="t('common.close')">{{ split(t('msg.waiting', { action: p.label }))[1] }}</OuiBanner>
      </div>
    </section>
  </div>
</template>
