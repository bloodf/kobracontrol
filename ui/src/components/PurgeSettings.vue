<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import InputNumber from 'primevue/inputnumber';
import Select from 'primevue/select';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiBanner, OuiFormRow, OuiFormSection, OuiStatus } from '../../shared/src/components';
import { flame } from '../../shared/src/icons';
import * as bridge from '../core/bridge';
import { message } from '../core/tracker';
import { acceptDot } from '../core/decimal-input';
import { config, form } from '../app/settings';
import { locale, t } from '../core/i18n';
import type { PurgePreview } from '../app/types';

// The purge-and-bed-wait add-on (src/kobracontrol/purge.py): off by default and untested on a printer, so the warning
// always shows. The preview is the plugin's own text for the values typed here, so it can't drift from what is sent.
const dot = computed(() => acceptDot(locale.value));
const corners = computed(() => [
  { value: 'front_left', label: t('purge.corner.front_left') }, { value: 'front_right', label: t('purge.corner.front_right') },
  { value: 'back_left', label: t('purge.corner.back_left') }, { value: 'back_right', label: t('purge.corner.back_right') }]);
const preview = ref<PurgePreview | null>(null);
const previewError = ref('');

async function load(): Promise<void> {
  try {
    preview.value = await bridge.request({ type: 'purge_preview', purge: { length: form.purgeLength, speed: form.purgeSpeed, corner: form.purgeCorner } });
    previewError.value = '';
  } catch (e) {
    previewError.value = message(e);
  }
}
watch(() => [config.value !== null, form.purgeLength, form.purgeSpeed, form.purgeCorner], () => { if (config.value) void load(); }, { immediate: true });
</script>

<template>
  <OuiFormSection id="purge-h" :icon="flame" tone="orange" :title="t('purge.title')" :description="t('purge.help')">
    <template #status><OuiStatus :state="form.purge ? 'warn' : 'idle'" data-test="purge-chip">{{ form.purge ? t('bridge.chip.on') : t('bridge.chip.off') }}</OuiStatus></template>
    <div class="kc-pad"><OuiBanner tone="warn" :title="t('purge.warnTitle')" data-test="purge-warning">{{ t('purge.warnBody') }}</OuiBanner></div>
    <OuiFormRow :label="t('purge.enable')" for="c-purge"><ToggleSwitch v-model="form.purge" input-id="c-purge" data-test="purge-enable" /></OuiFormRow>
    <OuiFormRow :label="t('purge.length')" for="c-purge-len">
      <InputNumber v-bind="dot" v-model="form.purgeLength" :locale="locale" input-id="c-purge-len" :min="1" :max="50" :max-fraction-digits="1" :use-grouping="false"
                   :allow-empty="false" size="small" data-test="purge-length" />
    </OuiFormRow>
    <OuiFormRow :label="t('purge.speed')" for="c-purge-speed">
      <InputNumber v-bind="dot" v-model="form.purgeSpeed" :locale="locale" input-id="c-purge-speed" :min="1" :max="10" :max-fraction-digits="1" :use-grouping="false"
                   :allow-empty="false" size="small" data-test="purge-speed" />
    </OuiFormRow>
    <OuiFormRow :label="t('purge.corner')" :hint="t('purge.cornerHint')">
      <Select v-model="form.purgeCorner" :options="corners" option-label="label" option-value="value" :aria-label="t('purge.corner')" data-test="purge-corner" />
    </OuiFormRow>
    <div class="kc-pad">
      <p class="oui-meta"><strong>{{ t('purge.preview') }}</strong></p>
      <p v-if="previewError" class="oui-meta" role="alert">{{ t('purge.previewFailed', { error: previewError }) }}</p>
      <template v-else-if="preview">
        <p class="oui-meta">{{ t('purge.previewBed') }}</p>
        <pre class="oui-mono ps-pre" data-test="purge-preview-bed">{{ preview.bed_wait.join('\n') }}</pre>
        <p class="oui-meta">{{ t('purge.previewTool') }}</p>
        <pre class="oui-mono ps-pre" data-test="purge-preview">{{ preview.purge.join('\n') }}</pre>
      </template>
    </div>
  </OuiFormSection>
</template>

<style>
.ps-pre { margin: var(--oui-s1) 0 var(--oui-s2); padding: var(--oui-s2) var(--oui-s3); overflow-x: auto; white-space: pre;
  background: var(--oui-inset); border-radius: var(--oui-radius-sm); font-size: 12px; }
</style>
