<script setup lang="ts">
import { computed } from 'vue';
import { OuiStatus, type OuiState } from '../../shared/src/components';
import type { Requirement, RequirementId } from '../app/types';
import { t } from '../core/i18n';
import type { MessageKey } from '../core/messages';

// One row of Settings > Requirements: name, state, what needs it and how to get it. Kept apart so ui-foundation
// 4.2's OuiRequirement can replace it in one place.
const props = defineProps<{ item: Requirement; checking?: boolean }>();

interface Spec { name: MessageKey; why: MessageKey; ok: MessageKey; missing: MessageKey; how: MessageKey[]; link: string; optional: boolean }
const SPECS: Record<RequirementId, Spec> = {
  ffmpeg: { name: 'req.ffmpeg.name', why: 'req.ffmpeg.why', ok: 'req.ffmpeg.ok', missing: 'req.ffmpeg.missing',
    how: ['req.ffmpeg.mac', 'req.ffmpeg.win', 'req.ffmpeg.linux', 'req.ffmpeg.path'], link: 'https://ffmpeg.org/download.html', optional: false },
  anycubic_slicer: { name: 'req.slicer.name', why: 'req.slicer.why', ok: 'req.slicer.ok', missing: 'req.slicer.missing',
    how: ['req.slicer.mac', 'req.slicer.win', 'req.slicer.linux'], link: 'https://www.anycubic.com/pages/anycubic-slicer', optional: true },
  printer_agents: { name: 'req.agents.name', why: 'req.agents.why', ok: 'req.agents.ok', missing: 'req.agents.unknown',
    how: ['req.agents.step1', 'req.agents.step2', 'req.agents.note'], link: '', optional: false },
  spoolman: { name: 'req.spoolman.name', why: 'req.spoolman.why', ok: 'req.spoolman.ok', missing: 'req.spoolman.missing',
    how: ['req.spoolman.how'], link: 'https://github.com/Donkie/Spoolman', optional: true },
};
const spec = computed(() => SPECS[props.item.id]);
// The printer agent setting can't be read, only seen in use: "unknown" there means "not detected".
const fileCheck = computed(() => props.item.id === 'ffmpeg' || props.item.id === 'anycubic_slicer');
const pending = computed(() => fileCheck.value && (props.checking || props.item.state === 'unknown'));
const tone = computed<OuiState>(() => (pending.value ? 'pending' : props.item.state === 'ok' ? 'ok' : spec.value.optional ? 'idle' : 'warn'));
const label = computed(() => (pending.value ? t(props.checking ? 'req.checking' : 'req.unknown')
  : t(props.item.state === 'ok' ? spec.value.ok : spec.value.missing)));
</script>

<template>
  <div class="rq" :data-req="item.id" :data-state="item.state">
    <div class="rq-head"><span class="rq-name">{{ t(spec.name) }}</span><OuiStatus :state="tone" data-test="req-state">{{ label }}</OuiStatus></div>
    <p class="oui-meta">{{ t(spec.why) }}</p>
    <p v-if="item.state === 'ok' && item.details" class="oui-meta oui-mono rq-details">{{ item.details }}</p>
    <template v-if="item.state !== 'ok' && !pending">
      <ul class="rq-how oui-meta"><li v-for="k in spec.how" :key="k">{{ t(k) }}</li></ul>
      <a v-if="spec.link" class="rq-link" :href="spec.link" data-test="req-link">{{ spec.link }}</a>
    </template>
  </div>
</template>

<style>
.rq { display: grid; gap: var(--oui-s1); padding: var(--oui-s3) var(--oui-s4); border-top: 1px solid var(--oui-border); }
.rq-head { display: flex; align-items: center; justify-content: space-between; gap: var(--oui-s2); }
.rq-name { font-weight: 600; }
.rq-details, .rq-link { overflow-wrap: anywhere; }
.rq-how { margin: 0; padding-inline-start: 1.2em; }
</style>
