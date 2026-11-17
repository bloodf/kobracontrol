<script setup lang="ts">
import { computed, useId } from 'vue';
import photo from '../assets/kobra-x.webp';
import filamentMask from '../assets/kobra-x-mask.png';
import shading from '../assets/kobra-x-shade.webp';
import { t, fmt } from '../core/i18n';
import { colourName, type FigureSpool } from '../core/figure';

// The Kobra X, photographed (Anycubic product image, NOTICE.md), with its four spools recoloured live, slot 1..4 left
// to right. The photo's filament areas are neutral grey; each spool's area (kobra-x-mask) is filled with the slot's
// colour, bands for a multi-colour spool, and the winding's own light and shade (kobra-x-shade, white and black with
// alpha) go back over it, so black, white and every hue keep the wound texture. The feeding slot glows, with its tube.
// Coordinates are the photo's pixels in the 1500 px original, minus the crop.
const props = defineProps<{ spools: FigureSpool[]; state?: string; stale?: boolean }>();

const uid = useId();
const W = 731, H = 1097;
const FIL_Y = 63, FIL_H = 255;                       // the windings' top and height
const FIL_X: [number, number][] = [[10, 101], [171, 264], [412, 507], [568, 661]];
const REEL_X: [number, number][] = [[5, 116], [167, 271], [407, 511], [563, 667]];   // flange to flange
const STRAND_X = [65, 209, 463, 605];
const TUBES = [
  'M60 15C110 70 210 180 258 233S305 330 310 380S318 460 318 493',
  'M213 8C238 40 275 140 293 193S318 300 320 353S325 460 325 493',
  'M456 13C430 45 390 140 373 193S338 300 335 353S335 460 335 493',
  'M608 11C560 55 460 160 413 213S352 290 348 333S343 460 343 493',
];

const reels = computed(() => props.spools.slice(0, 4).map((sp, i) => {
  const [x0, x1] = FIL_X[i], w = (x1 - x0) / Math.max(1, sp.colors.length);
  return { sp, x0, x1, reel: REEL_X[i], strand: STRAND_X[i], tube: TUBES[i],
    bands: sp.empty ? [] : sp.colors.map((c, k) => ({ c, x: x0 + k * w, w })) };
}));
const active = computed(() => reels.value.find(r => r.sp.active && !r.sp.empty) ?? null);
const tone = computed(() => (props.state === 'error' ? 'error' : props.state === 'paused' ? 'paused' : props.state === 'printing' || props.state === 'busy' ? 'busy' : 'idle'));

const NAMES = { black: 'figure.colour.black', white: 'figure.colour.white', grey: 'figure.colour.grey', red: 'figure.colour.red',
  orange: 'figure.colour.orange', brown: 'figure.colour.brown', yellow: 'figure.colour.yellow', green: 'figure.colour.green',
  cyan: 'figure.colour.cyan', blue: 'figure.colour.blue', purple: 'figure.colour.purple', pink: 'figure.colour.pink' } as const;
const label = computed(() => t('figure.label', { slots: fmt.list(props.spools.map(sp => {
  if (sp.empty) return t('figure.slotEmpty', { n: sp.n });
  const name = colourName(sp.colors[0] ?? '');
  const colour = sp.colors.length > 1 ? t('figure.colour.multi') : name ? t(NAMES[name]) : t('figure.colour.unknown');
  const one = t('figure.slot', { n: sp.n, colour, material: sp.material }).replace(/\s+/g, ' ').trim();
  return sp.active ? t('figure.feeding', { slot: one }) : one;
})) }));
</script>

<template>
  <svg class="kx" :viewBox="`0 0 ${W} ${H}`" role="img" :aria-label="label" :data-tone="tone" :data-stale="stale || undefined" data-test="printer-figure">
    <defs>
      <mask :id="`${uid}-fil`" maskUnits="userSpaceOnUse" x="0" y="0" :width="W" :height="H">
        <image :href="filamentMask" x="0" y="0" :width="W" :height="H" />
      </mask>
      <linearGradient :id="`${uid}-hub`" x1="0" x2="1" y1="0" y2="0">
        <stop offset="0" stop-color="#b9bec6" /><stop offset=".3" stop-color="#e3e6ea" /><stop offset=".75" stop-color="#a9afb8" /><stop offset="1" stop-color="#7d838c" />
      </linearGradient>
      <filter :id="`${uid}-glow`" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="9" /></filter>
    </defs>

    <rect v-if="active" class="kx-glow" :x="active.reel[0] - 6" y="32" :width="active.reel[1] - active.reel[0] + 12" height="312" rx="16" :filter="`url(#${uid}-glow)`" />
    <image :href="photo" x="0" y="0" :width="W" :height="H" />

    <g :mask="`url(#${uid}-fil)`">
      <g v-for="r in reels" :key="r.sp.n" class="kx-reel" :data-figure-slot="r.sp.n" :data-empty="r.sp.empty || undefined"
         :data-active="(r.sp.active && !r.sp.empty) || undefined" :data-colors="r.sp.colors.join(' ') || undefined">
        <rect v-if="r.sp.empty" class="kx-none" :x="r.x0" :y="FIL_Y" :width="r.x1 - r.x0" :height="FIL_H" />
        <template v-else>
          <rect v-for="(b, k) in r.bands" :key="k" :x="b.x" :y="FIL_Y" :width="b.w + .3" :height="FIL_H" :style="{ fill: b.c }" />
          <rect v-if="!r.bands.length" class="kx-unknown" :x="r.x0" :y="FIL_Y" :width="r.x1 - r.x0" :height="FIL_H" />
          <rect :x="r.strand - 4" y="29" width="8" :height="FIL_Y - 29" :style="{ fill: r.sp.colors[0] ?? '#9aa1ab' }" />
        </template>
      </g>
    </g>
    <image class="kx-shade" :href="shading" x="0" y="0" :width="W" :height="H" />
    <g :mask="`url(#${uid}-fil)`">
      <template v-for="r in reels.filter(x => x.sp.empty)" :key="r.sp.n">
        <rect class="kx-through" :x="r.x0 - 2" :y="FIL_Y - 2" :width="r.x1 - r.x0 + 4" :height="FIL_H + 4" />
        <rect class="kx-through" :x="r.strand - 5" y="29" width="10" :height="FIL_Y - 29" />
        <rect class="kx-hub" :x="r.x0" :y="FIL_Y + FIL_H / 2 - 52" :width="r.x1 - r.x0" height="104" :fill="`url(#${uid}-hub)`" />
      </template>
    </g>

    <path v-if="active" class="kx-tube-glow" :d="active.tube" :filter="`url(#${uid}-glow)`" data-test="figure-tube-active" />
    <path v-if="active" class="kx-tube-on" :d="active.tube" />

    <g v-if="active" class="kx-display">
      <rect x="299" y="586" width="46" height="44" rx="3" />
      <text x="322" y="622" data-test="figure-digit">{{ active.sp.n }}</text>
    </g>
  </svg>
</template>

<style>
.kx { display: block; flex: none; height: clamp(170px, 32cqi, 260px); width: auto; aspect-ratio: 731 / 1097; overflow: visible; }
.kx[data-stale] { filter: grayscale(.9); opacity: .7; }
.kx-none { fill: #c4c8ce; }
/* An empty slot: the winding is gone, the card shows through to the bare hub. */
.kx-through { fill: var(--oui-surface); }
.oui-on-band .kx-through { fill: var(--oui-band); }
.kx-hub { stroke: rgb(0 0 0 / .35); stroke-width: 1.5; }
.kx-unknown { fill: #9aa1ab; }
.kx-glow { fill: var(--oui-primary); opacity: .9; }
.oui-on-band .kx-glow { fill: #fff; opacity: .75; }
.kx-tube-glow { fill: none; stroke: var(--oui-primary); stroke-width: 14; stroke-linecap: round; opacity: .55; }
.oui-on-band .kx-tube-glow { stroke: #fff; opacity: .7; }
.kx-tube-on { fill: none; stroke: rgb(255 255 255 / .55); stroke-width: 3; stroke-linecap: round; }
.kx-display > rect { fill: #0e0f11; }
.kx-display > text { font: 300 38px/1 var(--oui-font, sans-serif); fill: #f4f6f8; text-anchor: middle; }
.kx[data-tone="paused"] .kx-display > text { fill: #f5b83d; }
.kx[data-tone="error"] .kx-display > text { fill: #ff5a52; }
</style>
