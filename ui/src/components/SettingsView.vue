<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Select from 'primevue/select';
import ToggleSwitch from 'primevue/toggleswitch';
import { OuiEmpty, OuiFormRow, OuiFormSection, OuiIcon, OuiKeyValue, OuiRequirement, OuiSettings, OuiStatus, type OuiSettingsSection } from '../../shared/src/components';
import { camera, info, languages, link as linkIcon, printer, refresh, save as saveIcon, search, shieldCheck, spoolman, wrench } from '../../shared/src/icons';
import { UI_VERSION } from '../../shared/src';
import CertFinder from './CertFinder.vue';
import * as bridge from '../core/bridge';
import { message } from '../core/tracker';
import { s, controlsOff, link, tracker, loadSpools, searchAgain, otherAgent, stockVisible, toast } from '../app/store';
import { config, form, changed, dirty, saving, save, discard } from '../app/settings';
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
const smInfo = computed(() => s.spoolsError || (s.spoolsLoaded ? t('sm.count', { n: s.spools.length }) : t('sm.notLoaded')));
// What Kobra Control needs on this computer. "Check again" asks the plugin to look for the certificate, ffmpeg and
// Spooler now (it answers with a fresh config); for Spoolman it loads the spools again.
type Need = 'found' | 'missing' | 'checking' | 'unknown';
const looking = ref(false);
async function checkAgain() {
  if (looking.value) return;
  looking.value = true;
  try { await Promise.race([bridge.request({ type: 'check' }), new Promise(r => setTimeout(r, 10000))]); }
  catch (e) { toast('error', t('msg.plugin', { error: message(e) })); }
  finally { looking.value = false; }
}
const NEED_LABEL = { found: 'req.found', missing: 'req.missing', checking: 'req.checking', unknown: 'req.unknown' } as const;
const needLabel = (st: Need) => t(NEED_LABEL[st]);
const certNeed = computed<Need>(() => (looking.value ? 'checking' : !cert.value ? 'unknown' : cert.value.found ? 'found' : 'missing'));
const ffmpeg = computed(() => config.value?.ffmpeg);
const ffmpegNeed = computed<Need>(() => (looking.value ? 'checking' : ffmpeg.value == null ? 'unknown' : ffmpeg.value ? 'found' : 'missing'));
const smNeed = computed<Need>(() => (tracker.isBusy('spools') ? 'checking' : s.spoolsError ? 'missing' : s.spoolsLoaded ? 'found' : 'unknown'));
const FFMPEG_URL = 'https://ffmpeg.org/download.html', SPOOLMAN_URL = 'https://github.com/Donkie/Spoolman';
const smBusy = computed(() => tracker.isBusy('spools') || !!controlsOff.value);
const smWhere = computed(() => s.located?.spoolman_url || config.value?.settings.spoolman_url || '');
const smDetail = computed(() => (s.spoolsError || [smWhere.value, s.spoolsLoaded ? t('sm.count', { n: s.spools.length }) : ''].filter(Boolean).join(' · ')));
const spooler = computed(() => config.value?.spooler ?? null);
const spoolerNeed = computed<Need>(() => (looking.value ? 'checking' : !spooler.value ? 'unknown' : spooler.value.installed ? 'found' : 'missing'));
const langOptions = computed(() => [
  { value: 'auto', label: t('lang.auto', { current: t(`lang.${autoLocale.value}`) }) },
  ...LOCALES.map(value => ({ value, label: t(`lang.${value}`) }))]);
const sections = computed<OuiSettingsSection[]>(() => [
  { id: 'conn-h', label: t('conn.title'), icon: linkIcon },
  { id: 'cert-h', label: t('cert.section'), icon: shieldCheck, ...(cert.value && !cert.value.found ? { state: 'warn' as const } : {}) },
  { id: 'print-h', label: t('printdef.title'), icon: printer },
  { id: 'cam-s-h', label: t('camset.title'), icon: camera, ...(s.camReason === 'no_ffmpeg' ? { state: 'warn' as const } : {}) },
  { id: 'sm-s-h', label: t('sm.title'), icon: spoolman },
  { id: 'needs-h', label: t('req.tab'), icon: wrench, ...(certNeed.value === 'missing' || ffmpegNeed.value === 'missing' ? { state: 'warn' as const } : {}) },
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
          <template v-if="s.camReason === 'no_ffmpeg'" #status><OuiStatus state="warn">{{ t('camset.noFfmpeg') }}</OuiStatus></template>
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
            <Button severity="secondary" size="small" :label="t('sm.refresh')" :disabled="!!controlsOff" :aria-describedby="controlsOff ? 'kc-why' : undefined"
                    :loading="tracker.isBusy('spools')" @click="loadSpools(false)"><template #icon><OuiIcon :icon="refresh" :size="14" /></template></Button>
          </OuiFormRow>
        </OuiFormSection>

        <OuiFormSection id="needs-h" :icon="wrench" tone="sky" :title="t('req.title')" :description="t('req.help')">
          <div class="sv-needs" data-test="requirements">
            <OuiRequirement :name="t('req.cert.name')" :why="t('req.cert.why')" :status="certNeed" :status-label="needLabel(certNeed)" :detail="cert?.found ? certText : undefined"
                            :install-text="t('req.cert.install')" :check-label="t('req.check')" :checking="looking" data-need="cert" @check="checkAgain" />
            <OuiRequirement name="ffmpeg" :why="t('req.ffmpeg.why')" :status="ffmpegNeed" :status-label="needLabel(ffmpegNeed)" :detail="ffmpeg || undefined"
                            :install-text="t('req.ffmpeg.install')" :install-url="FFMPEG_URL" install-label="ffmpeg.org"
                            :check-label="t('req.check')" :checking="looking" data-need="ffmpeg" @check="checkAgain" />
            <OuiRequirement name="Spoolman" :why="t('req.sm.why')" :status="smNeed" :status-label="needLabel(smNeed)" :detail="smDetail || undefined"
                            :install-text="t('req.sm.install')" :install-url="SPOOLMAN_URL" install-label="Spoolman"
                            :check-label="t('req.check')" :checking="smBusy" data-need="spoolman" @check="loadSpools(false)" />
            <OuiRequirement :name="t('spooler.title')" :why="t('req.spooler.why')" :status="spoolerNeed" :status-label="needLabel(spoolerNeed)"
                            :detail="spooler?.installed ? t('spooler.installed') : undefined" :install-text="t('spooler.suggest')" :install-url="spooler?.url"
                            :check-label="t('req.check')" :checking="looking" data-need="spooler" @check="checkAgain" />
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
