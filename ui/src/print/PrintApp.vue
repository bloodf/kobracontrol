<script setup lang="ts">
// Kobra Control — print setup: opened by the plugin after OrcaSlicer's Print (plugin.ask_print), pre-filled from that
// dialog's choice. Top to bottom: the print task's name, the plate, one chip per filament with its slot, the printer and
// its slots, the print options, then Cancel / Start print. The plugin checks the answer again; this page only shows the
// choice and keeps Start print off while it can't be printed.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import Button from 'primevue/button';
import Checkbox from 'primevue/checkbox';
import InputText from 'primevue/inputtext';
import { OuiAppBar, OuiBanner, OuiHint, OuiIcon, OuiStatus } from '@orca-plugins/ui-foundation/src/components';
import { ace as aceIcon, clock, play, plate as plateIcon, refresh, settings as settingsIcon, spool } from '@orca-plugins/ui-foundation/src/icons';
import * as bridge from '../core/bridge';
import { boot } from '../core/boot';
import { fmt, t, tMaybe } from '../core/i18n';
import type { MessageKey } from '../core/messages';
import { checkChoice, issueKey, type PdFilament, type PdIssue, type PdSlot } from '../core/printsetup';
import SlotPicker from './SlotPicker.vue';
import { slotName } from './slots';

interface Option { key: string; on: boolean; lock: '' | 'setting' | 'unsupported' }
interface Data {
  printer: { name: string; host: string; state: string; can_print: boolean; model?: string };
  job: { name?: string; plate?: number; seconds?: number; grams?: number; metres?: number; thumbnail?: string };
  filaments: PdFilament[]; slots: PdSlot[]; trays: Record<string, number>; options: Option[];
  auto_feed: boolean | null; remember: boolean;
}
const D = boot.data as Data;
const slots = ref<PdSlot[]>(D.slots);
const state = ref(D.printer.state);
const canPrintNow = ref(D.printer.can_print !== false);
const name = ref(D.job.name ?? '');
const trays = reactive<Record<string, number>>({ ...D.trays });
const options = reactive<Record<string, boolean>>(Object.fromEntries(D.options.map(o => [o.key, o.on])));
const autoFeed = ref(D.auto_feed);
const remember = ref(D.remember);
const sent = ref(false);
const refreshing = ref(false);
const settingsSent = ref(false);

const OPTION_LABEL: Record<string, MessageKey> = { auto_leveling: 'files.autoLeveling', vibration_compensation: 'files.vibration',
  timelapse: 'files.timelapse', flow_calibration: 'files.flow' };
const ORDER = ['auto_leveling', 'vibration_compensation', 'timelapse', 'flow_calibration'];   // the 2 × 2 grid, row by row
const shownOptions = computed(() => [...D.options].sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key)));

const byTray = (tray: number) => slots.value.find(s => s.tray === tray);
const choice = computed(() => checkChoice(D.filaments, slots.value, trays));
const issues = computed(() => [...choice.value.blocking, ...choice.value.warnings, ...choice.value.hints]);
const invalid = (f: number) => choice.value.blocking.some(i => i.f === f);

function issueText(i: PdIssue): string {
  const f = D.filaments.find(x => x.index === i.f);
  const slot = slotName(byTray(i.tray));
  const b = byTray(i.tray)?.type ?? '';
  if (i.kind === 'none') return t('pd.warn.none', { f: i.f + 1 });
  if (i.kind === 'empty') return t('pd.warn.empty', { f: i.f + 1, slot });
  if (i.kind === 'material') return t('pd.warn.material', { f: i.f + 1, a: f?.type ?? '', slot, b });
  if (i.kind === 'variant') return t('pd.warn.variant', { f: i.f + 1, a: f?.type ?? '', slot, b });
  return t('pd.hint.colour', { slot });
}
const tone = (i: PdIssue) => (i.kind === 'colour' ? 'info' : i.kind === 'variant' ? 'warn' : 'danger');

// "Use anyway" belongs to one exact set of same-family warnings: another choice or a slot change clears it.
const ackFor = ref('');
const ackReset = ref(false);
const acked = computed({
  get: () => !!choice.value.warnings.length && ackFor.value === issueKey(choice.value.warnings),
  set: (v: boolean) => { ackFor.value = v ? issueKey(choice.value.warnings) : ''; ackReset.value = false; },
});
watch(() => issueKey(choice.value.warnings), now => {
  if (ackFor.value && ackFor.value !== now) { ackFor.value = ''; ackReset.value = true; }
  if (!now) ackReset.value = false;
});

const busy = computed(() => !canPrintNow.value);
const locked = computed(() => busy.value || sent.value);
const blocked = computed(() => choice.value.blocking.length > 0);
const canPrint = computed(() => !locked.value && !blocked.value && (!choice.value.warnings.length || acked.value));
const why = computed(() => locked.value ? '' : blocked.value ? t('pd.blocked') : !canPrint.value ? t('pd.needAck') : '');
const stateText = computed(() => tMaybe(`status.state.${state.value}`, state.value));
const lockText = (o: Option) => (o.lock ? t(o.lock === 'setting' ? 'pd.lock.setting' : 'pd.lock.unsupported') : '');
const usage = computed(() => [D.job.grams ? fmt.grams(D.job.grams) : '', D.job.metres ? `${fmt.number(D.job.metres, 2)} m` : '']
  .filter(Boolean).join(' / '));

function pick(f: number, tray: number) { trays[String(f)] = tray; }
function refreshSlots() { refreshing.value = true; bridge.post({ refresh: true }); }
function openSettings() { settingsSent.value = true; bridge.post({ open_settings: true }); }
function print() {
  if (!canPrint.value) return;
  sent.value = true;
  bridge.submit({ name: name.value, trays: { ...trays }, options: { ...options }, remember: remember.value,
    acknowledged: choice.value.warnings.map(w => w.id), ...(autoFeed.value === null ? {} : { auto_feed: autoFeed.value }) });
}
const cancel = () => { if (!sent.value) bridge.submit({ cancelled: true }); };

// Capture phase: an open slot picker closes itself first; Escape on the page cancels.
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && !document.querySelector('.p-popover, .p-select-overlay')) cancel();
}
onMounted(() => {
  bridge.attach();
  bridge.onMessage(m => {   // slots or state changed on the printer while the window is open, or a Refresh answered
    if (!m || !Array.isArray(m.slots)) return;
    slots.value = m.slots;
    refreshing.value = false;
    if (typeof m.state === 'string') state.value = m.state;
    if (typeof m.can_print === 'boolean') canPrintNow.value = m.can_print;
  });
  document.addEventListener('keydown', onKey, true);
  bridge.post({ ready: true });
});
onBeforeUnmount(() => document.removeEventListener('keydown', onKey, true));
</script>

<template>
  <OuiAppBar :name="t('pd.title')">
    <template #mark>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 6H7L4 9V15L7 18H10M14 6H17L20 9V15L17 18H14M4 12H20" /></svg>
    </template>
  </OuiAppBar>

  <main class="oui-page pd">
    <label class="pd-name"><span class="oui-sr">{{ t('pd.taskName') }}</span>
      <InputText v-model="name" :aria-label="t('pd.taskName')" :placeholder="t('pd.taskName')" :disabled="sent" maxlength="120" data-test="name" fluid />
    </label>

    <section class="pd-plate" :aria-label="t('pd.thumb')">
      <span class="pd-for">{{ t('pd.for', { model: D.printer.model || 'Anycubic' }) }}<template v-if="D.job.plate"> · {{ t('pd.plate', { n: D.job.plate }) }}</template></span>
      <img v-if="D.job.thumbnail" class="pd-thumb" :src="'data:image/png;base64,' + D.job.thumbnail" :alt="t('pd.thumb')" />
      <OuiIcon v-else :icon="plateIcon" :size="72" class="pd-thumb pd-thumb-none" />
      <dl class="pd-facts">
        <div v-if="D.job.seconds"><dt><OuiIcon :icon="clock" :size="15" /><span class="oui-sr">{{ t('pd.time') }}</span></dt><dd class="oui-num">{{ fmt.duration(D.job.seconds) }}</dd></div>
        <div v-if="usage"><dt><OuiIcon :icon="spool" :size="15" /><span class="oui-sr">{{ t('pd.use') }}</span></dt><dd class="oui-num">{{ usage }}</dd></div>
      </dl>
    </section>

    <section aria-labelledby="pd-fils" class="pd-section">
      <h2 id="pd-fils" class="oui-sr">{{ t('pd.filaments') }}</h2>
      <div class="pd-chips">
        <SlotPicker v-for="f in D.filaments" :key="f.index" :filament="f" :slots="slots" :tray="trays[String(f.index)] ?? -1"
                    :disabled="locked" :invalid="invalid(f.index)" @pick="v => pick(f.index, v)" />
      </div>
      <ul v-if="issues.length" class="pd-issues" role="list" aria-live="polite">
        <li v-for="i in issues" :key="i.id" class="pd-note" :data-tone="tone(i)" :data-kind="i.kind">{{ issueText(i) }}</li>
      </ul>
      <template v-if="choice.warnings.length && !locked">
        <p v-if="ackReset" class="pd-note" data-tone="warn" role="status">{{ t('pd.ackReset') }}</p>
        <label class="pd-check" for="pd-ack"><Checkbox v-model="acked" input-id="pd-ack" binary data-test="ack" />{{ t('pd.ack') }}</label>
      </template>
    </section>

    <section class="pd-section" aria-labelledby="pd-p">
      <div class="pd-head">
        <h2 id="pd-p" class="pd-h">{{ t('pd.printerLabel') }}</h2>
        <Button text rounded size="small" :aria-label="t('pd.refresh')" :title="t('pd.refresh')" :loading="refreshing" data-test="refresh" @click="refreshSlots">
          <template #icon><OuiIcon :icon="refresh" :size="15" /></template></Button>
      </div>
      <div class="pd-printer">
        <span class="pd-printer-id"><span class="oui-strong oui-truncate">{{ D.printer.name }} · {{ D.printer.host }}</span>
          <OuiStatus :state="busy ? 'busy' : 'ok'" variant="plain" data-test="state">{{ stateText }}</OuiStatus></span>
        <span class="pd-ace" role="img" :aria-label="t('pd.slots') + ': ' + slots.map(s => slotName(s) + ' ' + (s.usable ? s.type : t('slot.empty'))).join(', ')">
          <OuiIcon :icon="aceIcon" :size="18" />
          <span v-for="s in slots" :key="s.tray" class="pd-sq" :data-empty="!s.usable || undefined" :style="s.usable ? { background: s.colour } : {}" :title="slotName(s) + (s.spool ? ' · ' + s.spool : '')" />
        </span>
      </div>
      <OuiBanner v-if="busy" tone="warn" :title="t('pd.busy', { state: stateText })" role="status" data-test="busy" />
    </section>

    <section class="pd-section" aria-labelledby="pd-o">
      <h2 id="pd-o" class="pd-h">{{ t('pd.options') }}</h2>
      <div class="pd-grid">
        <label v-for="o in shownOptions" :key="o.key" class="pd-box" :for="`pd-o-${o.key}`" :data-option="o.key" :data-locked="(o.lock || locked) || undefined">
          <Checkbox v-model="options[o.key]" :input-id="`pd-o-${o.key}`" binary :disabled="!!o.lock || locked"
                    :aria-describedby="o.lock ? `pd-o-${o.key}-why` : undefined" />
          <span>{{ t(OPTION_LABEL[o.key]) }}</span>
          <OuiHint v-if="o.lock" :id="`pd-o-${o.key}-why`" :label="t(OPTION_LABEL[o.key])" :text="lockText(o)" />
        </label>
        <label v-if="autoFeed !== null" class="pd-box pd-wide" for="pd-o-feed" data-option="auto_feed" :data-locked="locked || undefined">
          <Checkbox v-model="autoFeed" input-id="pd-o-feed" binary :disabled="locked" aria-describedby="pd-o-feed-why" />
          <span>{{ t('assist.autoFeed') }}</span>
          <OuiHint id="pd-o-feed-why" :label="t('assist.autoFeed')" :text="t('assist.autoFeed.help')" />
        </label>
      </div>
      <label class="pd-check" for="pd-remember"><Checkbox v-model="remember" input-id="pd-remember" binary :disabled="sent" data-test="remember" />{{ t('pd.remember') }}</label>
    </section>
  </main>

  <footer class="pd-bar">
    <div class="pd-bar-in">
      <span v-if="why" id="pd-why" class="pd-note" data-tone="warn">{{ why }}</span>
      <span v-if="settingsSent" class="pd-note" role="status">{{ t('pd.settingsSent') }}</span>
      <OuiStatus v-if="sent" state="busy" role="status">{{ t('pd.sending') }}</OuiStatus>
      <Button link size="small" class="pd-settings" :label="t('pd.settings')" data-test="settings" @click="openSettings">
        <template #icon><OuiIcon :icon="settingsIcon" :size="14" /></template></Button>
      <span class="pd-actions">
        <Button severity="secondary" :label="t('pd.cancel')" :disabled="sent" data-test="cancel" @click="cancel" />
        <Button :severity="choice.warnings.length ? 'warn' : undefined" :disabled="!canPrint" :aria-describedby="why ? 'pd-why' : undefined" data-test="print"
                :label="choice.warnings.length ? t('pd.printAnyway') : t('pd.print')" @click="print"><template #icon><OuiIcon :icon="play" :size="14" /></template></Button>
      </span>
    </div>
  </footer>
</template>

<style>
.pd { max-width: 720px; margin: 0 auto; padding-bottom: 112px; }
.pd-name .p-inputtext { font-weight: 600; }
/* The plate's picture on a neutral well (5.0: no block is filled with the plugin's colour). */
.pd-plate { position: relative; display: grid; place-items: center; min-height: 190px; padding: var(--oui-s6) var(--oui-s4) var(--oui-s4); border-radius: var(--oui-radius-lg); overflow: hidden;
  background: var(--oui-inset); box-shadow: inset 0 0 0 1px var(--oui-border); }
.pd-for { position: absolute; inset: var(--oui-s2) auto auto var(--oui-s3); font-size: var(--oui-text-sm); font-weight: 600; color: var(--oui-muted); }
.pd-thumb { width: min(220px, 60%); aspect-ratio: 1; object-fit: contain; }
.pd-thumb-none { opacity: .5; }
.pd-facts { position: absolute; inset: auto auto var(--oui-s2) var(--oui-s2); display: grid; gap: 2px; margin: 0; padding: 6px 10px; border-radius: var(--oui-radius);
  background: rgb(0 0 0 / .62); color: #fff; font-size: var(--oui-text-sm); }
.pd-facts > div { display: flex; align-items: center; gap: 6px; }
.pd-facts dt { display: inline-flex; }
.pd-facts dd { margin: 0; font-weight: 600; }
.pd-section { display: grid; gap: var(--oui-s2); }
.pd-chips { display: flex; flex-wrap: wrap; gap: var(--oui-s2); }
.pd-issues { display: grid; gap: 2px; margin: 0; padding: 0; list-style: none; }
.pd-note { font-size: var(--oui-text-sm); }
.pd-note[data-tone] { color: var(--oui-tone); }
.pd-note[data-tone="info"] { color: var(--oui-muted); }
.pd-head { display: flex; align-items: center; gap: var(--oui-s1); }
.pd-h { font-weight: 700; }
.pd-printer { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--oui-s2) var(--oui-s4); padding: var(--oui-s2) var(--oui-s3);
  border-radius: var(--oui-radius); background: var(--oui-surface); box-shadow: inset 0 0 0 1px var(--oui-border); }
.pd-printer-id { display: grid; gap: 2px; min-width: 0; }
.pd-ace { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 4px; color: var(--oui-muted); }
.pd-sq { width: 18px; height: 18px; border-radius: 4px; box-shadow: inset 0 0 0 1px rgb(0 0 0 / .25); }
.pd-sq[data-empty] { background: var(--oui-raised); box-shadow: inset 0 0 0 1px var(--oui-control-border); background-image: linear-gradient(135deg, transparent 45%, var(--oui-control-border) 45% 55%, transparent 55%); }
.pd-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--oui-s2); }
.pd-box { display: flex; align-items: center; gap: var(--oui-s2); min-height: 40px; padding: var(--oui-s2) var(--oui-s3); border-radius: var(--oui-radius);
  background: var(--oui-surface); box-shadow: inset 0 0 0 1px var(--oui-border); cursor: pointer; font-weight: 600; }
.pd-box:has(:checked) { box-shadow: inset 0 0 0 1.5px var(--oui-primary-mark); }
.pd-box[data-locked] { cursor: default; color: var(--oui-muted); }
/* What an option needs explained (why it is locked, what it does) is behind its (i), at the end of its box. */
.pd-box > .oui-hint { margin-inline-start: auto; }
.pd-wide { grid-column: 1 / -1; }
.pd-check { display: inline-flex; align-items: center; gap: var(--oui-s2); font-weight: 600; justify-self: start; }
.pd-bar { position: fixed; inset: auto 0 0 0; z-index: 5; background: var(--oui-surface); border-top: 1px solid var(--oui-border); box-shadow: 0 -6px 16px rgb(0 0 0 / .12); }
.pd-bar-in { display: flex; flex-wrap: wrap; gap: var(--oui-s2); align-items: center; max-width: 720px; margin: 0 auto; padding: var(--oui-s2) var(--oui-s4); }
.pd-bar-in > .pd-note { flex: 1 1 100%; }
.pd-settings.p-button { padding-inline: 0; }
.pd-actions { display: flex; gap: var(--oui-s2); margin-inline-start: auto; }
@container oui-page (max-width: 460px) {
  .pd-grid { grid-template-columns: minmax(0, 1fr); }
  .pd-plate { min-height: 160px; }
  .pd-thumb { width: min(160px, 55%); }
}
</style>
