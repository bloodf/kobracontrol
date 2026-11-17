<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Select from 'primevue/select';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiEmpty, OuiFormRow, OuiFormSection, OuiIcon, OuiKeyValue, OuiRequirement, OuiSettings, OuiStatus, type OuiSettingsSection } from '../../shared/src/components';
import { camera, info, languages, link as linkIcon, printer, refresh, save as saveIcon, search, shieldCheck, spoolman, wrench } from '../../shared/src/icons';
import { UI_VERSION } from '../../shared/src';
import CertFinder from './CertFinder.vue';
import { s, controlsOff, link, tracker, loadSpools, searchAgain, otherAgent, stockVisible, noFfmpeg, requirement, checkRequirements } from '../app/store';
import { config, form, changed, dirty, saving, save, discard, spoolmanSet } from '../app/settings';
import type { Requirement, RequirementId } from '../app/types';
import type { MessageKey } from '../core/messages';
import { t, fmt, langPref, setLangPref, autoLocale } from '../core/i18n';
import { playable } from '../core/player';
import { LOCALES } from '../core/i18n-core';
import type { LangPref } from '../core/i18n-core';
import { boot } from '../core/boot';
import { fingerprintText } from '../core/logic';

const cert = computed(() => s.certificate ?? config.value?.certificate ?? null);
const certText = computed(() => (!cert.value ? t('cert.unknown') : !cert.value.found ? t('cert.missing')
  : cert.value.source === 'saved' ? t('cert.saved') : t('cert.builtIn')));
// The address in use and how it was found; a blank "Printer address" means "find it by itself".
const inUse = computed(() => (s.info?.address ? t('conn.inUse', { address: s.info.address, how: t(`conn.source.${s.info.source || 'override'}`) }) : ''));
const smFrom = computed(() => (s.located?.spoolman_source === 'spooler' && !form.spoolman ? t('conn.smFromSpooler', { url: s.located.spoolman_url }) : ''));
const smInfo = computed(() => (!spoolmanSet.value ? t('sm.notConfigured') : s.spoolsError || (s.spoolsLoaded ? t('sm.count', { n: s.spools.length }) : t('sm.notLoaded'))));
const smWhy = computed(() => controlsOff.value || (spoolmanSet.value ? '' : t('sm.notConfigured')));
// Settings > Requirements: one row per item of the plugin's `requirements` message (src/kobracontrol/requirements.py).
// "Check again" asks the plugin to look at all of them again; for Spoolman it also loads the spools again.
type Need = 'found' | 'missing' | 'checking' | 'unknown';
interface Row { name: string | MessageKey; why: MessageKey; ok: MessageKey; missing: MessageKey; how: MessageKey[]; url?: string; label?: string; fileCheck?: boolean }
const ROWS: Record<RequirementId, Row> = {
  certificate: { name: 'req.cert.name', why: 'req.cert.why', ok: 'req.found', missing: 'req.missing', how: ['req.cert.install'] },
  ffmpeg: { name: 'ffmpeg', why: 'req.ffmpeg.why', ok: 'req.found', missing: 'req.missing', fileCheck: true,
    how: ['req.ffmpeg.mac', 'req.ffmpeg.win', 'req.ffmpeg.linux', 'req.ffmpeg.path'], url: 'https://ffmpeg.org/download.html', label: 'ffmpeg.org' },
  anycubic_slicer: { name: 'Anycubic Slicer Next', why: 'req.slicer.why', ok: 'req.slicer.ok', missing: 'req.slicer.missing', fileCheck: true,
    how: ['req.slicer.mac', 'req.slicer.win', 'req.slicer.linux'], url: 'https://www.anycubic.com/pages/anycubic-slicer', label: 'anycubic.com' },
  printer_agents: { name: 'req.agents.name', why: 'req.agents.why', ok: 'req.agents.ok', missing: 'req.agents.unknown', how: ['req.agents.step1', 'req.agents.step2', 'req.agents.note'] },
  spoolman: { name: 'Spoolman', why: 'req.spoolman.why', ok: 'req.spoolman.ok', missing: 'req.spoolman.missing', how: ['req.spoolman.how'],
    url: 'https://github.com/Donkie/Spoolman', label: 'Spoolman' },
  spooler: { name: 'spooler.title', why: 'req.spooler.why', ok: 'req.found', missing: 'req.missing', how: ['spooler.suggest'] },
};
const ORDER: RequirementId[] = ['certificate', 'ffmpeg', 'anycubic_slicer', 'printer_agents', 'spoolman', 'spooler'];
const items = computed(() => ORDER.map(id => requirement(id)).filter((r): r is Requirement => !!r));
const isKey = (k: string): k is MessageKey => k.includes('.');   // else a product name, the same in every language
// "unknown" is "not checked yet" (no warning); a re-check shows "Checking…" on the rows it looks at again.
const need = (r: Requirement): Need => (s.checking && ROWS[r.id].fileCheck ? 'checking' : r.state === 'ok' ? 'found' : r.state);
const needLabel = (r: Requirement) => {
  const n = need(r), row = ROWS[r.id];
  // ffmpeg is optional only where the page plays the camera itself ('Not installed (optional)')
  const missing = r.id === 'ffmpeg' && playable() ? 'req.slicer.missing' : row.missing;
  return t(n === 'checking' ? 'req.checking' : n === 'unknown' ? 'req.unknown' : n === 'found' ? row.ok : missing);
};
const smDetail = computed(() => [requirement('spoolman')?.details, s.spoolsError || (s.spoolsLoaded ? t('sm.count', { n: s.spools.length }) : '')].filter(Boolean).join(' · '));
const detail = (r: Requirement) => (r.state !== 'ok' ? undefined : r.id === 'certificate' ? certText.value : r.id === 'spooler' ? t('spooler.installed')
  : r.id === 'spoolman' ? smDetail.value || undefined : r.details || undefined);
const spooler = computed(() => config.value?.spooler ?? null);
const rowUrl = (r: Requirement) => (r.id === 'spooler' ? spooler.value?.url : ROWS[r.id].url);
function checkAgain(r: Requirement) {
  checkRequirements();
  if (r.id === 'spoolman' && spoolmanSet.value && !controlsOff.value) void loadSpools(false);
}
// What the camera, the connection or OrcaSlicer's own Print/Device tab need is missing (optional ones never warn).
const reqWarn = computed(() => !s.checking && (noFfmpeg.value || ['certificate', 'printer_agents'].some(id => requirement(id as RequirementId)?.state === 'missing')));
const langOptions = computed(() => [
  { value: 'auto', label: t('lang.auto', { current: t(`lang.${autoLocale.value}`) }) },
  ...LOCALES.map(value => ({ value, label: t(`lang.${value}`) }))]);
const sections = computed<OuiSettingsSection[]>(() => [
  { id: 'conn-h', label: t('conn.title'), icon: linkIcon },
  { id: 'cert-h', label: t('cert.section'), icon: shieldCheck, ...(cert.value && !cert.value.found ? { state: 'warn' as const } : {}) },
  { id: 'print-h', label: t('printdef.title'), icon: printer },
  { id: 'cam-s-h', label: t('camset.title'), icon: camera, ...(s.camReason === 'no_ffmpeg' || noFfmpeg.value ? { state: 'warn' as const } : {}) },
  { id: 'sm-s-h', label: t('sm.title'), icon: spoolman },
  { id: 'needs-h', label: t('req.tab'), icon: wrench, ...(reqWarn.value ? { state: 'warn' as const } : {}) },
  { id: 'lang-h', label: t('lang.title'), icon: languages },
  { id: 'about-h', label: t('about.title'), icon: info },
]);
// The save bar names what is not saved yet.
const FIELD: Record<string, string> = { host: 'conn.host', printer_name: 'conn.name', ffmpeg_path: 'camset.ffmpeg', camera_enabled: 'camset.default',
  auto_leveling: 'files.autoLeveling', vibration_compensation: 'files.vibration', flow_calibration: 'files.flow', timelapse: 'files.timelapse', spoolman_url: 'conn.sm', spoolman_auto: 'sm.auto', spoolman_report_usage: 'sm.usage' };
const changedText = computed(() => fmt.list(changed.value.map(k => t(FIELD[k] as 'conn.host'))));
const about = computed(() => [{ label: t('about.kit'), value: UI_VERSION }]);
// Enter in a text field saves, as the form's own button did.
function onEnter(e: KeyboardEvent) { if (e.target instanceof HTMLInputElement && e.target.type !== 'checkbox') { e.preventDefault(); void save(); } }
</script>

<template>
  <div class="sv">
    <OuiSettings :sections="sections" :nav-label="t('settings.nav')">
      <div class="oui-stack">
        <OuiFormSection id="conn-h" :icon="linkIcon" tone="cobalt" :title="t('conn.title')" :description="t('conn.help')">
          <template v-if="link === 'connected'" #status><OuiStatus state="ok">{{ t('conn.answering') }}</OuiStatus></template>
          <OuiEmpty v-if="!config" compact state="loading" :title="t('settings.notLoaded')" />
          <form class="oui-formsection-rows" @submit.prevent="save" @keydown.enter="onEnter">
            <OuiFormRow :label="t('conn.name')" for="c-name" :hint="t('conn.nameHelp')"><InputText id="c-name" v-model="form.name" /></OuiFormRow>
            <OuiFormRow :label="t('conn.host')" for="c-host" :hint="t('conn.hostHelp')">
              <InputText id="c-host" v-model="form.host" class="oui-mono" :placeholder="t('conn.hostPh')" />
            </OuiFormRow>
            <OuiFormRow :label="t('conn.inUseLabel')">
              <span v-if="inUse" class="oui-meta sv-inuse" data-test="in-use" role="status">{{ inUse }}</span><span v-else class="oui-muted">—</span>
              <Button size="small" severity="secondary" :label="t('settings.searchAgain')" :loading="tracker.isBusy('search')" :disabled="!!form.host"
                      data-test="search-again-settings" @click="searchAgain()"><template #icon><OuiIcon :icon="search" :size="14" /></template></Button>
            </OuiFormRow>
          </form>
          <div v-if="otherAgent || s.status?.tls" class="oui-stack sv-notes">
            <p v-if="otherAgent" class="oui-meta" data-test="other-agent">{{ t('agent.other', { agent: otherAgent }) }}</p>
            <template v-if="s.status?.tls">
              <p class="oui-meta oui-mono sv-fp" data-test="tls-fp">{{ t('tls.fingerprint', { fp: fingerprintText(s.status.tls.fingerprint) }) }}
                <template v-if="s.status.tls.changed_from"><br>{{ t('tls.previous', { fp: fingerprintText(s.status.tls.changed_from) }) }}</template></p>
              <p class="oui-meta">{{ t('tls.help') }}</p>
            </template>
          </div>
        </OuiFormSection>

        <OuiFormSection id="cert-h" :icon="shieldCheck" tone="teal" :title="t('cert.section')" :description="t('cert.why')">
          <template #status><OuiStatus :state="!cert ? 'pending' : cert.found ? 'ok' : 'warn'">{{ !cert ? t('cert.chip.unknown') : cert.found ? t('cert.chip.ok') : t('cert.chip.missing') }}</OuiStatus></template>
          <OuiFormRow :label="t('cert.source')"><span data-test="cert-status" role="status">{{ certText }}</span></OuiFormRow>
          <!-- Only for a firmware that stops taking the built-in copy: the one action that reads Anycubic Slicer Next. -->
          <details class="kc-disclose sv-adv" data-test="cert-advanced">
            <summary>{{ t('cert.advanced') }}</summary>
            <p class="oui-meta">{{ t('cert.advancedHelp') }}</p>
            <CertFinder id-prefix="set" />
          </details>
        </OuiFormSection>

        <OuiFormSection id="print-h" :icon="printer" :title="t('printdef.title')" :description="t('printdef.help')">
          <OuiFormRow :label="t('files.autoLeveling')" for="c-level" :hint="t('printdef.levelingHint')"><ToggleSwitch v-model="form.leveling" input-id="c-level" data-test="def-leveling" /></OuiFormRow>
          <OuiFormRow :label="t('files.vibration')" for="c-vib" :hint="t('printdef.vibrationHint')"><ToggleSwitch v-model="form.vibration" input-id="c-vib" data-test="def-vibration" /></OuiFormRow>
          <OuiFormRow :label="t('files.flow')" for="c-flow" :hint="t('printdef.untestedHint')"><ToggleSwitch v-model="form.flow" input-id="c-flow" data-test="def-flow" /></OuiFormRow>
          <OuiFormRow :label="t('files.timelapse')" for="c-tl" :hint="t('printdef.untestedHint')"><ToggleSwitch v-model="form.timelapse" input-id="c-tl" data-test="def-timelapse" /></OuiFormRow>
        </OuiFormSection>
      </div>

      <div class="oui-stack">
        <OuiFormSection id="cam-s-h" :icon="camera" tone="sky" :title="t('camset.title')">
          <template v-if="s.camReason === 'no_ffmpeg' || noFfmpeg" #status><OuiStatus state="warn">{{ t('camset.noFfmpeg') }}</OuiStatus></template>
          <OuiFormRow :label="t('camset.default')" for="c-cam"><ToggleSwitch v-model="form.camera" input-id="c-cam" data-test="cam-default" /></OuiFormRow>
          <OuiFormRow :label="t('camset.ffmpeg')" for="c-ffmpeg" :hint="t('camset.ffmpegHelp')">
            <InputText id="c-ffmpeg" v-model="form.ffmpeg" class="oui-mono" :placeholder="t('camset.ffmpegPh')" @keydown.enter="onEnter" />
          </OuiFormRow>
        </OuiFormSection>

        <OuiFormSection id="sm-s-h" :icon="spoolman" tone="magenta" :title="t('sm.title')" :description="t('sm.sectionHelp')">
          <OuiFormRow :label="t('conn.sm')" for="c-sm">
            <InputText id="c-sm" v-model="form.spoolman" class="oui-mono" :placeholder="t('conn.smPh')" aria-describedby="c-sm-help" @keydown.enter="onEnter" />
            <p id="c-sm-help" class="oui-meta sv-hint" data-test="sm-from">{{ smFrom || t('conn.smHelp') }}</p>
          </OuiFormRow>
          <OuiFormRow :label="t('sm.auto')" for="c-sm-auto"><ToggleSwitch v-model="form.spoolmanAuto" input-id="c-sm-auto" /></OuiFormRow>
          <OuiFormRow :label="t('sm.usage')" for="c-sm-usage"><ToggleSwitch v-model="form.usage" input-id="c-sm-usage" /></OuiFormRow>
          <OuiFormRow :label="t('sm.spools')">
            <span class="oui-muted" role="status">{{ smInfo }}</span>
            <Button severity="secondary" size="small" :label="t('sm.refresh')" :disabled="!!smWhy" :title="smWhy || undefined" :aria-describedby="controlsOff ? 'kc-why' : undefined"
                    :loading="tracker.isBusy('spools')" @click="loadSpools(false)"><template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
          </OuiFormRow>
        </OuiFormSection>

        <OuiFormSection id="needs-h" :icon="wrench" tone="sky" :title="t('req.title')" :description="t('req.help')">
          <div class="sv-needs" data-test="requirements" aria-live="polite">
            <OuiRequirement v-for="r in items" :key="r.id" :name="isKey(ROWS[r.id].name) ? t(ROWS[r.id].name as MessageKey) : ROWS[r.id].name" :why="t(ROWS[r.id].why)"
                            :status="need(r)" :status-label="needLabel(r)" :detail="detail(r)" :install-text="ROWS[r.id].how.map(k => t(k)).join(' · ')"
                            :install-url="rowUrl(r)" :install-label="ROWS[r.id].label" :check-label="t('req.check')"
                            :checking="s.checking || (r.id === 'spoolman' && tracker.isBusy('spools'))" :data-need="r.id" @check="checkAgain(r)" />
            <p v-if="!items.length" class="oui-meta kc-pad">{{ t('req.checking') }}</p>
          </div>
          <p v-if="spooler?.installed && !stockVisible" class="oui-meta kc-pad" data-test="spooler-no-stock">{{ t('spooler.noStock') }}</p>
        </OuiFormSection>

        <OuiFormSection id="lang-h" :icon="languages" tone="neutral" :title="t('lang.title')">
          <OuiFormRow :label="t('lang.label')" :hint="t('lang.help')">
            <Select :model-value="langPref" :options="langOptions" option-label="label" option-value="value" :aria-label="t('lang.label')" data-test="lang"
                    @update:model-value="setLangPref($event as LangPref)" />
          </OuiFormRow>
        </OuiFormSection>

        <OuiFormSection id="about-h" :icon="info" tone="neutral" :title="t('about.title')">
          <div class="kc-pad oui-stack">
            <OuiKeyValue :items="about" />
            <p class="oui-meta" data-test="version">{{ t('about.text', { version: config?.version || boot.version }) }}</p>
          </div>
        </OuiFormSection>
      </div>

      <template #footer>
        <template v-if="dirty"><OuiStatus state="pending" role="status">{{ t('settings.unsaved') }}</OuiStatus><span class="oui-meta oui-truncate">{{ changedText }}</span></template>
        <span class="oui-spacer" />
        <Button severity="secondary" text :label="t('settings.discard')" :disabled="!dirty || saving" data-test="discard" @click="discard" />
        <Button :label="saving ? t('settings.saving') : t('settings.save')" :loading="saving" :disabled="!config" data-test="save-top" @click="save">
          <template #icon><OuiIcon :icon="saveIcon" :size="14" /></template></Button>
      </template>
    </OuiSettings>
  </div>
</template>

<style>
.sv-hint { flex: 1 0 100%; text-align: end; }
.sv-inuse { margin-inline-end: auto; }
.sv-notes { padding: 0 var(--oui-s4) var(--oui-s3); }
.sv-fp { overflow-wrap: anywhere; }
.sv-needs > * + * { border-top: 1px solid var(--oui-border); }
.sv-adv { padding: var(--oui-s3) var(--oui-s4); border-top: 1px solid var(--oui-border); }
</style>
