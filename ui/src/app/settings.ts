import { computed, reactive, ref } from 'vue';
import * as bridge from '../core/bridge';
import { message } from '../core/tracker';
import { t, onLangPref } from '../core/i18n';
import { hello, lease, onConfig, s, tracker } from './store';
import type { Config, PurgeCorner } from './types';

// Settings form: a config message from the plugin never wipes values the user is still editing; "Saved" only
// once the plugin answered; on an error the typed values stay.
export const config = ref<Config | null>(null);
const DEFAULT_NAME = 'Anycubic Kobra X';
export const form = reactive({ host: '', name: DEFAULT_NAME, ffmpeg: '', camera: true, leveling: true, vibration: true, flow: false, timelapse: false,
  spoolman: '', spoolmanAuto: true, usage: true,
  bridge: false, bridgePort: 8765, purge: false, purgeLength: 30, purgeSpeed: 5, purgeCorner: 'front_left' as PurgeCorner });
export const saving = ref(false);
/** A Spoolman address is set here or comes from Spooler: linking spools to slots needs one. */
export const spoolmanSet = computed(() => !!(config.value?.settings.spoolman_url || s.located?.spoolman_url));
let cameraApplied = false;

type Form = typeof form;
const fromSettings = (st: Record<string, any>): Form => ({
  host: st.host || '', name: st.printer_name || DEFAULT_NAME, ffmpeg: st.ffmpeg_path || '', camera: st.camera_enabled === true,
  leveling: st.auto_leveling !== false, vibration: st.vibration_compensation !== false, flow: st.flow_calibration === true,
  timelapse: st.timelapse === true, spoolman: st.spoolman_url || '',
  spoolmanAuto: st.spoolman_auto !== false, usage: st.spoolman_report_usage !== false,
  bridge: st.bridge_enabled === true, bridgePort: Number(st.bridge_port) || 8765, purge: st.purge_enabled === true,
  purgeLength: Number(st.purge_length) || 30, purgeSpeed: Number(st.purge_speed) || 5, purgeCorner: st.purge_corner || 'front_left' });
const toSettings = (f: Form): Record<string, unknown> => ({
  host: f.host.trim(), printer_name: f.name.trim() || DEFAULT_NAME, ffmpeg_path: f.ffmpeg.trim(), camera_enabled: f.camera,
  auto_leveling: f.leveling, vibration_compensation: f.vibration, flow_calibration: f.flow, timelapse: f.timelapse, spoolman_url: f.spoolman.trim(),
  spoolman_auto: f.spoolmanAuto, spoolman_report_usage: f.usage,
  bridge_enabled: f.bridge, bridge_port: f.bridgePort, purge_enabled: f.purge, purge_length: f.purgeLength, purge_speed: f.purgeSpeed,
  purge_corner: f.purgeCorner });

/** The settings typed here and not saved yet, by their plugin names. */
export const changed = computed(() => {
  const c = config.value;
  if (!c) return [];
  const saved = toSettings(fromSettings(c.settings)), now = toSettings(form);
  return Object.keys(now).filter(k => now[k] !== saved[k]);
});
export const dirty = computed(() => changed.value.length > 0);
/** Back to the saved values (the save bar's Discard). */
export function discard(): void {
  if (config.value && !saving.value) Object.assign(form, fromSettings(config.value.settings));
}

function fill(m: Config): void {
  const keep = !saving.value && dirty.value;
  config.value = m;
  if (!cameraApplied) { cameraApplied = true; s.camOn = m.settings.camera_enabled === true; lease(); }
  if (!keep) Object.assign(form, fromSettings(m.settings));
}

export async function save(): Promise<void> {
  const c = config.value;
  if (!c || saving.value) return;
  saving.value = true;
  try {
    const r = await bridge.request({ type: 'save_settings', settings: toSettings(form) });
    if (r?.connect_error) tracker.notify('error', t('settings.savedBut', { error: r.connect_error }));
    else tracker.notify('success', t('ok.settings'));
    void hello();
  } catch (e) {
    tracker.notify('error', t('settings.notSaved', { error: message(e) }));
  } finally {
    saving.value = false;
  }
}

export function installSettings(): () => void {
  onLangPref(value => bridge.post({ type: 'ui_language', value }));
  return onConfig(fill);
}
