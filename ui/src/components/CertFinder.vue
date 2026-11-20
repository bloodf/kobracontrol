<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import { OuiFormRow, OuiIcon } from '@orca-plugins/ui-foundation/src/components';
import { search } from '@orca-plugins/ui-foundation/src/icons';
import { run, hello, tracker, noSlicer } from '../app/store';
import { t } from '../core/i18n';

// "Find certificate": the plugin reads the Anycubic Slicer Next installation (or the file/folder given here);
// afterwards the connection is tried again.
const props = defineProps<{ idPrefix: string }>();
const path = ref('');
const notFound = ref(false);
// Not installed where it usually is: the search needs a path typed in (the bundled certificate still works).
const blocked = computed(() => noSlicer.value && !path.value.trim());

async function find() {
  if (blocked.value) return;
  notFound.value = false;
  const arg = path.value.trim();
  const r = await run({ key: 'cert', label: t('act.findCert'), cmd: 'find_certificate', args: arg ? { path: arg } : {}, timeoutMs: 120000 });
  if (!r.ok) return;
  if (r.result?.found === false) { notFound.value = true; return; }
  tracker.notify('success', t('ok.cert', { source: r.result?.source ?? '' }));
  void hello(true);   // connect with the new certificate now, not after the retry delay
}
</script>

<template>
  <OuiFormRow :label="t('cert.path')" :for="`${props.idPrefix}-cert-path`" stacked>
    <div class="oui-row cf-row">
      <InputText :id="`${props.idPrefix}-cert-path`" v-model="path" :placeholder="t('cert.pathPh')" class="cf-path oui-mono" :aria-describedby="`${props.idPrefix}-cert-why`" @keydown.enter="find" />
      <Button :label="t('cert.find')" :loading="tracker.isBusy('cert')" :disabled="blocked" :data-focus-key="`${props.idPrefix}-cert`" data-test="find-cert" @click="find">
        <template #icon><OuiIcon :icon="search" :size="14" /></template></Button>
    </div>
    <p :id="`${props.idPrefix}-cert-why`" class="oui-meta" :class="{ 'cf-err': notFound }" role="status">{{ notFound ? t('cert.notFound') : blocked ? t('cert.noSlicer') : t('cert.pathHelp') }}</p>
  </OuiFormRow>
</template>

<style>
.cf-row { flex: 1 1 100%; flex-wrap: nowrap; }
.cf-row > .p-button { flex: none; }
.cf-path { flex: 1 1 260px; min-width: 0; }
.cf-err { color: var(--oui-danger); }
</style>
