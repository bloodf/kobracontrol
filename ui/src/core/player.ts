// The camera's own player: fragmented MP4 from the plugin (camera.Relay, fmp4.py) into Media Source Extensions,
// so the camera needs no ffmpeg. WebKit (OrcaSlicer on macOS, Linux) gets ManagedMediaSource through srcObject:
// a MediaSource object URL never opens there from the page's file:// origin. Chromium (WebView2) gets MediaSource.
type MS = typeof MediaSource;
const W = window as unknown as { ManagedMediaSource?: MS; MediaSource?: MS };
const Source = (): MS | undefined => W.ManagedMediaSource ?? W.MediaSource;
const LIVE_LAG_S = 1.5, KEEP_S = 10, MAX_QUEUE = 50;   // 50 fragments: 5 s at the Kobra X's 10 fps

/** The page can play the Kobra X stream (H.264 High) itself; sent in every lease. */
export function playable(): boolean {
  try { return Source()?.isTypeSupported('video/mp4; codecs="avc1.640028"') === true; } catch { return false; }
}

const bytes = (b64: string): Uint8Array<ArrayBuffer> => Uint8Array.from(atob(b64), c => c.charCodeAt(0));
interface Part { buf: Uint8Array<ArrayBuffer>; key: boolean }
export interface PlayerEvents {
  playing: () => void;   // frames are on screen
  failed: () => void;    // this stream can't be played here: the plugin falls back to ffmpeg
  reset: () => void;     // fragments but no init segment (the page reloaded): ask the plugin for it again
}

export class Player {
  private ms: MediaSource | null = null;
  private sb: SourceBuffer | null = null;
  private queue: Part[] = [];
  private url = '';
  private waitKey = true;     // after an init or dropped fragments the decoder can only start at a keyframe
  private askedReset = false;
  private readonly onError = () => this.fail();
  constructor(private video: HTMLVideoElement, private on: PlayerEvents) {
    video.addEventListener('playing', () => { if (this.ms) on.playing(); });
    video.addEventListener('error', this.onError);
  }

  /** A new stream (first start, reconnect, new token, a page reload): a fresh MediaSource, the init segment first. */
  init(codec: string, init: string): void {
    this.close();
    const S = Source();
    if (!S) { this.on.failed(); return; }
    const ms = new S();
    this.ms = ms;
    this.queue = [{ buf: bytes(init), key: true }];
    this.waitKey = true; this.askedReset = false;
    const ended = () => { if (this.ms === ms) this.fail(); };   // closed by anyone but close()
    ms.addEventListener('sourceopen', () => {
      if (this.ms !== ms) return;
      try { this.sb = ms.addSourceBuffer(`video/mp4; codecs="${codec}"`); } catch { this.fail(); return; }
      this.sb.mode = 'segments';
      this.sb.addEventListener('updateend', () => this.pump());
      this.sb.addEventListener('error', this.onError);
      ms.addEventListener('sourceclose', ended);
      ms.addEventListener('sourceended', ended);
      this.pump();
    }, { once: true });
    const v = this.video;
    v.disableRemotePlayback = true;   // ManagedMediaSource opens only without AirPlay
    if (S === W.ManagedMediaSource && 'srcObject' in v) v.srcObject = ms as unknown as MediaProvider;
    else v.src = this.url = URL.createObjectURL(ms);
  }

  append(data: string, key: boolean): void {
    if (!this.ms) {
      if (!this.askedReset) { this.askedReset = true; this.on.reset(); }
      return;
    }
    if (this.waitKey && !key) return;
    this.waitKey = false;
    if (this.queue.length >= MAX_QUEUE) { this.queue = []; this.waitKey = !key; if (!key) return; }   // too far behind
    this.queue.push({ buf: bytes(data), key });
    this.pump();
  }

  private pump(): void {
    const sb = this.sb, v = this.video;
    if (!sb || sb.updating || !this.ms || this.ms.readyState !== 'open') return;
    const b = sb.buffered, end = b.length ? b.end(b.length - 1) : 0;
    if (end && end - v.currentTime > LIVE_LAG_S) v.currentTime = end - 0.2;   // fell behind: back to live
    try {
      if (b.length && v.currentTime - b.start(0) > KEEP_S * 2) sb.remove(0, v.currentTime - KEEP_S);
      else if (this.queue.length) { sb.appendBuffer(this.queue[0].buf); this.queue.shift(); }   // shifted only once accepted
    } catch (e) {
      if ((e as DOMException)?.name !== 'QuotaExceededError') { this.fail(); return; }
      if (b.length && v.currentTime - b.start(0) > 1) sb.remove(0, v.currentTime - 1);   // make room, then retry
      else { this.queue = this.queue.slice(1); this.dropToKey(); }
    }
    if (v.paused && end) void v.play().catch(() => {});
  }

  /** Skip queued fragments up to the next keyframe (the decoder can't use the ones in between). */
  private dropToKey(): void {
    const k = this.queue.findIndex(p => p.key);
    this.queue = k < 0 ? [] : this.queue.slice(k);
    this.waitKey = k < 0;
  }

  private fail(): void {
    if (!this.ms) return;
    this.close();
    this.on.failed();
  }

  close(): void {
    this.ms = null; this.sb = null; this.queue = [];
    const v = this.video;
    v.removeAttribute('src'); v.srcObject = null; v.load();
    if (this.url) { URL.revokeObjectURL(this.url); this.url = ''; }
  }
}
