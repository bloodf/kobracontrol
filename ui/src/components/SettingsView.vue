<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Select from 'primevue/select';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiEmpty, OuiFormRow, OuiFormSection, OuiIcon, OuiKeyValue, OuiSettings, OuiStatus, type OuiSettingsSection } from '../../shared/src/components';
import { camera, info, languages, link as linkIcon, printer, refresh, save as saveIcon, search, shieldCheck, spoolman, wrench } from '../../shared/src/icons';
import { UI_VERSION } from '../../shared/src';
import CertFinder from './CertFinder.vue';
import SpoolerHint from './SpoolerHint.vue';
import RequirementRow from './RequirementRow.vue';
import { s, controlsOff, link, tracker, loadSpools, searchAgain, otherAgent, noFfmpeg, requirement, checkRequirements } from '../app/store';
import { config, form, changed, dirty, saving, save, discard, spoolmanSet } from '../app/settings';
import { t, fmt, langPref, setLangPref, autoLocale } from '../core/i18n';
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
// Something the camera or OrcaSlicer's own Print/Device tab needs is missing (optional ones never warn).
const reqWarn = computed(() => !s.checking && (noFfmpeg.value || requirement('printer_agents')?.state === 'unknown'));
const langOptions = computed(() => [
  { value: 'auto', label: t('lang.auto', { current: t(`lang.${autoLocale.value}`) }) },
  ...LOCALES.map(value => ({ value, label: t(`lang.${value}`) }))]);
const sections = computed<OuiSettingsSection[]>(() => [
  { id: 'conn-h', label: t('conn.title'), icon: linkIcon },
  { id: 'req-h', label: t('req.title'), icon: wrench, ...(reqWarn.value ? { state: 'warn' as const } : {}) },
  { id: 'cert-h', label: t('cert.section'), icon: shieldCheck, ...(cert.value && !cert.value.found ? { state: 'warn' as const } : {}) },
  { id: 'print-h', label: t('printdef.title'), icon: printer },
  { id: 'cam-s-h', label: t('camset.title'), icon: camera, ...(s.camReason === 'no_ffmpeg' || noFfmpeg.value ? { state: 'warn' as const } : {}) },
  { id: 'sm-s-h', label: t('sm.title'), icon: spoolman },
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

        <OuiFormSection id="req-h" :icon="wrench" tone="neutral" :title="t('req.title')" :description="t('req.help')">
          <template #status><Button size="small" severity="secondary" :label="t('req.checkAgain')" :loading="s.checking" data-test="req-check"
                                    @click="checkRequirements()"><template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button></template>
          <div data-test="requirements" aria-live="polite">
            <RequirementRow v-for="r in s.requirements" :key="r.id" :item="r" :checking="s.checking" />
            <p v-if="!s.requirements.length" class="oui-meta kc-pad">{{ t('req.checking') }}</p>
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
          <div class="kc-pad"><SpoolerHint where="settings" /></div>
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
.sv-adv { padding: var(--oui-s3) var(--oui-s4); border-top: 1px solid var(--oui-border); }
</style>
