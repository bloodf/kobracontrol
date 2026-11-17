<script setup lang="ts">
// One project filament's chip: its material on its own colour, and under it the slot it prints from. The chip opens a
// row of spool discs, one per printer slot; slots of another material family (and empty ones) can't be chosen.
// Keyboard: the discs are one radio group (arrows move, Enter/Space choose, Escape closes and returns to the chip).
import { computed, nextTick, ref } from 'vue';
import Popover from 'primevue/popover';
import { OuiIcon } from '../../shared/src/components';
import { check, chevronDown } from '../../shared/src/icons';
import { t } from '../core/i18n';
import { sameFamily, type PdFilament, type PdSlot } from '../core/printsetup';
import { inkOn, slotNumber, slotName } from './slots';

const props = defineProps<{ filament: PdFilament; slots: PdSlot[]; tray: number; disabled?: boolean; invalid?: boolean }>();
const emit = defineEmits<{ pick: [tray: number] }>();
const pop = ref<InstanceType<typeof Popover> | null>(null);
const chip = ref<HTMLButtonElement | null>(null);
const group = ref<HTMLElement | null>(null);

const chosen = computed(() => props.slots.find(s => s.tray === props.tray));
const choosable = (s: PdSlot) => s.usable && sameFamily(props.filament, s);
const discLabel = (s: PdSlot) => [t('pd.disc', { slot: slotName(s, props.slots), type: s.usable ? (s.type || t('slot.noType')) : t('slot.empty') }), s.spool]
  .filter(Boolean).join(' · ');
const chipLabel = computed(() => t('pd.slotBtn', { n: props.filament.index + 1, type: props.filament.type || '?',
  slot: chosen.value ? discLabel(chosen.value) : t('pd.noSlot') }));

async function open(e: Event) {
  if (props.disabled) return;
  pop.value?.toggle(e);
  await nextTick();
  setTimeout(() => (group.value?.querySelector<HTMLElement>('[aria-checked="true"]:not([aria-disabled="true"])')
    ?? group.value?.querySelector<HTMLElement>('[role=radio]:not([aria-disabled="true"])'))?.focus(), 60);
}
function choose(s: PdSlot) {
  if (!choosable(s)) return;
  emit('pick', s.tray);
  pop.value?.hide();
  chip.value?.focus();
}
function onKey(e: KeyboardEvent) {
  const discs = [...(group.value?.querySelectorAll<HTMLElement>('[role=radio]:not([aria-disabled="true"])') ?? [])];
  const at = discs.indexOf(document.activeElement as HTMLElement);
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
  if (step && discs.length) { e.preventDefault(); discs[(at + step + discs.length) % discs.length].focus(); }
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); pop.value?.hide(); chip.value?.focus(); }
}
</script>

<template>
  <div class="sp" :data-f="filament.index" :data-invalid="invalid || undefined">
    <span class="sp-material" :style="{ background: filament.colour, color: inkOn(filament.colour) }">{{ filament.type || '?' }}</span>
    <button ref="chip" type="button" class="sp-slot" :style="{ background: filament.colour, color: inkOn(filament.colour) }" :disabled="disabled"
            :aria-label="chipLabel" :title="chipLabel" aria-haspopup="dialog" :data-test="`slot-${filament.index}`" @click="open">
      <OuiIcon :icon="chevronDown" :size="14" /><span class="oui-num">{{ chosen ? slotNumber(chosen, slots) : '–' }}</span>
    </button>
    <Popover ref="pop" class="sp-pop" :pt="{ content: { role: 'dialog', 'aria-label': t('pd.pickTitle', { n: filament.index + 1 }) } }">
      <div ref="group" class="sp-discs" role="radiogroup" :aria-label="t('pd.pickTitle', { n: filament.index + 1 })" @keydown="onKey">
        <div v-for="s in slots" :key="s.tray" class="sp-disc" role="radio" :aria-checked="s.tray === tray" :aria-disabled="!choosable(s) || undefined"
             :tabindex="choosable(s) ? 0 : -1" :aria-label="discLabel(s)" :title="discLabel(s)" :data-tray="s.tray"
             @click="choose(s)" @keydown.enter.prevent="choose(s)" @keydown.space.prevent="choose(s)">
          <span class="sp-reel" :data-empty="!s.usable || undefined" :style="s.usable ? { background: s.colour, color: inkOn(s.colour) } : {}">
            <span class="sp-n oui-num">{{ slotNumber(s, slots) }}</span><span class="sp-hub" /><span class="sp-type">{{ s.usable ? (s.type || '?') : '–' }}</span>
          </span>
          <OuiIcon v-if="s.tray === tray" :icon="check" :size="14" class="sp-check" />
          <span class="sp-spool">{{ s.spool }}</span>
        </div>
      </div>
      <p class="sp-only" data-tone="warn">{{ t('pd.sameOnly') }}</p>
    </Popover>
  </div>
</template>

<style>
.sp { display: grid; width: 116px; border-radius: var(--oui-radius); overflow: hidden; box-shadow: inset 0 0 0 1px var(--oui-border); }
.sp[data-invalid] { box-shadow: 0 0 0 2px var(--oui-danger); }
.sp-material { display: block; padding: 6px 8px; font-weight: 700; text-align: center; overflow-wrap: anywhere; }
.sp-slot { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 32px; border: 0; border-top: 1px solid rgb(0 0 0 / .18);
  font: inherit; font-weight: 700; cursor: pointer; }
.sp-slot:disabled { cursor: default; opacity: .6; }
.sp-slot:focus-visible { outline: 2px solid var(--oui-primary); outline-offset: -4px; }
.sp-discs { display: flex; flex-wrap: wrap; gap: var(--oui-s2); max-width: min(92vw, 460px); }
.sp-disc { position: relative; display: grid; justify-items: center; gap: 4px; width: 84px; padding: 6px; border-radius: var(--oui-radius); cursor: pointer; }
.sp-disc[aria-checked="true"] { background: var(--oui-primary-soft); box-shadow: inset 0 0 0 2px var(--oui-primary); }
.sp-disc[aria-disabled="true"] { cursor: not-allowed; opacity: .45; }
.sp-disc:focus-visible { outline: 2px solid var(--oui-primary); outline-offset: 1px; }
.sp-reel { display: grid; justify-items: center; align-content: center; width: 64px; height: 64px; border-radius: 50%; line-height: 1.05;
  box-shadow: inset 0 0 0 2px rgb(255 255 255 / .55), 0 0 0 1px var(--oui-border); font-weight: 700; }
.sp-reel[data-empty] { background: var(--oui-raised); color: var(--oui-muted); box-shadow: inset 0 0 0 2px var(--oui-border); border: 1px dashed var(--oui-control-border); }
.sp-n { font-size: var(--oui-text-sm); }
.sp-hub { width: 14px; height: 14px; margin: 2px 0; border-radius: 50%; background: var(--oui-text); box-shadow: 0 0 0 2px rgb(255 255 255 / .8); }
.sp-type { font-size: var(--oui-text-xs); max-width: 56px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sp-check { position: absolute; inset: 4px 4px auto auto; color: var(--oui-primary); }
.sp-spool { max-width: 80px; font-size: var(--oui-text-xs); color: var(--oui-muted); text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sp-spool:empty { display: none; }
.sp-only { margin: var(--oui-s2) 0 0; font-size: var(--oui-text-sm); font-weight: 600; color: var(--oui-tone); }
</style>
