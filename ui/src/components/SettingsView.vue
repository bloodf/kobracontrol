<script setup lang="ts">
import { computed } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Select from 'primevue/select';
import Checkbox from 'primevue/checkbox';
import Icon from './Icon.vue';
import CertFinder from './CertFinder.vue';
import SpoolerHint from './SpoolerHint.vue';
import { s, controlsOff, tracker, loadSpools, searchAgain, otherAgent } from '../app/store';
import { config, form, dirty, saving, save } from '../app/settings';
import { t, langPref, setLangPref, autoLocale } from '../core/i18n';
import type { LangPref } from '../core/i18n-core';
import { boot } from '../core/boot';
import { fingerprintText } from '../core/logic';

const cert = computed(() => s.certificate ?? config.value?.certificate ?? null);
const certText = computed(() => (!cert.value ? t('cert.unknown') : !cert.value.found ? t('cert.missing')
  : cert.value.source === 'saved' ? t('cert.saved') : t('cert.builtIn')));
// The address in use and how it was found; blank "Printer address" means "find it by itself".
const inUse = computed(() => (s.info?.address ? t('conn.inUse', { address: s.info.address, how: t(`conn.source.${s.info.source || 'override'}`) }) : ''));
const smFrom = computed(() => (s.located?.spoolman_source === 'spooler' && !form.spoolman ? t('conn.smFromSpooler', { url: s.located.spoolman_url }) : ''));
const smInfo = computed(() => s.spoolsError || (s.spoolsLoaded ? t('sm.count', { n: s.spools.length }) : t('sm.notLoaded')));
const langOptions = computed(() => [
  { value: 'auto', label: t('lang.auto', { current: t(`lang.${autoLocale.value}`) }) },
  { value: 'en', label: t('lang.en') }, { value: 'pt-BR', label: t('lang.pt-BR') }]);
</script>

<template>
  <div class="sv">
    <section class="kc-card" aria-labelledby="save-h">
      <div class="kc-row">
        <h2 id="save-h" class="sv-h">{{ t('settings.title') }}</h2><span class="kc-spacer" />
        <span v-if="dirty" class="kc-warn" role="status">{{ t('settings.unsaved') }}</span>
        <Button :label="saving ? t('settings.saving') : t('common.save')" :loading="saving" :disabled="!config" data-test="save-top" @click="save" />
      </div>
      <p v-if="!config" class="oui-muted">{{ t('settings.notLoaded') }}</p>
    </section>

    <section class="kc-card" aria-labelledby="conn-h">
      <h2 id="conn-h">{{ t('conn.title') }}</h2>
      <form class="sv-conn" @submit.prevent="save">
        <label for="c-host">{{ t('conn.host') }}</label>
        <span class="sv-field"><InputText id="c-host" v-model="form.host" :placeholder="t('conn.hostPh')" aria-describedby="c-host-help" />
          <span id="c-host-help" class="oui-meta">{{ t('conn.hostHelp') }}</span>
          <span class="kc-row"><span v-if="inUse" class="oui-meta" data-test="in-use" role="status">{{ inUse }}</span><span class="kc-spacer" />
            <Button size="small" severity="secondary" outlined :label="t('settings.searchAgain')" :loading="tracker.isBusy('search')"
                    :disabled="!!form.host" data-test="search-again-settings" @click="searchAgain()" /></span>
          <span v-if="otherAgent" class="oui-meta" data-test="other-agent">{{ t('agent.other', { agent: otherAgent }) }}</span></span>
        <label for="c-name">{{ t('conn.name') }}</label>
        <span class="sv-field"><InputText id="c-name" v-model="form.name" aria-describedby="c-name-help" />
          <span id="c-name-help" class="oui-meta">{{ t('conn.nameHelp') }}</span></span>
      </form>
      <template v-if="s.status?.tls">
        <p class="oui-meta sv-fp" data-test="tls-fp">{{ t('tls.fingerprint', { fp: fingerprintText(s.status.tls.fingerprint) }) }}
          <template v-if="s.status.tls.changed_from"><br>{{ t('tls.previous', { fp: fingerprintText(s.status.tls.changed_from) }) }}</template></p>
        <p class="oui-meta">{{ t('tls.help') }}</p>
      </template>
    </section>

    <section class="kc-card" aria-labelledby="cert-h">
      <h2 id="cert-h"><Icon name="icon/certificate" /> {{ t('cert.title') }}</h2>
      <p data-test="cert-status" role="status" :class="{ 'kc-warn': cert && !cert.found }">{{ certText }}</p>
      <p class="oui-meta">{{ t('cert.why') }}</p>
      <!-- Only for a firmware that stops taking the built-in copy: the one action that reads Anycubic Slicer Next. -->
      <details class="sv-adv" data-test="cert-advanced">
        <summary>{{ t('cert.advanced') }}</summary>
        <p class="oui-meta">{{ t('cert.advancedHelp') }}</p>
        <CertFinder id-prefix="set" />
      </details>
    </section>

    <section class="kc-card" aria-labelledby="cam-s-h">
      <h2 id="cam-s-h"><Icon name="icon/camera" /> {{ t('camset.title') }}</h2>
      <div class="sv-conn">
        <label for="c-ffmpeg">{{ t('camset.ffmpeg') }}</label>
        <span class="sv-field"><InputText id="c-ffmpeg" v-model="form.ffmpeg" :placeholder="t('camset.ffmpegPh')" aria-describedby="c-ffmpeg-help" />
          <span id="c-ffmpeg-help" class="oui-meta">{{ t('camset.ffmpegHelp') }}</span></span>
        <span /><span class="kc-row"><Checkbox v-model="form.camera" binary input-id="c-cam" data-test="cam-default" /><label for="c-cam">{{ t('camset.default') }}</label></span>
      </div>
    </section>

    <section class="kc-card" aria-labelledby="pd-h">
      <h2 id="pd-h">{{ t('printdef.title') }}</h2>
      <p class="oui-meta">{{ t('printdef.help') }}</p>
      <div class="sv-prefs">
        <span class="kc-row"><Checkbox v-model="form.leveling" binary input-id="c-level" data-test="def-leveling" /><label for="c-level">{{ t('files.autoLeveling') }}</label></span>
        <span class="kc-row"><Checkbox v-model="form.vibration" binary input-id="c-vib" data-test="def-vibration" /><label for="c-vib">{{ t('files.vibration') }}</label></span>
      </div>
    </section>

    <section class="kc-card" aria-labelledby="sm-s-h">
      <h2 id="sm-s-h"><Icon name="icon/spoolman" /> {{ t('sm.title') }}</h2>
      <div class="sv-conn">
        <label for="c-sm">{{ t('conn.sm') }}</label>
        <span class="sv-field"><InputText id="c-sm" v-model="form.spoolman" :placeholder="t('conn.smPh')" aria-describedby="c-sm-help" />
          <span id="c-sm-help" class="oui-meta" data-test="sm-from">{{ smFrom || t('conn.smHelp') }}</span></span>
        <span /><span class="kc-row"><Checkbox v-model="form.spoolmanAuto" binary input-id="c-sm-auto" /><label for="c-sm-auto">{{ t('sm.auto') }}</label></span>
        <span /><span class="kc-row"><Checkbox v-model="form.usage" binary input-id="c-sm-usage" /><label for="c-sm-usage">{{ t('sm.usage') }}</label></span>
      </div>
      <div class="kc-row"><span class="oui-muted" role="status">{{ smInfo }}</span><span class="kc-spacer" />
        <Button severity="secondary" outlined :disabled="!!controlsOff" :loading="tracker.isBusy('spools')" @click="loadSpools(false)">
          <Icon name="icon/spoolman" /><span>{{ t('sm.refresh') }}</span></Button></div>
    </section>

    <SpoolerHint where="settings" />

    <section class="kc-card" aria-labelledby="lang-h">
      <h2 id="lang-h">{{ t('lang.title') }}</h2>
      <div class="kc-row"><label id="lang-l">{{ t('lang.label') }}</label>
        <Select :model-value="langPref" :options="langOptions" option-label="label" option-value="value" aria-labelledby="lang-l" data-test="lang"
                @update:model-value="setLangPref($event as LangPref)" /></div>
      <p class="oui-meta">{{ t('lang.help') }}</p>
      <p class="oui-meta" data-test="version">{{ t('about.text', { version: config?.version || boot.version }) }}</p>
    </section>
  </div>
</template>

<style scoped>
.sv { display: grid; gap: 16px; max-width: 1000px; }
.sv-h { margin: 0; }
.sv-fp { overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.sv-prefs { display: flex; flex-wrap: wrap; gap: 8px 20px; }
.sv-conn { display: grid; grid-template-columns: minmax(160px, 220px) minmax(0, 1fr); gap: 12px; align-items: start; margin-bottom: 8px; }
.sv-conn > label { padding-top: 8px; }
.sv-field { display: grid; gap: 4px; }
.sv-adv { margin-top: 8px; }
.sv-adv > summary { cursor: pointer; color: var(--oui-muted); }
@media (max-width: 640px) { .sv-conn { grid-template-columns: minmax(0, 1fr); } .sv-conn > label { padding-top: 0; } }
</style>
