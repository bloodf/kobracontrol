<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import Icon from './Icon.vue';
import * as bridge from '../core/bridge';
import { s, lease, controlsOff, link, printerName } from '../app/store';
import { t } from '../core/i18n';

function toggle() {
  s.camOn = !s.camOn;
  if (!s.camOn) { s.frame = ''; s.camError = ''; s.camReason = ''; }
  lease();
}
// A plain explanation per reason: what happened and what to do about it.
const msg = computed(() => {
  if (!s.camError) return t('cam.starting');
  if (s.camReason === 'no_ffmpeg') return t('cam.reason.no_ffmpeg');
  if (s.camReason === 'no_stream') return t('cam.reason.no_stream');
  return t('cam.reason.failed', { error: s.camError });
});
</script>
<template>
  <!-- Off: a compact strip so status and controls stay above the fold. -->
  <section class="kc-card cam-card" :class="{ compact: !s.camOn }" aria-labelledby="cam-h">
    <div class="kc-row">
      <h2 id="cam-h" class="cam-h"><Icon name="icon/camera" /> {{ t('cam.title') }}</h2>
      <span v-if="!s.camOn" class="oui-meta">{{ t('cam.off') }} · {{ t('cam.offHint') }}</span>
      <span class="kc-spacer" />
      <Button :severity="s.camOn ? 'secondary' : undefined" :outlined="s.camOn" :disabled="link !== 'connected' && !s.camOn"
              data-focus-key="camera" data-test="camera" @click="toggle">
        <Icon name="icon/live-stream" /><span>{{ s.camOn ? t('cam.stop') : t('cam.start') }}</span></Button>
    </div>
    <!-- The same reason as every other control: the page shows one connection state. -->
    <p v-if="link !== 'connected' && !s.camOn" class="kc-why" data-test="cam-why">{{ controlsOff || t('reason.waiting') }}</p>
    <div v-if="s.camOn" class="cam-view">
      <img v-if="s.frame" :src="s.frame" :alt="t('cam.alt', { printer: printerName })" @load="bridge.post({ type: 'frame_ack' })">
      <div v-else class="cam-empty" role="status" :data-reason="s.camReason"><Icon :name="s.camError ? 'spot/camera-off' : 'spot/not-connected'" :size="96" /><span>{{ msg }}</span>
        <Button v-if="s.camReason === 'no_ffmpeg'" size="small" severity="secondary" :label="t('cam.ffmpegSettings')" data-test="cam-settings" @click="s.tab = 'settings'" /></div>
    </div>
  </section>
</template>
<style scoped>
.cam-h { margin: 0; display: flex; align-items: center; gap: 8px; }
.cam-card.compact { padding-block: 10px; }
.cam-view { margin-top: 12px; position: relative; background: #000; border-radius: 6px; aspect-ratio: 16 / 9; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.cam-view img { width: 100%; height: 100%; object-fit: contain; }
.cam-empty { display: grid; justify-items: center; gap: 8px; color: #d5dbe3; padding: 16px; text-align: center; }
</style>
