<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import Icon from './Icon.vue';
import * as bridge from '../core/bridge';
import { config } from '../app/settings';
import { stockVisible } from '../app/store';
import { t } from '../core/i18n';

const props = defineProps<{ where: 'dash' | 'settings' }>();
const sp = computed(() => config.value?.spooler ?? null);
const show = computed(() => !!sp.value && (props.where === 'settings' || (!sp.value.installed && !sp.value.dismissed)));
const dismiss = () => bridge.post({ type: 'save_settings', settings: { spooler_hint_dismissed: true } });
</script>
<template>
  <section v-if="show && sp" class="kc-card" :aria-labelledby="`sph-${where}`">
    <h2 :id="`sph-${where}`"><Icon name="icon/spoolman" /> {{ t('spooler.title') }}</h2>
    <template v-if="sp.installed">
      <p>{{ t('spooler.installed') }}</p>
      <p v-if="where === 'settings' && !stockVisible" class="kc-why" data-test="spooler-no-stock">{{ t('spooler.noStock') }}</p>
    </template>
    <div v-else class="sph"><Icon name="spot/spooler-suggestion" :size="96" />
      <p>{{ t('spooler.suggest') }} <a :href="sp.url">{{ sp.url }}</a></p></div>
    <Button v-if="!sp.installed && !sp.dismissed" severity="secondary" outlined :label="t('spooler.dismiss')" @click="dismiss" />
  </section>
</template>
<style scoped>.sph { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; } .sph p { margin: 0; flex: 1 1 240px; }</style>
