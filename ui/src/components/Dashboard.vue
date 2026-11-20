<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import { OuiIcon, OuiPageHeader } from '@orca-plugins/ui-foundation/src/components';
import { edit } from '@orca-plugins/ui-foundation/src/icons';
import JobCard from './JobCard.vue';
import ControlsPanel from './ControlsPanel.vue';
import MotionPanel from './MotionPanel.vue';
import PrinterPanel from './PrinterPanel.vue';
import CameraCard from './CameraCard.vue';
import AceCard from './AceCard.vue';
import SpoolerHint from './SpoolerHint.vue';
import UsageCard from './UsageCard.vue';
import FirstRun from './FirstRun.vue';
import { s, run, tracker, busy, controlsOff, printerName, whyId } from '../app/store';
import { prompt } from '../core/dialog';
import { t } from '../core/i18n';

// The dashboard standard (DESIGN.md): the printer in the page header, the print across the top, what you work on
// (filament, controls) in the main column and what you watch (camera, moves, the printer's facts) beside it.
// Without a certificate or a printer the modules would only be empty: the one task and its recovery come instead.
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
    <template #actions>
      <Button severity="secondary" text :label="t('device.rename')" :disabled="renameOff" :aria-describedby="whyId(busy.print)"
              :loading="tracker.isBusy('rename')" data-focus-key="rename" data-test="rename" @click="rename">
        <template #icon><OuiIcon :icon="edit" :size="14" /></template></Button>
    </template>
  </OuiPageHeader>

  <!-- Always here, also on the first run: the page's messages are moved into it (App.vue). -->
  <div class="kc-msgs" data-msgs="dash" />

  <FirstRun v-if="firstRun" />

  <template v-else>
    <UsageCard />
    <SpoolerHint />

    <div class="oui-dash">
      <JobCard class="oui-dash-top" />
      <div class="oui-dash-main" data-test="filament">
        <AceCard />
        <ControlsPanel />
      </div>
      <div class="oui-dash-side" data-test="machine">
        <CameraCard />
        <MotionPanel />
        <PrinterPanel />
      </div>
    </div>
  </template>
</template>
