import { createApp, watch } from 'vue';
import { installOrcaUI } from '../shared/src';
import { boot } from './core/boot';
import { locale, setHostLanguage } from './core/i18n';
import { followHostTheme } from './core/theme';
import { primeVueOptions } from '../shared/src';
import { PRIME_LOCALE } from './core/prime-locale';
import './styles.css';
import App from './App.vue';

document.body.classList.add('orca-ui');
setHostLanguage(boot.lang);
followHostTheme();
const app = createApp(App);
installOrcaUI(app, 'en', 'violet');
// PrimeVue's own labels (dialog close, select filter…) follow the page language too.
const prime = app.config.globalProperties.$primevue;
const english = { ...prime.config.locale };
watch(locale, l => {
  document.documentElement.lang = l;
  // The shared foundation carries PrimeVue's pt-BR labels; the other languages' are this page's own (core/prime-locale.ts).
  const own = l === 'en' ? {} : l === 'pt-BR' ? primeVueOptions(l).locale ?? {} : PRIME_LOCALE[l];
  prime.config.locale = { ...english, ...own } as NonNullable<typeof prime.config.locale>;
}, { immediate: true });
app.mount('#app');
