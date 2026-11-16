<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import Button from 'primevue/button';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiIcon, OuiKeyValue, OuiPanel, OuiStatus } from '../../shared/src/components';
import { edit, printer, shieldCheck } from '../../shared/src/icons';
import { s, run, tracker, controlsOff, printerName, stale, loadDevice } from '../app/store';
import { ask, prompt } from '../core/dialog';
import { t, fmt } from '../core/i18n';
import type { MessageKey } from '../core/messages';

// The printer itself: its name (Rename asks first), firmware, network address and lifetime counters, then the Print
// Assist switches. Every value is the printer's own report; a counter or switch the firmware does not report is left
// out, never shown as 0 or off. Changing a switch or the name asks first and needs an idle printer (status.can.print).
// The details and the switches come from messages read in Anycubic Slicer Next's Workbench; they are not yet tried
// on a Kobra X, so a firmware that ignores them just shows less.
const st = computed(() => s.status);
const NAME_MAX = 32;   // service.NAME_MAX, in UTF-8 bytes

// The details and switches are asked for when this panel is shown with the printer idle, once per connection.
const idle = computed(() => !!st.value?.connected && !!st.value.can.print && !controlsOff.value);
watch([idle, () => s.epoch], () => { if (idle.value && s.device === '') void loadDevice(); }, { immediate: true });

const facts = computed(() => {
  const v = st.value, stats = v?.stats ?? {};
  const rows: { label: string; value: string; mono?: boolean; key: string }[] = [];
  if (v?.firmware) rows.push({ key: 'firmware', label: t('device.firmware'), value: v.firmware });
  if (v?.mac) rows.push({ key: 'mac', label: t('device.mac'), value: v.mac, mono: true });
  if (stats.print_minutes != null) rows.push({ key: 'time', label: t('device.printTime'), value: fmt.duration(stats.print_minutes * 60) });
  if (stats.print_count != null) rows.push({ key: 'count', label: t('device.prints'), value: fmt.number(stats.print_count) });
  if (stats.filament_g != null) rows.push({ key: 'filament', label: t('device.filament'),
    value: stats.filament_g >= 1000 ? `${fmt.number(stats.filament_g / 1000, 2)} kg` : fmt.grams(stats.filament_g) });
  return rows;
});

// Idle only: the printer is not asked to change how it prints while it prints.
const changeWhy = computed(() => controlsOff.value || (st.value && !st.value.can.print ? t('reason.noDeviceChange') : ''));
const whyId = computed(() => (controlsOff.value ? 'kc-why' : changeWhy.value ? 'device-why' : undefined));

interface Switch { key: string; option: number | null; on: boolean }
// The order of Anycubic Slicer Next's Print Assist dialog. option null: auto-feed, which is each ACE's own setting.
const ORDER: [string, number | null][] = [['breakAlert', 3], ['jamAlert', 4], ['autoFeed', null], ['remain', 5], ['belt', 0], ['lostStep', 1]];
const switches = computed<Switch[]>(() => {
  const assist = st.value?.assist ?? null, units = st.value?.ace_units ?? [];
  return ORDER.flatMap(([key, option]): Switch[] => {
    if (option == null) return units.length ? [{ key, option, on: units.every(u => u.auto_feed) }] : [];
    const value = assist?.[String(option)];
    return typeof value === 'boolean' ? [{ key, option, on: value }] : [];
  });
});
// The printer's own switches (all but auto-feed) are missing: still being asked, or the firmware did not answer.
const assistNote = computed(() => (st.value?.assist != null ? '' : s.device === 'done' ? t('assist.none') : s.device === 'asking' ? t('assist.asking')
  : st.value && !controlsOff.value ? t('assist.whenIdle') : ''));
// A switch shows the printer's value, never the click: it is drawn again from that value when asked.
const rev = ref(0);
// Each switch's name and help, spelled out (no keys built at run time: the messages test checks every key is used).
const TEXT: Record<string, [MessageKey, MessageKey]> = {
  breakAlert: ['assist.breakAlert', 'assist.breakAlert.help'], jamAlert: ['assist.jamAlert', 'assist.jamAlert.help'],
  autoFeed: ['assist.autoFeed', 'assist.autoFeed.help'], remain: ['assist.remain', 'assist.remain.help'],
  belt: ['assist.belt', 'assist.belt.help'], lostStep: ['assist.lostStep', 'assist.lostStep.help'] };
const name = (key: string) => t(TEXT[key][0]);
const help = (key: string) => t(TEXT[key][1]);

async function toggle(sw: Switch, on: boolean) {
  const what = name(sw.key);
  rev.value++;   // the switch keeps showing the printer's value while the question is open
  if (!await ask({ title: t(on ? 'confirm.assist.onTitle' : 'confirm.assist.offTitle', { what }),
    text: help(sw.key) + '\n' + t('confirm.assist.text', { printer: printerName.value }),
    yes: t(on ? 'confirm.assist.on' : 'confirm.assist.off'), no: t('common.goBack') })) return;
  await run({ key: `assist:${sw.key}`, label: t('act.assist', { what }), cmd: 'assist', args: { option: sw.key, on },
    okText: t(on ? 'ok.assistOn' : 'ok.assistOff', { what }), sentText: t('sent.assist', { what }) });
}

// service.cmd_rename's rule: 1-32 UTF-8 bytes, no control characters, quotes, backslashes or angle brackets.
const validName = (v: string) => { const n = v.trim().replace(/\s+/g, ' ');
  return n && new TextEncoder().encode(n).length <= NAME_MAX && !/["<>\\\u0000-\u001f]/.test(n) ? n : ''; };
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
  <OuiPanel :title="t('device.panel')" :icon="printer" tone="cobalt" data-test="device">
    <template v-if="stale" #meta><OuiStatus state="stale">{{ t('status.lastKnownShort') }}</OuiStatus></template>
    <div class="kc-device">
      <div class="kc-line">
        <span class="kc-line-label kc-device-name"><span class="oui-meta">{{ t('device.name') }}</span><strong data-test="device-name">{{ st?.printer_name || '—' }}</strong></span>
        <Button severity="secondary" size="small" :label="t('device.rename')" :disabled="!!changeWhy || !st?.printer_name" :aria-describedby="whyId"
                :loading="tracker.isBusy('rename')" data-focus-key="rename" data-test="rename" @click="rename">
          <template #icon><OuiIcon :icon="edit" :size="14" /></template></Button>
      </div>
      <OuiKeyValue v-if="facts.length" :items="facts" data-test="device-facts" />

      <h3 class="kc-device-sub"><OuiIcon :icon="shieldCheck" :size="14" tile tone="lime" />{{ t('assist.title') }}</h3>
      <div v-if="switches.length" :key="rev" class="kc-rows" data-test="assist">
        <div v-for="sw in switches" :key="sw.key" class="kc-line">
          <label :for="`assist-${sw.key}`" class="kc-line-label kc-assist-label">{{ name(sw.key) }}
            <span class="oui-meta">{{ help(sw.key) }}</span></label>
          <ToggleSwitch :input-id="`assist-${sw.key}`" :model-value="sw.on" :disabled="!!changeWhy || tracker.isBusy(`assist:${sw.key}`)" :pt="{ input: { 'aria-describedby': whyId } }"
                        :data-assist="sw.key" :data-focus-key="`assist-${sw.key}`" @update:model-value="v => toggle(sw, v)" />
        </div>
      </div>
      <p v-if="assistNote" class="oui-meta" data-test="assist-none" role="status">{{ assistNote }}</p>
      <p v-if="changeWhy && !controlsOff" id="device-why" class="oui-meta" data-test="device-why">{{ changeWhy }}</p>
    </div>
  </OuiPanel>
</template>

<style>
.kc-device { display: grid; gap: var(--oui-s3); }
.kc-device-name { display: grid; gap: 0; font-weight: 400; }
.kc-device-name strong { font-weight: 700; overflow-wrap: anywhere; }
.kc-device-sub { display: flex; align-items: center; gap: var(--oui-s2); margin: var(--oui-s1) 0 0; font-size: var(--oui-text-sm); font-weight: 700; }
.kc-assist-label { display: grid; gap: 0; font-weight: 600; }
.kc-assist-label .oui-meta { font-weight: 400; }
</style>
