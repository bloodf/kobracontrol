<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import Button from 'primevue/button';
import { OuiEmpty, OuiIcon, OuiPanel } from '../../shared/src/components';
import { camera, cameraOff, settings } from '../../shared/src/icons';
import * as bridge from '../core/bridge';
import { s, lease, controlsOff, link, printerName, noFfmpeg, requirement } from '../app/store';
import { t } from '../core/i18n';
import { Player } from '../core/player';

// The stream from the plugin's Relay, played here; ffmpeg's JPEG frames (the fallback) still come as `frame`.
const vid = ref<HTMLVideoElement | null>(null);
let player: Player | null = null;
watch(vid, el => { player?.close(); player = el ? new Player(el) : null; });
let unlisten = () => {};
onMounted(() => { unlisten = bridge.onMessage(m => {
  if (m?.type !== 'video' || !player) return;
  if (typeof m.init === 'string') player.init(String(m.codec), m.init);
  else if (typeof m.data === 'string') player.append(m.data);
}); });
onBeforeUnmount(() => { unlisten(); player?.close(); player = null; });

async function toggle() {
  s.camOn = !s.camOn;
  if (!s.camOn) { s.frame = ''; s.video = false; s.camError = ''; s.camReason = ''; }
  lease();
  await nextTick();   // Turn on and Turn off are different buttons: keep the keyboard on the one that replaced the other
  if (document.activeElement === document.body) document.querySelector<HTMLElement>('[data-focus-key="camera"]')?.focus();
}
// A plain explanation per reason: what happened and what to do about it.
const msg = computed(() => {
  if (!s.camError) return t('cam.starting');
  if (s.camReason === 'no_ffmpeg') return t('cam.reason.no_ffmpeg');
  if (s.camReason === 'no_stream') return t('cam.reason.no_stream');
  return t('cam.reason.failed', { error: s.camError });
});
// No ffmpeg: the camera can't run at all, so it shows as off with that one reason (the plugin does not start it).
const off = computed(() => noFfmpeg.value || (link.value !== 'connected' && !s.camOn));
// While a re-check runs the last answer stands; say it is being looked at again rather than only "missing".
const why = computed(() => (noFfmpeg.value ? t(s.checking ? 'cam.checkingFfmpeg' : 'cam.noFfmpeg') : controlsOff.value || t('reason.waiting')));
const shown = computed(() => s.camOn && !noFfmpeg.value);
// Being looked for: said, but the camera can still be turned on (it then looks for ffmpeg itself).
const ffmpegPending = computed(() => s.checking && requirement('ffmpeg')?.state !== 'ok');
</script>

<template>
  <!-- Off: one row, not a 16:9 hole, so the printer's state stays above the fold. -->
  <OuiPanel class="cam-card" :class="{ compact: !shown }" :icon="camera" tone="sky" flush aria-labelledby="cam-h">
    <template #title><span id="cam-h">{{ t('cam.title') }}</span></template>
    <template v-if="shown" #actions>
      <Button severity="secondary" size="small" :label="t('cam.stop')" data-focus-key="camera" data-test="camera" @click="toggle"><template #icon><OuiIcon :icon="cameraOff" :size="14" /></template></Button>
    </template>
    <!-- The same reason as every other control: the page shows one connection state. -->
    <OuiEmpty v-if="!shown" compact tone="sky" :icon="cameraOff" :title="off ? t('cam.unavailable') : t('cam.offTitle')">
      <span v-if="off" data-test="cam-why">{{ why }}</span><template v-else>{{ ffmpegPending ? t('cam.checkingFfmpeg') : t('cam.offHint') }}</template>
      <template #actions><Button v-if="noFfmpeg" size="small" severity="secondary" text :label="t('cam.ffmpegSettings')" data-test="cam-req" @click="s.tab = 'settings'" />
        <Button severity="secondary" :label="t('cam.start')" :disabled="off" :aria-describedby="off && !noFfmpeg && controlsOff ? 'kc-why' : undefined"
                                 data-focus-key="camera" data-test="camera" @click="toggle"><template #icon><OuiIcon :icon="camera" :size="14" /></template></Button></template>
    </OuiEmpty>
    <div v-else class="cam-view">
      <video v-show="s.video" ref="vid" muted autoplay playsinline disablepictureinpicture data-test="cam-video" :aria-label="t('cam.alt', { printer: printerName })"></video>
      <img v-if="!s.video && s.frame" :src="s.frame" :alt="t('cam.alt', { printer: printerName })" @load="bridge.post({ type: 'frame_ack' })">
      <div v-else-if="!s.video" class="cam-empty oui-on-band" role="status" :data-reason="s.camReason">
        <OuiEmpty :state="s.camError ? 'error' : 'loading'" :icon="cameraOff" :title="msg">
          <template v-if="s.camReason === 'no_ffmpeg'" #actions>
            <Button size="small" severity="secondary" :label="t('cam.ffmpegSettings')" data-test="cam-settings" @click="s.tab = 'settings'"><template #icon><OuiIcon :icon="settings" :size="14" /></template></Button>
          </template>
        </OuiEmpty>
      </div>
    </div>
  </OuiPanel>
</template>

<style>
/* The picture area: always black behind the picture, whatever the theme (it is the camera's frame, not a surface). */
.cam-view { position: relative; display: flex; align-items: center; justify-content: center; overflow: hidden; aspect-ratio: 16 / 9; background: #000;
  border-radius: 0 0 var(--oui-radius-lg) var(--oui-radius-lg); }
.cam-view img, .cam-view video { width: 100%; height: 100%; object-fit: contain; }
.cam-view .cam-empty { background: none; max-width: 560px; text-align: center; }
</style>
