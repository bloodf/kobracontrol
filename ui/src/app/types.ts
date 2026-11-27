export interface Slot {
  global_index: number; box_id: number; box_pos: number; index: number; status: number; type: string; color: number[];
  rfid: number | null; sku: string | null; percent?: number | null; weight?: number | null; brand?: string; material_name?: string; activity: string; tray: number; usable: boolean; spool_id: number | null;
}
export interface Drying { status: number; target_temp: number; duration: number; remain_time: number; humidity: number | null; current_temp: number | null }
export interface AceUnit { id: number; auto_feed: boolean; humidity?: number | null; temp?: number | null; status?: number; model_id?: number; drying: Drying }
export interface Can { pause: boolean; resume: boolean; stop: boolean; move: boolean; heat: boolean; feed: boolean; print: boolean }
export interface Status {
  camera_url?: string;   // the printer's stream: rtsp:// needs ffmpeg, http:// plays in the page
  connected: boolean; state: string; preparing: boolean; kobra_state: string; printer_name: string; model: string; firmware: string;
  filename: string; progress: number; layer: number; total_layers: number; elapsed_s: number; remaining_s: number; task_id: string;
  nozzle_temp: number; nozzle_target: number; bed_temp: number; bed_target: number; chamber_temp?: number | null; chamber_target?: number | null; fan_pct: number; light_on: boolean; speed_mode: number;
  storage: { total?: number; used?: number };
  skipped_objects: string[]; pause_reason: { code?: number; msg?: string } | null; last_error: { msg?: string; code?: number } | null;
  phase_unit?: number | null; phase_channel?: number | null; box_set_failed: boolean; updated_at: number;
  mode: 'toolhead' | 'ace_direct' | 'ace_hub'; slots: Slot[]; loaded_slot: number; ace_units: AceUnit[]; can: Can;
  /** 'cloud' when this printer is reached through Anycubic Cloud (no move, heat or feed there); absent on the LAN. */
  transport?: 'cloud';
  /** The printer's TLS certificate (SHA-256 hex); changed_from is the one seen before when it changed, else "". */
  tls?: { fingerprint: string; changed_from: string } | null;
  /** info/report features ({"flow_calibration_support": true, ...}); {} before the printer said. */
  features?: Record<string, boolean>;
  /** Network (MAC) address, "" until the printer reported it. */
  mac?: string;
  /** Only the counters the printer reported. */
  stats?: { print_minutes?: number; print_count?: number; filament_g?: number };
  /** Print Assist switches by option number (JSON keys are strings); null until the printer answered. */
  assist?: Record<string, boolean> | null;
  /** An Upload and Print from OrcaSlicer (upload bridge) waiting for Start here; null when there is none. */
  bridge_pending?: { id: string; name: string; at: number } | null;
  /** This model's temperature maxima (profiles.py); 0 for a model Kobra Control does not know. */
  limits?: Limits;
  /** profiles.describe: known = has a LAN profile (else read-only), verified = tried on a real printer. */
  profile?: { known: boolean; verified: boolean; name: string; mode_id: string; single_client: boolean };
}
export interface Info { address: string; printer: string; generation: number; model?: string; firmware?: string;
  source?: AddressSource; note?: string }
/** Where the address in use came from (service.ORIGIN_TEXT). */
export type AddressSource = 'override' | 'preset' | 'remembered' | 'discovered' | '';
export interface Located { address: string; source: AddressSource; preset_host: string; preset_agent: string;
  spoolman_url: string; spoolman_source: 'settings' | 'spooler' | '' }
export interface Spool { id: number; name: string; vendor: string; material: string; colour?: string; colours?: string[];
  remaining?: number | null; initial?: number | null; location?: string; filament_id?: number; low?: boolean; use_first?: boolean; bound_slot?: number | null }
export interface StockView {
  spooler: { state: string; text: string; detail?: string; version?: string; links?: number };
  /** source 'spoolman' with code 'own': Kobra Control's own Spoolman list, as Spooler shares none (`spooler_reason` says why). */
  stock: { state: string; code?: string; text: string; detail?: string; rows: Spool[]; key: string; ts?: number; source?: string };
  same_spoolman: boolean | 'fallback' | null; usage: string; bindings: Record<string, number>;
  /** true when the list is usable; otherwise `reason` says why (absent, stale, waiting, unsupported, or a stock state code). */
  available: boolean; reason: string | null; spooler_reason?: string;
}
export interface FileEntry { name: string; size: number; timestamp: number; thumbnail?: string | null }
export interface FilesResult { files: FileEntry[] }
export interface FileInfo { estimated_s: number | null; layers: number | null; filament_g: number | null; layer_height: number | null;
  nozzle_temp: number | null; bed_temp: number | null; nozzle: number | null; printer_model: string; model_ok: boolean }
export interface FileMaterial { paint_index: number; material: string; colour: string; grams: number; slot: number | null;
  slot_type: string; slot_colour: string; check: 'ok' | 'differs' | 'missing' }
export interface FileDetails { name: string; thumbnail?: string | null; info?: FileInfo; materials?: FileMaterial[] }
/** A time-lapse video on the printer: `name` is the print, `created` unix seconds, `duration` seconds, `size` bytes;
 *  `empty` when nothing was recorded (the print ended before the first frame). */
export interface VideoEntry { filename: string; name: string; created: number; duration: number; size: number; empty: boolean }
export interface VideosResult { videos: VideoEntry[] }
/** Something the plugin needs and cannot install itself (src/kobracontrol/requirements.py). */
export type RequirementId = 'ffmpeg' | 'anycubic_slicer' | 'printer_agents' | 'spoolman' | 'certificate' | 'spooler';
export interface Requirement { id: RequirementId; state: 'ok' | 'missing' | 'unknown'; details: string }
export interface Certificate { found: boolean; source?: string }
export interface Limits { nozzle_max: number; bed_max: number }
export interface Config {
  settings: Record<string, any>; certificate: Certificate; spooler: { installed?: boolean; url?: string; dismissed?: boolean };
  version: string; limits: Limits; located?: Located | null; agent_id?: string; bridge?: BridgeState;
  /** How the selected printer preset reaches the printer (plugin.preset_setup): the Dashboard's setup hints. */
  setup?: { kobra?: boolean; agent?: string; host_type?: string; host?: string };
  /** Where the plugin found ffmpeg ('' = not found); absent from a plugin that does not look. */ ffmpeg?: string;
}
/** The upload bridge: on in Settings, listening, where, its API key and why it is not running. */
export interface BridgeState { enabled: boolean; running: boolean; port: number; host: string; key: string; error: string }
export interface UsagePending { file: string; printer: string; grams: Record<string, number> }
export interface UsageEntry { id: string; at: number | null; spool: number | null; grams: number; slot: number; file: string; error: string;
  job?: string; printer: string; printer_name?: string; spoolman?: string; acknowledged_at?: number }
export interface UsageView { pending: UsagePending[]; unconfirmed: UsageEntry[]; acknowledged: UsageEntry[]; acknowledged_total: number;
  save_error: string; restore_notice: string }
/** A slot's OrcaSlicer preset as the Device tab reports it (preset_matches): reasons are filmatch [code, value]. */
export interface PresetMatch { slot: number; name: string; source: 'linked' | 'remembered' | 'spooler' | 'generic' | 'none'; score: number | null;
  reasons: unknown; confident: boolean; candidates: { name: string; score: number; reasons: unknown }[]; remembered_key: string }
