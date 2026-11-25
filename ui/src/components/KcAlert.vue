<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { OuiBanner } from '@orca-plugins/ui-foundation/src/components';
import type { OuiIconData } from '@orca-plugins/ui-foundation/src/icons';
import { alerts } from '../core/dismissals';
import { t } from '../core/i18n';

// A page alert on one line: its title, then its text cut off with Details to read the rest, its actions and Close.
// One click on Close hides it for its dismissKey (what it is about: core/dismissals.ts), also across polls where its
// condition blinks off; a new or different condition shows again. An error starts opened, so what is wrong and what
// to do are read without a click; `keep` holds an informational alert closed for the session.
// ponytail: wraps the foundation's OuiBanner; a compact/expandable mode belongs in OuiBanner itself (foundation PR).
const props = withDefaults(defineProps<{ title: string; dismissKey: string; tone?: 'info' | 'warn' | 'error' | 'success' | 'neutral';
  icon?: OuiIconData; id?: string; show?: boolean; keep?: boolean }>(), { show: true });

const closed = ref(false);
const open = ref(props.tone === 'error');
const long = ref(false);   // the text does not fit on its line: Details is offered
const root = ref<{ $el?: Element } | null>(null);

watch(() => [props.show, props.dismissKey] as const, ([on, key]) => {
  if (on) alerts.back(key, props.keep ? Infinity : undefined); else alerts.gone(key);
  closed.value = alerts.isDismissed(key);
}, { immediate: true });
function close(): void {
  alerts.dismiss(props.dismissKey);
  closed.value = true;
}

let observer: ResizeObserver | undefined;
const measure = () => {
  const text = root.value?.$el instanceof Element ? root.value.$el.querySelector<HTMLElement>('.kc-alert-body') : null;
  long.value = !!text && text.scrollWidth > text.clientWidth + 1;
};
watch(() => [props.show && !closed.value, props.title] as const, async () => {
  observer?.disconnect();
  await nextTick();
  const el = root.value?.$el;
  if (!(el instanceof Element) || typeof ResizeObserver === 'undefined') return;
  observer = new ResizeObserver(measure);
  observer.observe(el);
  measure();
}, { immediate: true, flush: 'post' });
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <OuiBanner ref="root" :show="show && !closed" :id="id" :tone="tone" :icon="icon" :title="title" class="kc-alert" :data-open="open || undefined"
             dismissible :close-label="t('common.close')" @dismiss="close">
    <span v-if="$slots.default" class="kc-alert-body oui-truncate"><slot /></span>
    <template #actions>
      <slot name="actions" />
      <button v-if="$slots.default && (long || open)" type="button" class="kc-alert-more" :aria-expanded="open" data-test="alert-more"
              @click="open = !open">{{ open ? t('alert.less') : t('alert.more') }}</button>
    </template>
  </OuiBanner>
</template>

<style>
/* One line: the title stays whole, the text is cut off inside its own box, actions and Close keep their place on
   the right. */
.kc-alert { flex-wrap: nowrap; min-width: 0; max-width: 100%; min-height: 32px; padding-block: 2px; }
.kc-alert:not([data-open]) .oui-banner-text { display: flex; align-items: baseline; padding-block: 1px; min-width: 0; }
.kc-alert:not([data-open]) .oui-banner-text > strong { flex: none; white-space: nowrap; }
.kc-alert:not([data-open]) .oui-banner-text > span { flex: 1 1 0; min-width: 0; overflow: hidden; }
.kc-alert-body { display: block; }
.kc-alert-body :is(p, ol, ul, li) { display: inline; margin: 0; padding: 0; }
.kc-alert-body li + li::before { content: ' · '; }
.kc-alert[data-open] .kc-alert-body { display: inline; white-space: normal; overflow: visible; }
.kc-alert[data-open] .kc-alert-body :is(p, ol) { display: block; margin: var(--oui-s1) 0 0; }
.kc-alert[data-open] .kc-alert-body ol { padding-inline-start: 1.25em; }
.kc-alert[data-open] .kc-alert-body li { display: list-item; }
.kc-alert[data-open] .kc-alert-body li + li::before { content: none; }
.kc-alert[data-open] { flex-wrap: wrap; }
.kc-alert .oui-banner-actions { flex-wrap: nowrap; flex: none; }
.kc-alert-more { border: 0; background: none; padding: 2px 6px; border-radius: var(--oui-radius); color: var(--oui-link, var(--oui-text)); font: inherit; font-size: 12px;
  cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
/* Narrow: the actions go under the line instead of pushing the page wider. */
@media (max-width: 640px) { .kc-alert, .kc-alert .oui-banner-actions { flex-wrap: wrap; } }
.kc-alert-more:hover { background: color-mix(in srgb, var(--oui-tone) 14%, transparent); }
</style>
