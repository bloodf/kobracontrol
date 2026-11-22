<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiFormRow, OuiFormSection, OuiIcon, OuiStatus } from '@orca-plugins/ui-foundation/src/components';
import { external, link as linkIcon, refresh, user } from '@orca-plugins/ui-foundation/src/icons';
import { run, tracker } from '../app/store';
import { config, form, save, saving } from '../app/settings';
import { t } from '../core/i18n';

// Anycubic Cloud (src/kobracontrol/cloud.py): off by default. The switch is saved like every other setting; the
// account (sign-in, printers) is only asked for once the plugin has it on. A pasted token is sent once and never kept.
interface CloudState { enabled: boolean; signed_in: boolean; email: string; slicer_log: boolean }
interface CloudPrinter { id: string; name: string; model: string; online: boolean; printing: boolean }

const saved = computed(() => config.value?.settings.cloud_enabled === true);
const state = ref<CloudState | null>(null);
const printers = ref<CloudPrinter[] | null>(null);
const token = ref('');
const on = computed(() => form.cloud && saved.value);
const chip = computed(() => (!saved.value ? 'idle' : state.value?.signed_in ? 'ok' : 'warn'));
const chipText = computed(() => t(!saved.value ? 'cloud.chip.off' : state.value?.signed_in ? 'cloud.chip.on' : 'cloud.chip.signedOut'));

async function loadPrinters(): Promise<void> {
  const r = await run({ key: 'cloud-printers', label: t('cloud.act.printers'), cmd: 'cloud_printers', timeoutMs: 30000 });
  if (r.ok) printers.value = Array.isArray(r.result) ? r.result : [];
}
async function loadState(): Promise<void> {
  const r = await run({ key: 'cloud-state', label: t('cloud.title'), cmd: 'cloud_state', quiet: true });
  if (!r.ok || !saved.value) return;
  state.value = r.result;
  if (r.result?.signed_in) void loadPrinters();
}
watch(saved, now => { state.value = null; printers.value = null; if (now) void loadState(); }, { immediate: true });

function signedIn(email: string): void {
  state.value = { ...(state.value as CloudState), signed_in: true, email };
  tracker.notify('success', t('cloud.signedInOk', { email }));
  void loadPrinters();
}
async function find(): Promise<void> {
  const r = await run({ key: 'cloud-sign-in', label: t('cloud.act.signIn'), cmd: 'cloud_find', timeoutMs: 60000 });
  if (r.ok) signedIn(r.result?.email ?? '');
}
async function signIn(): Promise<void> {
  const value = token.value.trim();
  token.value = '';   // never shown again, also when the sign-in fails
  if (!value) return;
  const r = await run({ key: 'cloud-sign-in', label: t('cloud.act.signIn'), cmd: 'cloud_sign_in', args: { token: value }, timeoutMs: 60000 });
  if (r.ok) signedIn(r.result?.email ?? '');
}
async function signOut(): Promise<void> {
  const r = await run({ key: 'cloud-sign-out', label: t('cloud.act.signOut'), cmd: 'cloud_sign_out', okText: t('cloud.signedOutOk') });
  if (!r.ok) return;
  state.value = { ...(state.value as CloudState), signed_in: false, email: '' };
  printers.value = null;
}
/** Choosing a printer (or going back to the LAN one) is saved at once. */
function choose(id: string): void {
  form.cloudPrinter = id;
  void save();
}
</script>

<template>
  <OuiFormSection id="cloud-h" :icon="external" tone="teal" :title="t('cloud.title')" :description="t('cloud.help')">
    <template #status><OuiStatus :state="chip" data-test="cloud-chip">{{ chipText }}</OuiStatus></template>
    <details class="kc-disclose cs-more" data-test="cloud-more">
      <summary>{{ t('cloud.more') }}</summary>
      <p class="oui-meta">{{ t('cloud.moreText') }}</p>
    </details>
    <OuiFormRow :label="t('cloud.enable')" for="c-cloud" :hint="t('cloud.enableHint')">
      <ToggleSwitch v-model="form.cloud" input-id="c-cloud" data-test="cloud-enable" />
    </OuiFormRow>
    <p v-if="form.cloud && !saved" class="oui-meta kc-pad" role="status" data-test="cloud-save-first">{{ t('cloud.saveFirst') }}</p>

    <template v-if="on">
      <OuiFormRow v-if="!state" :label="t('cloud.account')">
        <span class="oui-muted" role="status">{{ t('cloud.checking') }}</span>
      </OuiFormRow>
      <OuiFormRow v-else-if="state.signed_in" :label="t('cloud.account')">
        <span role="status" data-test="cloud-email">{{ t('cloud.signedIn', { email: state.email }) }}</span>
        <Button size="small" severity="secondary" :label="t('cloud.signOut')" :loading="tracker.isBusy('cloud-sign-out')" data-test="cloud-sign-out" @click="signOut" />
      </OuiFormRow>
      <OuiFormRow v-else :label="t('cloud.account')" stacked>
        <div class="oui-stack cs-grow" data-test="cloud-sign-in">
          <div>
            <Button :label="t('cloud.find')" :disabled="!state.slicer_log" :loading="tracker.isBusy('cloud-sign-in')" aria-describedby="c-cloud-find-hint"
                    data-test="cloud-find" @click="find"><template #icon><OuiIcon :icon="user" :size="14" /></template></Button>
            <p id="c-cloud-find-hint" class="oui-meta cs-hint">{{ state.slicer_log ? t('cloud.findHint') : t('cloud.noSlicer') }}</p>
          </div>
          <details class="kc-disclose" data-test="cloud-paste">
            <summary>{{ t('cloud.paste') }}</summary>
            <form class="cs-row" @submit.prevent="signIn">
              <InputText v-model="token" type="password" autocomplete="off" spellcheck="false" class="oui-mono cs-grow" :aria-label="t('cloud.token')"
                         aria-describedby="c-cloud-token-hint" data-test="cloud-token" />
              <Button type="submit" size="small" :label="t('cloud.signIn')" :disabled="!token.trim()" :loading="tracker.isBusy('cloud-sign-in')" data-test="cloud-token-sign-in" />
            </form>
            <p id="c-cloud-token-hint" class="oui-meta">{{ t('cloud.tokenHint') }}</p>
          </details>
        </div>
      </OuiFormRow>

      <OuiFormRow v-if="state?.signed_in" :label="t('cloud.printers')" stacked>
        <div class="oui-stack cs-grow">
          <div class="cs-row">
            <span class="oui-meta cs-grow" role="status">{{ printers === null ? t('cloud.loading') : !printers.length ? t('cloud.none') : '' }}</span>
            <Button size="small" severity="secondary" text :label="t('cloud.refresh')" :loading="tracker.isBusy('cloud-printers')" data-test="cloud-refresh" @click="loadPrinters">
              <template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
          </div>
          <div v-if="printers?.length" role="radiogroup" :aria-label="t('cloud.printers')" class="cs-list" data-test="cloud-printers">
            <label v-for="p in printers" :key="p.id" class="cs-printer" :data-printer="p.id">
              <input type="radio" name="cloud-printer" :value="p.id" :checked="form.cloudPrinter === p.id" :disabled="saving" @change="choose(p.id)">
              <span class="cs-grow"><strong>{{ p.name || p.id }}</strong><span class="oui-meta"> · {{ p.model }}</span></span>
              <OuiStatus :state="p.online ? 'ok' : 'offline'" variant="plain">{{ t(p.online ? 'cloud.online' : 'cloud.offline') }}</OuiStatus>
              <OuiStatus v-if="p.printing" state="busy" variant="plain">{{ t('cloud.printing') }}</OuiStatus>
            </label>
          </div>
          <p class="oui-meta">{{ t('cloud.note') }}</p>
          <div v-if="form.cloudPrinter">
            <Button size="small" severity="secondary" :label="t('cloud.useLan')" :disabled="saving" data-test="cloud-use-lan" @click="choose('')">
              <template #icon><OuiIcon :icon="linkIcon" :size="14" /></template></Button>
          </div>
        </div>
      </OuiFormRow>
    </template>
  </OuiFormSection>
</template>

<style>
.cs-more { padding: var(--oui-s2) var(--oui-s4) var(--oui-s3); }
.cs-grow { flex: 1 1 12rem; min-width: 0; }
.cs-row { display: flex; flex-wrap: wrap; gap: var(--oui-s2); align-items: center; }
.cs-hint { margin-top: var(--oui-s1); }
.cs-list { display: grid; border: 1px solid var(--oui-border); border-radius: var(--oui-radius); }
.cs-printer { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oui-s2) var(--oui-s3); padding: var(--oui-s2) var(--oui-s3); min-height: 44px; cursor: pointer; }
.cs-printer + .cs-printer { border-top: 1px solid var(--oui-border); }
.cs-printer input { accent-color: var(--oui-primary-mark); margin: 0; }
</style>
