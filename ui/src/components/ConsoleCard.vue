<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import Button from 'primevue/button';
import { OuiPanel, OuiWidgetMaximize } from '@orca-plugins/ui-foundation/src/components';
import { terminal } from '@orca-plugins/ui-foundation/src/icons';
import { activity, printerName, targetKnown } from '../app/store';
import { t } from '../core/i18n';

// The Console widget: the page's log (store.activity) of commands sent, what came back and what the printer did. The
// log takes the widget's height, so a taller widget shows more lines; `lines` (its setting) is how many it shows.
const props = withDefaults(defineProps<{ config?: { lines?: number } }>(), { config: () => ({}) });
const lines = computed(() => activity.value.slice(-(props.config.lines ?? 400)));
const box = ref<HTMLElement | null>(null);
watch(() => lines.value.at(-1)?.id, () => nextTick(() => { if (box.value) box.value.scrollTop = box.value.scrollHeight; }));
</script>
<template>
  <OuiPanel :icon="terminal" aria-labelledby="console-h" :meta="targetKnown ? printerName : undefined" :hint="t('console.help')" :hint-label="t('console.title')" data-test="console">
    <template #title><span id="console-h">{{ t('console.title') }}</span></template>
    <template #actions>
      <Button severity="secondary" text size="small" :label="t('console.clear')" :disabled="!activity.length" data-test="console-clear" @click="activity = []" />
      <OuiWidgetMaximize />
    </template>
    <div ref="box" class="kc-log oui-well" role="log" aria-live="polite" :aria-label="t('console.log')" tabindex="0" data-test="console-log">
      <p v-if="!lines.length" class="oui-muted">{{ t('console.empty') }}</p>
      <div v-for="l in lines" :key="l.id" :class="['kc-log-line', l.kind]">{{ l.text }}</div>
    </div>
  </OuiPanel>
</template>
<style>
.kc-log { height: 100%; min-height: 96px; overflow: auto; padding: var(--oui-s2) var(--oui-s3); font-family: var(--oui-mono); font-size: var(--oui-text-sm); line-height: 1.5; box-shadow: inset 0 0 0 1px var(--oui-border); box-sizing: border-box; }
.oui-dash-grid[data-narrow] .kc-log { height: 240px; }
.kc-log-line { white-space: pre-wrap; overflow-wrap: anywhere; }
.kc-log-line.in { font-weight: 700; }
.kc-log-line.err { color: var(--oui-danger); }
</style>
