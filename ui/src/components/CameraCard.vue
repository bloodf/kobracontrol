<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import Button from 'primevue/button';
import { OuiCamera, OuiEmpty, OuiIcon, OuiPanel } from '../../shared/src/components';
import { camera, cameraOff, settings } from '../../shared/src/icons';
import * as bridge from '../core/bridge';
import { s, openSettings, lease, controlsOff, link, printerName, noFfmpeg, requirement } from '../app/store';
import { t } from '../core/i18n';
import { Player } from '../core/player';

// The stream from the plugin's Relay, played here; ffmpeg's JPEG frames (the fallback) still come as `frame`.
const vid = ref<HTMLVideoElement | null>(null);
let player: Player | null = null;
// s.video only once frames play; a failure hands the stream to the plugin's ffmpeg fallback.
const events = {
  playing: () => { if (s.camOn) { s.video = true; s.camError = ''; s.camReason = ''; } },
  failed: () => { s.video = false; bridge.post({ type: 'video_error' }); },
  reset: () => bridge.post({ type: 'video_reset' }),
};
watch(vid, el => {
  player?.close();
  player = el ? new Player(el, events) : null;
  if (player) bridge.post({ type: 'video_reset' });   // a (re)attached player needs the current stream's init
});
let unlisten = () => {};
onMounted(() => { unlisten = bridge.onMessage(m => {
  if (m?.type !== 'video') return;
  if (typeof m.data === 'string') bridge.post({ type: 'video_ack' });   // Relay's backpressure: taken, played or not
  if (!player) return;
  if (typeof m.init === 'string') player.init(String(m.codec), m.init);
  else if (typeof m.data === 'string') player.append(m.data, m.key === true);
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
const alt = computed(() => t('cam.alt', { printer: printerName.value }));
</script>

<template>
  <!-- OuiCamera's 16:9 box keeps its size whether the camera is off, starting, failed or live, so turning it on does not
       move the page. A camera that cannot run at all (no printer, no ffmpeg) is one row with the reason. -->
  <OuiPanel class="cam-card" :icon="camera" tone="sky" flush aria-labelledby="cam-h">
    <template #title><span id="cam-h">{{ t('cam.title') }}</span></template>
    <template v-if="shown" #actions>
      <Button severity="secondary" size="small" :label="t('cam.stop')" data-focus-key="camera" data-test="camera" @click="toggle"><template #icon><OuiIcon :icon="cameraOff" :size="14" /></template></Button>
    </template>
    <!-- The same reason as every other control: the page shows one connection state. -->
    <OuiEmpty v-if="off" compact :state="noFfmpeg ? 'empty' : 'offline'" :icon="cameraOff" :title="t('cam.unavailable')">
      <span data-test="cam-why">{{ why }}</span>
      <template v-if="noFfmpeg" #actions><Button size="small" severity="secondary" text :label="t('cam.ffmpegSettings')" data-test="cam-req" @click="openSettings('needs-h')" /></template>
    </OuiEmpty>
    <OuiCamera v-else-if="!shown" state="off" :alt="alt" :title="t('cam.offTitle')" :text="ffmpegPending ? t('cam.checkingFfmpeg') : t('cam.offHint')">
      <template #actions><Button severity="secondary" size="small" :label="t('cam.start')" data-focus-key="camera" data-test="camera" @click="toggle"><template #icon><OuiIcon :icon="camera" :size="14" /></template></Button></template>
    </OuiCamera>
    <div v-else class="cam-view">
      <!-- OuiCamera draws the JPEG frames and the starting and failed states; the stream the page plays itself is the
           <video> over it (foundation-gap: OuiCamera 5.0.0 takes a picture address only, it has no slot for a player). -->
      <OuiCamera v-show="!s.video" :class="{ 'cam-empty': !s.frame && !s.video }" :src="s.frame || null" :alt="alt" :state="s.frame ? 'live' : s.camError ? 'error' : 'loading'" :title="msg"
                 :role="s.frame ? undefined : 'status'" :data-reason="s.frame ? undefined : s.camReason" @load.capture="bridge.post({ type: 'frame_ack' })">
        <template v-if="s.camReason === 'no_ffmpeg'" #actions>
          <Button size="small" severity="secondary" :label="t('cam.ffmpegSettings')" data-test="cam-settings" @click="openSettings('cam-s-h')"><template #icon><OuiIcon :icon="settings" :size="14" /></template></Button>
        </template>
      </OuiCamera>
      <video ref="vid" :class="{ 'cam-hidden': !s.video }" muted autoplay playsinline disablepictureinpicture data-test="cam-video" :aria-label="alt"></video>
      <div v-if="s.video || s.frame" class="oui-camera-overlay"><span class="oui-chip">{{ t('cam.live') }}</span></div>
    </div>
  </OuiPanel>
</template>

<style>
/* The stage while the camera is on: OuiCamera's own 16:9 box, with the page's player over it once it plays. */
.cam-view { position: relative; aspect-ratio: 16 / 9; min-height: 120px; overflow: hidden; border-radius: 0 0 var(--oui-radius-lg) var(--oui-radius-lg); background: var(--oui-inset); }
.cam-view > .oui-camera { height: 100%; }
.cam-view > video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; background: #000; }
/* Not display:none: WebKit may not decode a hidden video, and it must play to say it plays. */
.cam-view > video.cam-hidden { opacity: 0; pointer-events: none; }
</style>
