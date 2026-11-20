<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiControlRow, OuiEmpty, OuiKeyValue, OuiPanel, OuiStatus } from '@orca-plugins/ui-foundation/src/components';
import { printer } from '@orca-plugins/ui-foundation/src/icons';
import { s, run, tracker, busy, controlsOff, link, printerName, stale, loadDevice, whyId as pageWhy } from '../app/store';
import { ask } from '../core/dialog';
import { t, fmt } from '../core/i18n';
import type { MessageKey } from '../core/messages';

// The printer itself: firmware, network address and lifetime counters, then the Print Assist switches (its name and
// Rename are in the page header). Every value is the printer's own report; a counter or switch the firmware does not
// report is left out, never shown as 0 or off. Changing a switch asks first and needs an idle printer
// (status.can.print): while it works that is said once, in the page's banner (#kc-busy). What each switch does is
// behind the module's (i), and in the question it asks.
// The details and the switches come from messages read in Anycubic Slicer Next's Workbench; they are not yet tried
// on a Kobra X, so a firmware that ignores them just shows less.
const st = computed(() => s.status);

// The details and switches are asked for when this panel is shown with the printer idle, once per connection. An ask
// that failed (loadDevice puts s.device back to '') is made again the next time the printer becomes idle, not in a loop.
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
const changeOff = computed(() => !!controlsOff.value || busy.value.print);
const whyId = computed(() => pageWhy(busy.value.print));

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

</script>

<template>
  <OuiPanel :title="t('device.panel')" :icon="printer" :flush="!st" :hint-label="t('assist.title')" data-test="device">
    <template v-if="stale" #meta><OuiStatus state="stale">{{ t('status.lastKnownShort') }}</OuiStatus></template>
    <template v-if="switches.length" #hint><span class="kc-assist-help"><span v-for="sw in switches" :key="sw.key"><strong>{{ name(sw.key) }}</strong> {{ help(sw.key) }}</span></span></template>
    <OuiEmpty v-if="!st" compact :state="link === 'offline' ? 'offline' : 'loading'" :title="t('status.noStatus')" />
    <div v-else class="oui-controls kc-device">
      <OuiKeyValue v-if="facts.length" :items="facts" data-test="device-facts" />
      <div :key="rev" class="oui-controls-group" data-test="assist">
        <p class="oui-label">{{ t('assist.title') }}
          <OuiStatus v-if="assistNote" :state="s.device === 'asking' ? 'connecting' : 'idle'" variant="plain" class="kc-assist-note" data-test="assist-none" role="status">{{ assistNote }}</OuiStatus></p>
        <OuiControlRow v-for="sw in switches" :key="sw.key" :label="name(sw.key)" :for="`assist-${sw.key}`">
          <ToggleSwitch :input-id="`assist-${sw.key}`" :model-value="sw.on" :disabled="changeOff || tracker.isBusy(`assist:${sw.key}`)" :pt="{ input: { 'aria-describedby': whyId } }"
                        :data-assist="sw.key" :data-focus-key="`assist-${sw.key}`" @update:model-value="v => toggle(sw, v)" />
        </OuiControlRow>
      </div>
    </div>
  </OuiPanel>
</template>

<style>
.kc-device { grid-template-columns: minmax(0, 1fr); }
.kc-assist-help { display: grid; gap: var(--oui-s1); }
.kc-assist-note { margin-inline-start: auto; font-weight: 400; letter-spacing: 0; text-transform: none; }
</style>
