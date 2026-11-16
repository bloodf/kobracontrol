<script setup lang="ts">
import { computed, ref } from 'vue';
import Button from 'primevue/button';
import { OuiIcon, OuiPanel } from '../../shared/src/components';
import { home as homeIcon, move as moveIcon, power } from '../../shared/src/icons';
import { s, run, tracker, controlsOff, printerName } from '../app/store';
import { ask } from '../core/dialog';
import { t, fmt } from '../core/i18n';

// Jog pad, Z, step, homing and motors off. Moves go at once; homing and motors off ask first. The printer refuses
// moves while printing (status.can.move): that reason is said once, in the panel header.
const STEPS = [0.1, 1, 10, 50];
type Axis = 'x' | 'y' | 'z';
const step = ref(10);
const moveWhy = computed(() => controlsOff.value || (s.status && !s.status.can.move ? t('reason.noMove') : ''));
const whyId = computed(() => (controlsOff.value ? 'kc-why' : moveWhy.value ? 'move-why' : undefined));
const PAD: { axis: Axis; sign: 1 | -1; area: string }[] = [
  { axis: 'y', sign: 1, area: 'kc-up' }, { axis: 'x', sign: -1, area: 'kc-left' }, { axis: 'x', sign: 1, area: 'kc-right' }, { axis: 'y', sign: -1, area: 'kc-down' }];

async function move(axis: Axis, sign: 1 | -1) {
  const distance = sign * step.value;
  await run({ key: `move:${axis}`, label: t('act.move'), cmd: 'move', args: { axis, distance }, okText: t('ok.move', { axis: axis.toUpperCase(), distance: fmt.number(distance, 1) }),
    sentText: t('sent.move') });
}
const HOME: Record<string, string> = { xy: 'home.xy', z: 'home.z', xyz: 'home.all' };
async function home(axes: 'xy' | 'z' | 'xyz') {
  const what = t(HOME[axes] as 'home.xy');
  if (!await ask({ title: t('confirm.home.title', { what }), text: t('confirm.home.text', { what, printer: printerName.value }),
    yes: t('confirm.home.yes', { what }), no: t('common.goBack') })) return;
  await run({ key: 'home', label: t('act.home'), cmd: 'home', args: { axes }, okText: t('ok.home', { what }), sentText: t('sent.home') });
}
async function motorsOff() {
  if (!await ask({ title: t('confirm.motors.title'), text: t('confirm.motors.text', { printer: printerName.value }),
    yes: t('confirm.motors.yes'), no: t('common.goBack') })) return;
  await run({ key: 'motors', label: t('act.motors'), cmd: 'motors_off', okText: t('ok.motors') });
}
const label = (axis: Axis, sign: 1 | -1) => t('motion.moveLabel', { axis: axis.toUpperCase(), distance: `${sign < 0 ? '−' : '+'}${fmt.number(step.value, 1)}` });
</script>

<template>
  <OuiPanel :title="t('motion.title')" :icon="moveIcon" tone="cobalt" data-test="move">
    <template v-if="moveWhy && !controlsOff" #meta><span id="move-why" data-test="move-why">{{ moveWhy }}</span></template>
    <div class="kc-jog">
      <div class="kc-jogpad" role="group" :aria-label="t('motion.xy')">
        <Button v-for="p in PAD" :key="p.axis + p.sign" :class="p.area" severity="secondary" size="small" :label="`${p.axis.toUpperCase()}${p.sign < 0 ? '−' : '+'}`"
                :aria-label="label(p.axis, p.sign)" :disabled="!!moveWhy || tracker.isBusy(`move:${p.axis}`)" :aria-describedby="whyId"
                :data-move="`${p.axis}${p.sign < 0 ? '-' : '+'}`" :data-focus-key="`move:${p.axis}${p.sign < 0 ? '-' : '+'}`" @click="move(p.axis, p.sign)" />
        <Button class="kc-home" severity="secondary" size="small" :aria-label="t('confirm.home.yes', { what: t('home.all') })" :title="t('confirm.home.yes', { what: t('home.all') })"
                :disabled="!!moveWhy || tracker.isBusy('home')" :aria-describedby="whyId" data-home="xyz" data-focus-key="home-xyz" @click="home('xyz')">
          <template #icon><OuiIcon :icon="homeIcon" :size="14" /></template></Button>
      </div>
      <div class="kc-z" role="group" :aria-label="t('motion.z')">
        <Button v-for="sign in [1, -1] as const" :key="sign" severity="secondary" size="small" :label="`Z${sign < 0 ? '−' : '+'}`" :aria-label="label('z', sign)"
                :disabled="!!moveWhy || tracker.isBusy('move:z')" :aria-describedby="whyId" :data-move="`z${sign < 0 ? '-' : '+'}`" :data-focus-key="`move:z${sign < 0 ? '-' : '+'}`"
                :class="sign < 0 ? 'kc-z-down' : 'kc-z-up'" @click="move('z', sign)" />
      </div>
      <div class="kc-jog-side">
        <div class="kc-step" role="group" :aria-label="t('motion.step')">
          <span class="oui-label">{{ t('motion.step') }}</span>
          <span class="kc-seg">
            <Button v-for="n in STEPS" :key="n" size="small" :severity="step === n ? undefined : 'secondary'" :text="step !== n" :aria-pressed="step === n"
                    :label="fmt.number(n, n < 1 ? 1 : 0)" :aria-label="`${fmt.number(n, n < 1 ? 1 : 0)} mm`" :data-step="n" :disabled="!!controlsOff" @click="step = n" />
          </span>
          <span class="oui-meta">mm</span>
        </div>
        <div class="oui-row">
          <Button severity="secondary" size="small" :label="t('home.xyShort')" :aria-label="t('confirm.home.yes', { what: t('home.xy') })" :disabled="!!moveWhy || tracker.isBusy('home')" :aria-describedby="whyId"
                  data-home="xy" data-focus-key="home-xy" @click="home('xy')"><template #icon><OuiIcon :icon="homeIcon" :size="14" /></template></Button>
          <Button severity="secondary" size="small" :label="t('home.zShort')" :aria-label="t('confirm.home.yes', { what: t('home.z') })" :disabled="!!moveWhy || tracker.isBusy('home')" :aria-describedby="whyId"
                  data-home="z" data-focus-key="home-z" @click="home('z')"><template #icon><OuiIcon :icon="homeIcon" :size="14" /></template></Button>
          <Button severity="secondary" text size="small" :label="t('motion.motorsOff')" :disabled="!!moveWhy || tracker.isBusy('motors')" :aria-describedby="whyId"
                  data-test="motors-off" data-focus-key="motors" @click="motorsOff"><template #icon><OuiIcon :icon="power" :size="14" /></template></Button>
        </div>
      </div>
    </div>
  </OuiPanel>
</template>

<style>
.kc-jog { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oui-s4) var(--oui-s6); }
.kc-jogpad { display: grid; grid-template: repeat(3, 28px) / repeat(3, 44px); gap: 4px; }
.kc-jogpad > .p-button, .kc-z > .p-button { min-width: 0; padding-inline: 0; }
.kc-up { grid-area: 1 / 2; } .kc-left { grid-area: 2 / 1; } .kc-home { grid-area: 2 / 2; } .kc-right { grid-area: 2 / 3; } .kc-down { grid-area: 3 / 2; }
.kc-z { display: grid; gap: 4px; grid-template-columns: 44px; }
.kc-jog-side { display: grid; gap: var(--oui-s3); }
.kc-step { display: flex; flex-wrap: wrap; align-items: center; gap: var(--oui-s2); }
.kc-seg { display: inline-flex; gap: 2px; padding: 2px; border-radius: var(--oui-radius); background: var(--oui-inset); }
.kc-seg > .p-button { min-width: 40px; }
</style>
