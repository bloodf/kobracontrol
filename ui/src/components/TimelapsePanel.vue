<script setup lang="ts">
import { nextTick, ref, watch } from 'vue';
import Button from 'primevue/button';
import { OuiEmpty, OuiIcon, OuiPanel, OuiStatus, OuiThumb } from '../../shared/src/components';
import { refresh, trash, video } from '../../shared/src/icons';
import * as bridge from '../core/bridge';
import { s, run, tracker } from '../app/store';
import { ask } from '../core/dialog';
import { t, tn, fmt } from '../core/i18n';
import { message } from '../core/tracker';
import { clipLength } from '../core/logic';
import type { VideoEntry, VideosResult } from '../app/types';

// The printer's time-lapse videos, in the Files tab: listed and deleted, for a connected printer (idle or printing).
// Neither a video nor its cover picture can be fetched over the LAN: the cover is a placeholder and there is no
// download.
const state = ref<'idle' | 'loading' | 'ok' | 'error'>('idle');
const error = ref('');
const videos = ref<VideoEntry[]>([]);
let loadSeq = 0;

async function load() {
  if (!s.info) { state.value = 'idle'; videos.value = []; return; }
  const mine = ++loadSeq;
  state.value = 'loading';
  try {
    const r: VideosResult = await bridge.command('videos', {}, s.info.generation);
    if (mine !== loadSeq) return;
    videos.value = r.videos ?? [];
    state.value = 'ok';
  } catch (e) {
    if (mine !== loadSeq) return;
    error.value = message(e); state.value = 'error';
  }
}
watch(() => [s.tab, s.epoch, s.phase], () => { if (s.tab === 'files') void load(); }, { immediate: true });

const when = (v: VideoEntry) => (v.created ? fmt.dateTime(v.created) : '');
const named = (v: VideoEntry) => ({ name: v.name, date: when(v) || t('common.unknown') });
/** Date, length and size on one line, for a panel too narrow for their columns. */
const facts = (v: VideoEntry) => [when(v), v.empty ? t('videos.aborted') : clipLength(v.duration), fmt.bytes(v.size)].filter(Boolean).join(' · ');

// A deleted row takes its Delete button along. Refresh then stands for it (data-focus-key), so the focus goes there
// whether the dialog or the printer's answer finishes first, never to <body>.
const refreshKey = ref('videos-refresh');
async function del(v: VideoEntry) {
  if (!await ask({ title: t('act.videoDelete'), text: t('confirm.videoDelete.text', named(v)), yes: t('confirm.videoDelete.yes'), no: t('common.goBack'), danger: true })) return;
  const key = `vdel:${v.filename}`;
  const r = await run({ key, label: t('act.videoDelete'), cmd: 'video_delete', args: { name: v.filename }, okText: t('ok.videoDelete') });
  if (!r.ok && r.reason === 'busy') return;
  if (r.ok) refreshKey.value = key;
  await load();   // after an error too: the list then shows whether the video is still on the printer
  await nextTick();
  if (document.activeElement === document.body) document.querySelector<HTMLElement>(`[data-focus-key="${CSS.escape(key)}"]`)?.focus();
}
</script>
<template>
  <OuiPanel v-if="s.phase === 'connected'" :icon="video" flush aria-labelledby="videos-h" class="tl" data-test="videos">
    <template #title><span id="videos-h">{{ t('videos.title') }}</span></template>
    <template #meta><span v-if="state !== 'error' && videos.length" data-test="videos-count">{{ tn('videos.count', videos.length) }}</span></template>
    <template #actions>
      <Button severity="secondary" size="small" :label="t('common.refresh')" :aria-label="t('videos.refresh')" :loading="state === 'loading'" data-test="videos-refresh"
              :data-focus-key="refreshKey" @click="load"><template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
    </template>
    <OuiEmpty v-if="state === 'error'" state="error" class="tl-error" :title="t('videos.error', { error })">
      <template #actions><Button size="small" severity="secondary" :label="t('common.retry')" @click="load"><template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button></template>
    </OuiEmpty>
    <div v-else-if="videos.length" class="oui-table-wrap">
      <table class="kc-table tl-table">
        <thead><tr><th scope="col">{{ t('videos.col.print') }}</th><th scope="col" class="tl-date">{{ t('videos.col.recorded') }}</th>
          <th scope="col" class="oui-num tl-len">{{ t('videos.col.length') }}</th><th scope="col" class="oui-num tl-size">{{ t('files.col.size') }}</th>
          <th scope="col" class="oui-end tl-act"><span class="oui-sr">{{ t('files.col.actions') }}</span></th></tr></thead>
        <tbody>
          <tr v-for="v in videos" :key="v.filename" :data-video="v.filename" :data-empty="v.empty || undefined">
            <td><span class="tl-name"><OuiThumb :icon="video" :size="40" />
              <span class="tl-text"><span class="oui-strong">{{ v.name }}</span><span class="oui-meta tl-wide">{{ v.empty ? t('videos.abortedHint') : v.filename }}</span>
                <span class="oui-meta tl-narrow">{{ facts(v) }}</span></span></span></td>
            <td class="tl-date">{{ when(v) }}</td>
            <td class="oui-num tl-len"><OuiStatus v-if="v.empty" state="idle" variant="plain">{{ t('videos.aborted') }}</OuiStatus><template v-else>{{ clipLength(v.duration) }}</template></td>
            <td class="oui-num tl-size">{{ fmt.bytes(v.size) }}</td>
            <!-- Delete always asks first. There is no download: the printer has no way to hand a video over the LAN. -->
            <td class="oui-end"><Button size="small" severity="danger" text :label="t('files.delete')" :aria-label="t('videos.deleteLabel', named(v))" :loading="tracker.isBusy(`vdel:${v.filename}`)"
                                        :data-focus-key="`vdel:${v.filename}`" data-video-delete @click="del(v)"><template #icon><OuiIcon :icon="trash" :size="14" /></template></Button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <OuiEmpty v-else-if="state === 'ok'" class="tl-empty" :icon="video" :title="t('videos.empty')" :text="t('videos.emptyHint')" />
    <OuiEmpty v-else state="loading" :title="t('videos.loading')" role="status" />
    <template v-if="state !== 'error' && videos.length" #footer><span class="oui-meta" data-test="videos-note">{{ t('videos.noDownload') }}</span></template>
  </OuiPanel>
</template>

<style>
.tl { container: tl / inline-size; }
.tl-table { table-layout: fixed; }
.tl-date { width: 150px; } .tl-len { width: 96px; } .tl-size { width: 96px; } .tl-act { width: 124px; }
.tl-narrow { display: none; }
/* A narrow panel (a small window, or the file panel open beside it): date, length and size move under the name. */
@container tl (max-width: 760px) {
  .tl-table :is(.tl-date, .tl-len, .tl-size), .tl-wide { display: none; }
  .tl-narrow { display: block; }
}
.tl-name { display: flex; align-items: center; gap: var(--oui-s3); min-width: 0; }
.tl-text { display: grid; min-width: 0; overflow-wrap: anywhere; }
</style>
