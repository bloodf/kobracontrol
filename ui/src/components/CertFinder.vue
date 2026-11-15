<script setup lang="ts">
import { ref } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Icon from './Icon.vue';
import { s, run, hello, tracker } from '../app/store';
import { t } from '../core/i18n';

// "Find certificate": the plugin reads the Anycubic Slicer Next installation (or the file/folder given here);
// afterwards the connection is tried again.
const props = defineProps<{ idPrefix: string }>();
const path = ref('');
const notFound = ref(false);

async function find() {
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
  <div class="cf">
    <div class="kc-row">
      <label :for="`${props.idPrefix}-cert-path`">{{ t('cert.path') }}</label>
      <InputText :id="`${props.idPrefix}-cert-path`" v-model="path" :placeholder="t('cert.pathPh')" class="cf-path" :aria-describedby="`${props.idPrefix}-cert-why`" @keydown.enter="find" />
      <Button :loading="tracker.isBusy('cert')" :data-focus-key="`${props.idPrefix}-cert`" data-test="find-cert" @click="find">
        <Icon name="icon/certificate" /><span>{{ t('cert.find') }}</span></Button>
    </div>
    <p :id="`${props.idPrefix}-cert-why`" class="kc-why" :class="{ 'kc-err': notFound }" role="status">{{ notFound ? t('cert.notFound') : t('cert.pathHelp') }}</p>
  </div>
</template>

<style scoped>
.cf { display: grid; gap: 4px; }
.cf-path { flex: 1 1 260px; min-width: 0; }
</style>
