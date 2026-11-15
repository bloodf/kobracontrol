<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import Button from 'primevue/button';
import Checkbox from 'primevue/checkbox';
import Icon from './Icon.vue';
import { s, run, tracker, controlsOff, printing, printerName } from '../app/store';
import { ask } from '../core/dialog';
import { t, fmt } from '../core/i18n';
import { skippable } from '../core/logic';
import { message } from '../core/tracker';
import * as bridge from '../core/bridge';

const STEPS = [0.1, 1, 10, 50];
const AXES = ['x', 'y', 'z'] as const;
type Axis = (typeof AXES)[number];
const step = ref(10);
const moveWhy = computed(() => controlsOff.value || (s.status && !s.status.can.move ? t('reason.noMove') : ''));

async function move(axis: Axis, sign: 1 | -1) {
  const distance = sign * step.value;
  const label = t('act.move');
  await run({ key: `move:${axis}`, label, cmd: 'move', args: { axis, distance }, okText: t('ok.move', { axis: axis.toUpperCase(), distance: fmt.number(distance, 1) }),
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

// Object skip: the plugin's `objects` command answers for the running print when the section is opened.
const open = ref(false);
const sk = reactive({ state: 'idle' as 'idle' | 'loading' | 'ok' | 'error', objects: [] as string[], error: '' });
const chosen = ref<string[]>([]);
let seq = 0;
async function loadObjects() {
  const mine = ++seq;
  sk.state = 'loading';
  try {
    const r = await bridge.command('objects', {}, s.info?.generation);
    if (mine !== seq) return;
    sk.objects = skippable(r?.objects, r?.skipped);
    chosen.value = chosen.value.filter(n => sk.objects.includes(n));
    sk.state = 'ok';
  } catch (e) {
    if (mine !== seq) return;
    sk.error = message(e); sk.state = 'error';
  }
}
function toggle() { open.value = !open.value; if (open.value) void loadObjects(); }
const skipWhy = computed(() => controlsOff.value || (!printing.value ? t('reason.noPrint') : ''));
// A finished print or another printer closes the section: its list is no longer true.
watch(() => [printing.value, s.epoch], () => { open.value = false; seq++; sk.state = 'idle'; chosen.value = []; });
async function skip() {
  const names = chosen.value.filter(n => sk.objects.includes(n));
  if (!names.length) return;
  if (!await ask({ title: t('confirm.skip.title'), text: t('confirm.skip.text', { printer: printerName.value, names: names.join(', ') }),
    yes: t('confirm.skip.yes'), no: t('common.goBack'), danger: true })) return;
  const r = await run({ key: 'skip', label: t('act.skip'), cmd: 'skip_objects', args: { names }, okText: t('ok.skip') });
  if (r.ok) { chosen.value = []; void loadObjects(); }
}
</script>

<template>
  <div class="mp">
    <h3 class="mp-h"><Icon name="icon/move" /> {{ t('motion.title') }}</h3>
    <div class="kc-row" role="group" :aria-label="t('motion.step')">
      <span class="oui-meta">{{ t('motion.step') }}</span>
      <Button v-for="n in STEPS" :key="n" size="small" :severity="step === n ? undefined : 'secondary'" :outlined="step !== n" :aria-pressed="step === n"
              :label="`${fmt.number(n, n < 1 ? 1 : 0)} mm`" :data-step="n" :disabled="!!controlsOff" @click="step = n" />
    </div>
    <div class="mp-axes">
      <template v-for="a in AXES" :key="a">
        <strong>{{ a.toUpperCase() }}</strong>
        <Button severity="secondary" outlined size="small" :disabled="!!moveWhy || tracker.isBusy(`move:${a}`)" :data-move="`${a}-`" :data-focus-key="`move:${a}-`"
                :aria-label="t('motion.moveLabel', { axis: a.toUpperCase(), distance: `−${fmt.number(step, 1)}` })" label="−" @click="move(a, -1)" />
        <Button severity="secondary" outlined size="small" :disabled="!!moveWhy || tracker.isBusy(`move:${a}`)" :data-move="`${a}+`" :data-focus-key="`move:${a}+`"
                :aria-label="t('motion.moveLabel', { axis: a.toUpperCase(), distance: `+${fmt.number(step, 1)}` })" label="+" @click="move(a, 1)" />
      </template>
    </div>
    <div class="kc-row">
      <Button severity="secondary" outlined size="small" :disabled="!!moveWhy || tracker.isBusy('home')" data-home="xy" data-focus-key="home-xy" @click="home('xy')">
        <Icon name="icon/home" /><span>{{ t('home.xy') }}</span></Button>
      <Button severity="secondary" outlined size="small" :disabled="!!moveWhy || tracker.isBusy('home')" data-home="z" data-focus-key="home-z" @click="home('z')">
        <Icon name="icon/home" /><span>{{ t('home.z') }}</span></Button>
      <Button severity="secondary" outlined size="small" :disabled="!!moveWhy || tracker.isBusy('home')" data-home="xyz" data-focus-key="home-xyz" @click="home('xyz')">
        <Icon name="icon/home" /><span>{{ t('home.all') }}</span></Button>
      <Button severity="secondary" outlined size="small" :disabled="!!moveWhy || tracker.isBusy('motors')" data-test="motors-off" data-focus-key="motors" @click="motorsOff">
        <span>{{ t('motion.motorsOff') }}</span></Button>
    </div>
    <p v-if="moveWhy && !controlsOff" class="kc-why" data-test="move-why">{{ moveWhy }}</p>

    <h3 class="mp-h"><Icon name="icon/cancel" /> {{ t('skip.title') }}</h3>
    <div class="kc-row">
      <Button severity="secondary" outlined size="small" :label="open ? t('skip.close') : t('skip.open')" :aria-expanded="open" aria-controls="skip-body"
              :disabled="!!skipWhy" data-test="skip-open" data-focus-key="skip-open" @click="toggle" />
      <span v-if="skipWhy && !controlsOff" class="kc-why">{{ skipWhy }}</span>
    </div>
    <div v-if="open" id="skip-body" class="mp" data-test="skip-body">
      <p v-if="sk.state === 'loading'" class="oui-muted" role="status">{{ t('skip.loading') }}</p>
      <div v-else-if="sk.state === 'error'" role="alert" data-test="skip-error">
        <p class="kc-err mp-p">{{ t('skip.error', { error: sk.error }) }}</p>
        <Button size="small" severity="secondary" outlined :label="t('common.retry')" data-test="skip-retry" @click="loadObjects" />
      </div>
      <p v-else-if="!sk.objects.length" class="oui-muted" role="status">{{ t('skip.none') }}</p>
      <template v-else>
        <p class="oui-meta mp-p">{{ t('skip.help') }}</p>
        <div class="mp-objects" role="group" :aria-label="t('skip.title')">
          <span v-for="(n, i) in sk.objects" :key="n" class="kc-row">
            <Checkbox v-model="chosen" :input-id="`obj-${i}`" :value="n" :data-object="n" /><label :for="`obj-${i}`">{{ n }}</label></span>
        </div>
        <div class="kc-row">
          <Button severity="danger" outlined size="small" :label="t('skip.go')" :disabled="!chosen.length" :loading="tracker.isBusy('skip')"
                  data-test="skip" data-focus-key="skip" @click="skip" />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.mp { display: grid; gap: 8px; margin-top: 8px; }
.mp-h { display: flex; align-items: center; gap: 6px; margin: 16px 0 0; }
.mp-p { margin: 0; }
.mp-axes { display: grid; grid-template-columns: 24px 56px 56px; gap: 6px 8px; align-items: center; }
.mp-objects { display: flex; flex-wrap: wrap; gap: 8px 20px; }
</style>
