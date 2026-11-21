<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import InputNumber from 'primevue/inputnumber';
import InputText from 'primevue/inputtext';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiFormRow, OuiFormSection, OuiIcon, OuiStatus } from '@orca-plugins/ui-foundation/src/components';
import { copy, refresh, upload } from '@orca-plugins/ui-foundation/src/icons';
import * as bridge from '../core/bridge';
import { message } from '../core/tracker';
import { tracker } from '../app/store';
import { config, form } from '../app/settings';
import { t } from '../core/i18n';

// The upload bridge (src/kobracontrol/bridge.py): off by default; its key lives in the plugin, never in the form.
const state = computed(() => config.value?.bridge ?? null);
const address = computed(() => `${state.value?.host || '127.0.0.1'}:${form.bridgePort}`);
const chip = computed(() => (!state.value?.enabled ? 'off' : state.value.running ? 'on' : 'error'));
const keyInput = ref<{ $el: HTMLInputElement } | null>(null);
const addressInput = ref<{ $el: HTMLInputElement } | null>(null);
const renewing = ref(false);

/** Copies text; OrcaSlicer's web view may refuse the clipboard API, then the selected field still copies. */
async function copyField(text: string, field: { $el: HTMLInputElement } | null, done: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const input = field?.$el;
    input?.select();
    if (!input || !document.execCommand('copy')) { tracker.notify('error', t('bridge.copyFailed')); return; }
  }
  tracker.notify('success', done);
}
const copyKey = () => copyField(state.value?.key || '', keyInput.value, t('bridge.copied'));
const copyAddress = () => copyField(address.value, addressInput.value, t('bridge.addressCopied'));

async function newKey(): Promise<void> {
  renewing.value = true;
  try {
    await bridge.request({ type: 'bridge_new_key' });
    tracker.notify('success', t('bridge.newKeyDone'));
  } catch (e) {
    tracker.notify('error', t('bridge.newKeyFailed', { error: message(e) }));
  } finally {
    renewing.value = false;
  }
}
</script>

<template>
  <OuiFormSection id="bridge-h" :icon="upload" tone="cobalt" :title="t('bridge.title')" :description="t('bridge.help')">
    <template #status>
      <OuiStatus :state="chip === 'on' ? 'ok' : chip === 'error' ? 'warn' : 'idle'" data-test="bridge-chip">
        {{ chip === 'on' ? t('bridge.chip.on') : chip === 'error' ? t('bridge.chip.error') : t('bridge.chip.off') }}</OuiStatus>
    </template>
    <OuiFormRow :label="t('bridge.enable')" for="c-bridge" :hint="t('bridge.enableHint')">
      <ToggleSwitch v-model="form.bridge" input-id="c-bridge" data-test="bridge-enable" />
    </OuiFormRow>
    <OuiFormRow :label="t('bridge.port')" for="c-bridge-port" :hint="t('bridge.portHint')">
      <InputNumber v-model="form.bridgePort" input-id="c-bridge-port" :min="1024" :max="65535" :use-grouping="false" :allow-empty="false" size="small" data-test="bridge-port" />
    </OuiFormRow>
    <OuiFormRow :label="t('bridge.state')">
      <span role="status" data-test="bridge-state">{{ !state?.enabled ? t('bridge.off') : state.running ? t('bridge.running', { address: `${state.host}:${state.port}` })
        : t('bridge.error', { error: state.error }) }}</span>
    </OuiFormRow>
    <OuiFormRow :label="t('bridge.address')" for="c-bridge-address" stacked>
      <div class="bs-key">
        <InputText id="c-bridge-address" ref="addressInput" :model-value="address" readonly class="oui-mono" data-test="bridge-address" />
        <Button size="small" severity="secondary" :label="t('bridge.copy')" :aria-label="`${t('bridge.copy')}: ${t('bridge.address')}`" data-test="bridge-copy-address" @click="copyAddress">
          <template #icon><OuiIcon :icon="copy" :size="14" /></template></Button>
      </div>
    </OuiFormRow>
    <OuiFormRow :label="t('bridge.key')" for="c-bridge-key" stacked>
      <div class="bs-key">
        <InputText id="c-bridge-key" ref="keyInput" :model-value="state?.key || ''" readonly class="oui-mono" data-test="bridge-key" />
        <Button size="small" severity="secondary" :label="t('bridge.copy')" :disabled="!state?.key" data-test="bridge-copy" @click="copyKey">
          <template #icon><OuiIcon :icon="copy" :size="14" /></template></Button>
        <Button size="small" severity="secondary" text :label="t('bridge.newKey')" :loading="renewing" data-test="bridge-new-key" @click="newKey">
          <template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
      </div>
    </OuiFormRow>
    <div class="kc-pad">
      <p class="oui-meta"><strong>{{ t('bridge.steps') }}</strong></p>
      <ol class="oui-meta bs-steps" data-test="bridge-steps">
        <li>{{ t('bridge.step1') }}</li>
        <li>{{ t('bridge.step2', { address }) }}</li>
        <li>{{ t('bridge.step3') }}</li>
        <li>{{ t('bridge.step4') }}</li>
      </ol>
    </div>
  </OuiFormSection>
</template>

<style>
.bs-key { display: flex; flex-wrap: wrap; gap: var(--oui-s2); align-items: center; }
.bs-key .p-inputtext { flex: 1 1 16rem; min-width: 0; }
.bs-steps { margin: var(--oui-s1) 0 0; padding-inline-start: 1.25rem; }
.bs-steps li + li { margin-top: 2px; }
</style>
