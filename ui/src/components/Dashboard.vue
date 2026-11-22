<script setup lang="ts">
import { computed, markRaw, ref, watch } from 'vue';
import Button from 'primevue/button';
import { OuiDashboard, OuiIcon, OuiPageHeader, OuiStatus, validateLayout, replaceRetired, type OuiDashboardLabels, type OuiWidget } from '@orca-plugins/ui-foundation/src/components';
import { ace, camera, edit, files, move, printer, terminal, thermometer } from '@orca-plugins/ui-foundation/src/icons';
import JobCard from './JobCard.vue';
import ControlsPanel from './ControlsPanel.vue';
import MotionPanel from './MotionPanel.vue';
import PrinterPanel from './PrinterPanel.vue';
import CameraCard from './CameraCard.vue';
import AceCard from './AceCard.vue';
import SpoolerHint from './SpoolerHint.vue';
import SetupHint from './SetupHint.vue';
import UsageCard from './UsageCard.vue';
import FirstRun from './FirstRun.vue';
import ConsoleCard from './ConsoleCard.vue';
import TempsCard from './TempsCard.vue';
import FilesCard from './FilesCard.vue';
import { s, run, tracker, busy, controlsOff, printerName, whyId, lease, LOG_MAX } from '../app/store';
import { config } from '../app/settings';
import * as bridge from '../core/bridge';
import { prompt } from '../core/dialog';
import { t } from '../core/i18n';

// The dashboard standard (DESIGN.md): the printer in the page header, the print across the top, what you work on
// (filament, controls) in the main column and what you watch (camera, moves, the printer's facts) beside it.
// Without a certificate or a printer the modules would only be empty: the one task and its recovery come instead.
// The modules are widgets the user arranges (OuiDashboard): sizes in columns of 12 and 32 px rows. The default is the
// dashboard standard: the print across the top, filament and controls beside the camera, moves and the printer's facts.
const n = (v: number) => ({ value: v, label: String(v) });
// A widget that is not `fill` is at least as tall as its content: its rows grow to fit it at any window width, so its
// least height only keeps it from being dragged to nothing. The camera and the console fill what they get.
const widgets = computed<OuiWidget[]>(() => [
  { id: 'job', title: t('status.title'), icon: printer, component: markRaw(JobCard), w: 6, h: 2, minW: 4, minH: 2 },
  { id: 'ace', title: t('ace.title'), icon: ace, component: markRaw(AceCard), w: 6, h: 16, minW: 5, minH: 4 },
  { id: 'temps', title: t('widget.temps'), icon: thermometer, component: markRaw(TempsCard), w: 3, h: 4, minW: 3, minH: 3,
    settings: [{ key: 'nozzle', label: t('temps.nozzle'), default: true }, { key: 'bed', label: t('temps.bed'), default: true }, { key: 'fan', label: t('fan.label'), default: true }] },
  { id: 'controls', title: t('controls.title'), icon: thermometer, component: markRaw(ControlsPanel), w: 6, h: 4, minW: 4, minH: 3 },
  { id: 'camera', title: t('cam.title'), icon: camera, component: markRaw(CameraCard), w: 3, h: 9, minW: 3, minH: 4, fill: true,
    settings: [{ key: 'aspect', label: t('widget.aspect'), default: '16/9', options: [{ value: '16/9', label: '16:9' }, { value: '4/3', label: '4:3' }, { value: '1/1', label: '1:1' }] }] },
  { id: 'motion', title: t('motion.title'), icon: move, component: markRaw(MotionPanel), w: 3, h: 5, minW: 3, minH: 3 },
  { id: 'printer', title: t('device.panel'), icon: printer, component: markRaw(PrinterPanel), w: 3, h: 10, minW: 3, minH: 3 },
  { id: 'console', title: t('console.title'), icon: terminal, component: markRaw(ConsoleCard), w: 12, h: 6, minW: 3, minH: 4, fill: true,
    settings: [{ key: 'lines', label: t('widget.lines'), default: 400, options: [100, 400, LOG_MAX].map(n) }] },
  { id: 'files', title: t('nav.files'), icon: files, component: markRaw(FilesCard), w: 4, h: 3, minW: 3, minH: 3 },
]);
// The owner's own arrangement: the print over the filament over the console on the left; the controls, then the
// temperatures over the printer's facts beside the camera over the moves, on the right. Rows grow to fit content.
// Files is in the catalogue. A widget a printer does not offer is left out and the rest keep their places.
const DEFAULT_ITEMS = [
  { id: 'job', x: 0, y: 0, w: 6, h: 2 }, { id: 'ace', x: 0, y: 2, w: 6, h: 8 },
  { id: 'controls', x: 6, y: 0, w: 6, h: 4 }, { id: 'temps', x: 6, y: 4, w: 3, h: 4 }, { id: 'printer', x: 6, y: 8, w: 3, h: 4 },
  { id: 'camera', x: 9, y: 4, w: 3, h: 9 }, { id: 'motion', x: 9, y: 13, w: 3, h: 5 },
  { id: 'console', x: 0, y: 10, w: 6, h: 8 }];
const defaults = computed(() => { const ids = new Set(widgets.value.map(w => w.id));
  return { name: t('layout.default'), items: DEFAULT_ITEMS.filter(i => ids.has(i.id)) }; });
// Earlier defaults: a layout still exactly as one of them is given today's.
const RETIRED = [[{ id: 'job', x: 0, y: 0, w: 6, h: 2 }, { id: 'ace', x: 0, y: 2, w: 6, h: 16 },
  { id: 'controls', x: 6, y: 0, w: 6, h: 4 }, { id: 'temps', x: 6, y: 4, w: 3, h: 4 }, { id: 'printer', x: 6, y: 8, w: 3, h: 10 },
  { id: 'camera', x: 9, y: 4, w: 3, h: 9 }, { id: 'motion', x: 9, y: 13, w: 3, h: 5 }, { id: 'console', x: 0, y: 18, w: 12, h: 6 }],
[{ id: 'job', x: 0, y: 0, w: 12, h: 3 }, { id: 'ace', x: 0, y: 3, w: 12, h: 16 }, { id: 'controls', x: 0, y: 19, w: 8, h: 6 },
  { id: 'camera', x: 8, y: 19, w: 4, h: 6 }, { id: 'console', x: 0, y: 25, w: 8, h: 12 }, { id: 'motion', x: 8, y: 25, w: 4, h: 6 }, { id: 'printer', x: 8, y: 31, w: 4, h: 12 }],
[{ id: 'job', x: 0, y: 0, w: 12, h: 3 }, { id: 'ace', x: 0, y: 3, w: 12, h: 16 }, { id: 'temps', x: 0, y: 19, w: 6, h: 4 }, { id: 'camera', x: 6, y: 19, w: 6, h: 9 },
  { id: 'motion', x: 0, y: 23, w: 6, h: 5 }, { id: 'controls', x: 0, y: 28, w: 8, h: 6 }, { id: 'printer', x: 8, y: 28, w: 4, h: 12 }, { id: 'console', x: 0, y: 34, w: 8, h: 6 }]];
const labels = computed<OuiDashboardLabels>(() => ({
  toolbar: t('layout.toolbar'), layout: t('layout.layout'), edit: t('layout.edit'), save: t('layout.save'), cancel: t('layout.cancel'), add: t('layout.add'),
  addTitle: t('layout.addTitle'), added: t('layout.added'), close: t('layout.close'), newLayout: t('layout.new'), rename: t('layout.rename'), remove: t('layout.remove'),
  reset: t('layout.reset'), create: t('layout.create'), apply: t('layout.apply'), keep: t('layout.keep'), removeAsk: name => t('layout.removeAsk', { name }),
  nameEmpty: t('layout.nameEmpty'), nameTaken: t('layout.nameTaken'), settings: widget => t('layout.settings', { widget }), removeWidget: widget => t('layout.removeWidget', { widget }),
  widget: widget => t('layout.widget', { widget }), place: (widget, x, y, w, h) => t('layout.place', { widget, x, y, w, h }), removed: widget => t('layout.removed', { widget }),
  hint: t('layout.hint'), narrow: t('layout.narrow'), empty: t('layout.empty'), maximize: t('layout.maximize'), restore: t('layout.restore'),
}));
// Stored with the plugin's settings (settings "dashboard"); what the user saved here wins over a config that is older.
const saved = ref<unknown>(undefined);
const layout = computed({
  get: () => replaceRetired(saved.value !== undefined ? saved.value : config.value?.settings.dashboard, RETIRED, defaults.value.items),
  set: (v: unknown) => { saved.value = v; bridge.post({ type: 'dashboard', value: v }); },
});
// The camera streams only while its widget is on the open layout.
watch(() => { const st = validateLayout(layout.value, widgets.value, defaults.value); return st.layouts[st.active].items.map(i => i.id).join(); },
  ids => { s.widgets = ids.split(','); lease(); }, { immediate: true });

const firstRun = computed(() => s.phase === 'noCertificate' || s.phase === 'noTarget');
const st = computed(() => s.status);
const name = computed(() => st.value?.printer_name || printerName.value);
const meta = computed(() => [s.info?.address, st.value?.model, st.value?.firmware ? t('status.firmware', { version: st.value.firmware }) : ''].filter(Boolean).join(' · '));

// Rename asks for the name first and needs an idle printer (status.can.print), like every change to the printer itself.
// service.cmd_rename's rule: 1-32 UTF-8 bytes, no control characters, quotes, backslashes or angle brackets.
const NAME_MAX = 32;
const validName = (v: string) => { const n = v.trim().replace(/\s+/g, ' ');
  return n && new TextEncoder().encode(n).length <= NAME_MAX && !/["<>\\\u0000-\u001f]/.test(n) ? n : ''; };
const renameOff = computed(() => !!controlsOff.value || busy.value.print || !st.value?.printer_name);
async function rename() {
  const typed = await prompt({ title: t('confirm.rename.title'), text: t('confirm.rename.text', { max: NAME_MAX }),
    input: { label: t('device.name'), value: st.value?.printer_name ?? '' }, yes: t('confirm.rename.yes'), no: t('common.goBack') });
  if (typed == null) return;
  const next = validName(typed);
  if (!next) { tracker.notify('error', t('device.nameInvalid', { max: NAME_MAX })); return; }
  if (next === st.value?.printer_name) return;
  await run({ key: 'rename', label: t('act.rename'), cmd: 'rename', args: { name: next }, okText: t('ok.rename', { name: next }),
    sentText: t('sent.rename'), timeoutMs: 20000 });
}
</script>

<template>
  <OuiPageHeader v-if="!firstRun" :title="name" :meta="meta" data-test="printer-head">
    <template v-if="st?.transport === 'cloud'" #meta>{{ meta }} <OuiStatus state="idle" data-test="cloud-tag">{{ t('cloud.title') }}</OuiStatus></template>
    <template #actions>
      <Button severity="secondary" text :label="t('device.rename')" :disabled="renameOff" :aria-describedby="whyId(busy.print)"
              :loading="tracker.isBusy('rename')" data-focus-key="rename" data-test="rename" @click="rename">
        <template #icon><OuiIcon :icon="edit" :size="14" /></template></Button>
    </template>
  </OuiPageHeader>

  <!-- Always here, also on the first run: the page's messages are moved into it (App.vue). -->
  <div class="kc-msgs" data-msgs="dash" />

  <SetupHint />
  <FirstRun v-if="firstRun" />

  <template v-else>
    <UsageCard />
    <SpoolerHint />

    <OuiDashboard v-model="layout" :widgets="widgets" :defaults="defaults" :labels="labels" :narrow-at="1000" />
  </template>
</template>
