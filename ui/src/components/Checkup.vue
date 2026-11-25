<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import { OuiIcon, OuiStatus, type OuiState } from '@orca-plugins/ui-foundation/src/components';
import { refresh, shieldCheck } from '@orca-plugins/ui-foundation/src/icons';
import { run, tracker, checkRequirements, openSettings } from '../app/store';
import * as bridge from '../core/bridge';
import type { MessageKey } from '../core/messages';
import { t } from '../core/i18n';

// Settings > Requirements > Check everything: one read-only pass over every connection and permission Kobra Control
// depends on (src/kobracontrol/checkup.py): the printer over the LAN, its login, the certificate, OrcaSlicer's printer
// agents, Spoolman and Anycubic Cloud. Pass, fail or not configured; each failure says what to do, and where
// OrcaSlicer can ask for a missing permission, Allow shows its dialog now.
export interface Check { id: string; state: 'pass' | 'fail' | 'off'; reason: string; detail: string; action: '' | 'allow_printer' | 'allow_spoolman' }
const results = ref<Check[] | null>(null);
const error = ref('');
const allowing = ref('');
const STATE: Record<Check['state'], OuiState> = { pass: 'ok', fail: 'error', off: 'idle' };
// Where a fix sends the user: the Settings page that changes it.
const PAGE: Record<string, string> = { printer: 'conn-h', login: 'cert-h', certificate: 'cert-h', spoolman: 'sm-s-h', cloud: 'cloud-h' };

async function checkAll(): Promise<void> {
  error.value = '';
  checkRequirements();   // first: the plugin notes whether OrcaSlicer runs its printer agent, the check reads it
  const r = await run({ key: 'checkup', label: t('check.run'), cmd: 'checkup', timeoutMs: 90_000, quiet: true });
  if (r.ok) results.value = Array.isArray(r.result) ? r.result as Check[] : [];
  else if (r.reason === 'error') error.value = r.error ?? '';
}
async function allow(c: Check): Promise<void> {
  allowing.value = c.id;
  try {
    const r = await bridge.request({ type: 'allow_now', what: c.action === 'allow_printer' ? 'printer' : 'spoolman' });
    if (r?.allowed) await checkAll();
    else tracker.notify('error', t('check.notAllowed'));
  } catch (e) {
    tracker.notify('error', t('msg.plugin', { error: String((e as Error)?.message ?? e) }));
  } finally {
    allowing.value = '';
  }
}
const key = (k: string) => k as MessageKey;
// Product names are the same in every language.
const PRODUCT: Record<string, string> = { spoolman: 'Spoolman', cloud: 'Anycubic Cloud' };
const name = (c: Check) => PRODUCT[c.id] ?? t(key(`check.name.${c.id}`));
const fix = (c: Check) => (c.state === 'pass' ? '' : t(key(`check.fix.${c.id}.${c.reason || 'error'}`)));
const detail = (c: Check) => (c.id === 'cloud' && c.state === 'pass' ? t('check.cloudPrinters', { n: c.detail }) : c.detail);
const failed = computed(() => results.value?.filter(c => c.state === 'fail').length ?? 0);
</script>

<template>
  <div class="ck" data-test="checkup">
    <div class="ck-head">
      <p class="oui-meta">{{ t('check.help') }}</p>
      <Button size="small" :label="t('check.run')" :loading="tracker.isBusy('checkup')" data-test="check-all" @click="checkAll">
        <template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
    </div>
    <p v-if="error" class="oui-meta ck-error" role="alert">{{ t('check.failed', { error }) }}</p>
    <!-- always there, filled when a check is in: a live region added already filled is often not read out -->
    <p class="ck-sum" role="status" data-test="check-summary">{{ !results ? '' : failed ? t('check.someFail', { n: failed }) : t('check.allPass') }}</p>
    <ul v-if="results" class="ck-list">
      <li v-for="c in results" :key="c.id" class="ck-row" :data-check="c.id" :data-state="c.state">
        <OuiStatus :state="STATE[c.state]" variant="plain">{{ t(key(`check.state.${c.state}`)) }}</OuiStatus>
        <div class="ck-body">
          <strong>{{ name(c) }}</strong>
          <span v-if="detail(c)" class="oui-meta ck-detail"> · {{ detail(c) }}</span>
          <p v-if="fix(c)" class="ck-fix" data-test="check-fix">{{ fix(c) }}</p>
        </div>
        <div class="ck-actions">
          <Button v-if="c.action" size="small" :label="t('check.allow')" :loading="allowing === c.id" data-test="check-allow" @click="allow(c)">
            <template #icon><OuiIcon :icon="shieldCheck" :size="14" /></template></Button>
          <Button v-else-if="c.state === 'fail' && PAGE[c.id]" size="small" severity="secondary" text :label="t('common.openSettings')"
                  data-test="check-open" @click="openSettings(PAGE[c.id])" />
        </div>
      </li>
    </ul>
  </div>
</template>

<style>
.ck { padding: var(--oui-s3) var(--oui-s4); border-bottom: 1px solid var(--oui-border); }
.ck-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oui-s2) var(--oui-s3); }
.ck-head > p { flex: 1 1 220px; margin: 0; }
.ck-sum { margin: var(--oui-s3) 0 var(--oui-s1); font-weight: 600; }
.ck-sum:empty { display: none; }
.ck-error { color: var(--oui-danger, inherit); }
.ck-list { list-style: none; margin: 0; padding: 0; }
.ck-row { display: grid; grid-template-columns: 9.5em minmax(0, 1fr) auto; align-items: start; gap: var(--oui-s2) var(--oui-s3); padding: var(--oui-s2) 0; }
.ck-row + .ck-row { border-top: 1px solid var(--oui-border); }
.ck-detail { overflow-wrap: anywhere; }
.ck-fix { margin: 2px 0 0; }
@media (max-width: 560px) { .ck-row { grid-template-columns: minmax(0, 1fr) auto; } .ck-row > .oui-status { grid-column: 1 / -1; } }
</style>
