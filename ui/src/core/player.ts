// The camera's own player: fragmented MP4 from the plugin (camera.Relay, fmp4.py) into Media Source Extensions,
// so the camera needs no ffmpeg. WebKit (OrcaSlicer on macOS, Linux) gets ManagedMediaSource through srcObject:
// a MediaSource object URL never opens there from the page's file:// origin. Chromium (WebView2) gets MediaSource.
type MS = typeof MediaSource;
const W = window as unknown as { ManagedMediaSource?: MS; MediaSource?: MS };
const Source = (): MS | undefined => W.ManagedMediaSource ?? W.MediaSource;
const LIVE_LAG_S = 1.5, KEEP_S = 10;

/** The page can play the Kobra X stream (H.264 High) itself; sent in every lease. */
export function playable(): boolean {
  try { return Source()?.isTypeSupported('video/mp4; codecs="avc1.640028"') === true; } catch { return false; }
}

const bytes = (b64: string): Uint8Array<ArrayBuffer> => Uint8Array.from(atob(b64), c => c.charCodeAt(0));

export class Player {
  private ms: MediaSource | null = null;
  private sb: SourceBuffer | null = null;
  private queue: Uint8Array<ArrayBuffer>[] = [];
  private url = '';
  constructor(private video: HTMLVideoElement) {}

  /** A new stream (first start, reconnect, new token): a fresh MediaSource, the init segment first. */
  init(codec: string, init: string): void {
    this.close();
    const S = Source();
    if (!S) return;
    const ms = new S();
    this.ms = ms;
    this.queue = [bytes(init)];
    ms.addEventListener('sourceopen', () => {
      if (this.ms !== ms) return;
      try { this.sb = ms.addSourceBuffer(`video/mp4; codecs="${codec}"`); } catch { return; }
      this.sb.mode = 'segments';
      this.sb.addEventListener('updateend', () => this.pump());
      this.pump();
    }, { once: true });
    const v = this.video;
    v.disableRemotePlayback = true;   // ManagedMediaSource opens only without AirPlay
    if (S === W.ManagedMediaSource && 'srcObject' in v) v.srcObject = ms as unknown as MediaProvider;
    else v.src = this.url = URL.createObjectURL(ms);
  }

  append(data: string): void {
    if (!this.ms) return;
    this.queue.push(bytes(data));
    this.pump();
  }

  private pump(): void {
    const sb = this.sb, v = this.video;
    if (!sb || sb.updating || !this.ms || this.ms.readyState !== 'open') return;
    const b = sb.buffered, end = b.length ? b.end(b.length - 1) : 0;
    if (end && end - v.currentTime > LIVE_LAG_S) v.currentTime = end - 0.2;   // fell behind: back to live
    try {
      if (b.length && v.currentTime - b.start(0) > KEEP_S * 2) sb.remove(0, v.currentTime - KEEP_S);
      else if (this.queue.length) sb.appendBuffer(this.queue.shift()!);
    } catch { this.queue = []; }
    if (v.paused && end) void v.play().catch(() => {});
  }

  close(): void {
    this.ms = null; this.sb = null; this.queue = [];
    const v = this.video;
    v.removeAttribute('src'); v.srcObject = null; v.load();
    if (this.url) { URL.revokeObjectURL(this.url); this.url = ''; }
  }
}
