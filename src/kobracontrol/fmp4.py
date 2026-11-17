"""The printer's HTTP-FLV camera stream (H.264, video only) as fragmented MP4 for the page's own MSE player, so
the camera needs no ffmpeg. Pure Python, no I/O, free of the `orca` module.

    remux = Remuxer()
    for event in remux.feed(chunk):   # ("init", codec, bytes) once per stream (again if the SPS changes),
        ...                           # then ("media", bytes, keyframe): one moof+mdat per frame, from a keyframe on

A frame goes out when the next one arrives (its duration is the gap between them), one frame of latency. Decode
times are the running sum of those durations, so a printer clock that jumps (back or far ahead) never makes two
samples overlap.
Raises Unsupported for anything but FLV with AVC video (the caller falls back to ffmpeg) and FlvError for a
broken stream.
"""

import struct

MAX_TAG = 4 * 1024 * 1024
TIMESCALE = 1000            # FLV timestamps are milliseconds
DEFAULT_DURATION = 100      # a frame whose gap to the next one is not believable (first frame, a jump)
SYNC, NON_SYNC = 0x02000000, 0x01010000   # trun sample flags: depends on nothing / depends on others, not sync
HIGH_PROFILES = (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135)
MATRIX = struct.pack(">9I", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)


class FlvError(ValueError):
    pass


class Unsupported(FlvError):
    pass


class FlvReader:
    """Splits an FLV byte stream into (tag_type, timestamp_ms, body), however the bytes are chunked."""

    def __init__(self):
        self.buf, self.header = bytearray(), False

    def feed(self, chunk):
        self.buf += chunk
        tags = []
        if not self.header:
            if len(self.buf) < 9:
                return tags
            if self.buf[:3] != b"FLV":
                raise Unsupported("not an FLV stream")
            offset = struct.unpack(">I", self.buf[5:9])[0]
            if not 9 <= offset <= 1024:
                raise FlvError("bad FLV header")
            skip = offset + 4   # header, then PreviousTagSize0
            if len(self.buf) < skip:
                return tags
            del self.buf[:skip]
            self.header = True
        while len(self.buf) >= 11:
            size = int.from_bytes(self.buf[1:4], "big")
            if size > MAX_TAG:
                raise FlvError("FLV tag too large")
            if len(self.buf) < 11 + size + 4:
                break
            ts = int.from_bytes(self.buf[4:7], "big") | self.buf[7] << 24
            tags.append((self.buf[0] & 0x1F, ts, bytes(self.buf[11:11 + size])))
            del self.buf[:11 + size + 4]
        return tags


class Bits:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def u(self, n):
        v = 0
        for _ in range(n):
            byte = self.data[self.pos >> 3] if self.pos >> 3 < len(self.data) else 0
            v = v << 1 | (byte >> (7 - (self.pos & 7))) & 1
            self.pos += 1
        return v

    def ue(self):
        zeros = 0
        while not self.u(1):
            zeros += 1
            if zeros > 31:
                raise FlvError("bad SPS")
        return (1 << zeros) - 1 + self.u(zeros)

    def se(self):
        v = self.ue()
        return (v + 1) // 2 if v & 1 else -(v // 2)


def sps_size(sps):
    """(width, height) from an H.264 SPS NAL unit (ITU-T H.264 7.3.2.1.1)."""
    rbsp = bytes(sps).replace(b"\x00\x00\x03", b"\x00\x00")   # emulation prevention
    b = Bits(rbsp[1:])
    profile = b.u(8)
    b.u(16)                          # constraint flags, level
    b.ue()                           # seq_parameter_set_id
    chroma = 1
    if profile in HIGH_PROFILES:
        chroma = b.ue()
        if chroma == 3:
            b.u(1)
        b.ue(), b.ue(), b.u(1)       # bit depths, qpprime_y_zero_transform_bypass
        if b.u(1):                   # seq_scaling_matrix_present
            for i in range(12 if chroma == 3 else 8):
                if b.u(1):
                    last = nxt = 8
                    for _ in range(16 if i < 6 else 64):
                        if nxt:
                            nxt = (last + b.se()) % 256
                        last = nxt or last
    b.ue()                           # log2_max_frame_num_minus4
    poc = b.ue()
    if poc == 0:
        b.ue()
    elif poc == 1:
        b.u(1), b.se(), b.se()
        for _ in range(b.ue()):
            b.se()
    b.ue(), b.u(1)                   # max_num_ref_frames, gaps_in_frame_num_allowed
    w_mbs, h_units = b.ue() + 1, b.ue() + 1
    frame_mbs_only = b.u(1)
    if not frame_mbs_only:
        b.u(1)
    b.u(1)                           # direct_8x8_inference
    width, height = w_mbs * 16, (2 - frame_mbs_only) * h_units * 16
    if b.u(1):                       # frame_cropping
        left, right, top, bottom = b.ue(), b.ue(), b.ue(), b.ue()
        cx = 1 if chroma in (0, 3) else 2
        cy = (2 - frame_mbs_only) * (2 if chroma == 1 else 1)
        width, height = width - (left + right) * cx, height - (top + bottom) * cy
    return width, height


def box(kind, *parts):
    payload = b"".join(parts)
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def full(kind, version, flags, *parts):
    return box(kind, struct.pack(">I", version << 24 | flags), *parts)


def init_segment(avcc, width, height):
    zero = struct.pack(">I", 0)
    avc1 = box(b"avc1", bytes(6), struct.pack(">H", 1), bytes(16), struct.pack(">HH", width, height),
               struct.pack(">IIIH", 0x480000, 0x480000, 0, 1), bytes(32), struct.pack(">Hh", 0x18, -1),
               box(b"avcC", avcc))
    stbl = box(b"stbl", full(b"stsd", 0, 0, struct.pack(">I", 1), avc1), full(b"stts", 0, 0, zero),
               full(b"stsc", 0, 0, zero), full(b"stsz", 0, 0, zero, zero), full(b"stco", 0, 0, zero))
    minf = box(b"minf", full(b"vmhd", 0, 1, bytes(8)),
               box(b"dinf", full(b"dref", 0, 0, struct.pack(">I", 1), full(b"url ", 0, 1))), stbl)
    mdia = box(b"mdia", full(b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, TIMESCALE, 0, 0x55C4, 0)),
               full(b"hdlr", 0, 0, zero, b"vide", bytes(12), b"VideoHandler\x00"), minf)
    tkhd = full(b"tkhd", 0, 3, struct.pack(">IIIII", 0, 0, 1, 0, 0), bytes(8), struct.pack(">hhhH", 0, 0, 0, 0),
                MATRIX, struct.pack(">II", width << 16, height << 16))
    mvhd = full(b"mvhd", 0, 0, struct.pack(">IIIIIH", 0, 0, TIMESCALE, 0, 0x10000, 0x100), bytes(10), MATRIX,
                bytes(24), struct.pack(">I", 2))
    mvex = box(b"mvex", full(b"trex", 0, 0, struct.pack(">IIIII", 1, 1, 0, 0, 0)))
    ftyp = box(b"ftyp", b"isom", struct.pack(">I", 0x200), b"isomiso6avc1mp41")
    return ftyp + box(b"moov", mvhd, box(b"trak", tkhd, mdia), mvex)


def media_segment(seq, dts, duration, cts, key, data):
    def moof(offset):
        trun = full(b"trun", 1, 0xF01, struct.pack(">Ii", 1, offset),
                    struct.pack(">IIIi", duration, len(data), SYNC if key else NON_SYNC, cts))
        traf = box(b"traf", full(b"tfhd", 0, 0x20000, struct.pack(">I", 1)), full(b"tfdt", 1, 0, struct.pack(">Q", dts)),
                   trun)
        return box(b"moof", full(b"mfhd", 0, 0, struct.pack(">I", seq)), traf)
    head = moof(len(moof(0)) + 8)
    return head + box(b"mdat", data)


class Remuxer:
    def __init__(self):
        self.reader = FlvReader()
        self.avcc = None
        self.pending = None      # (ts, cts, key, data): the frame waiting for the next one's timestamp
        self.next_dts = None     # decode time of the next frame sent; None until the first keyframe
        self.seq = 0

    def feed(self, chunk):
        events = []
        for kind, ts, body in self.reader.feed(chunk):
            if kind != 9 or len(body) < 5:   # audio (none on the Kobra X) and script data are not needed
                continue
            if body[0] & 0x80 or body[0] & 0x0F != 7:
                raise Unsupported("the camera stream is not H.264")
            packet, cts = body[1], int.from_bytes(body[2:5], "big", signed=True)
            if packet == 0:
                self._config(body[5:], events)
            elif packet == 1 and self.avcc is not None and body[0] >> 4 != 5:   # 5: video info, not a picture
                key = body[0] >> 4 == 1
                if self.pending is None and self.next_dts is None and not key:
                    continue     # wait for a keyframe: the decoder can start nowhere else
                self._frame((ts, cts, key, body[5:]), events)
        return events

    def _config(self, avcc, events):
        if avcc == self.avcc:
            return
        if len(avcc) < 8 or avcc[0] != 1 or avcc[5] & 0x1F < 1:
            raise FlvError("bad AVC configuration")
        sps_len = struct.unpack(">H", avcc[6:8])[0]
        width, height = sps_size(avcc[8:8 + sps_len])
        if not (16 <= width <= 8192 and 16 <= height <= 8192):
            raise FlvError("bad SPS size %dx%d" % (width, height))
        self.avcc, self.pending, self.next_dts = bytes(avcc), None, None   # a new decoder: a new stream
        events.append(("init", "avc1.%02x%02x%02x" % (avcc[1], avcc[2], avcc[3]), init_segment(avcc, width, height)))

    def _frame(self, frame, events):
        if self.pending is not None:
            ts, cts, key, data = self.pending
            gap = frame[0] - ts
            duration = gap if 0 < gap <= 5000 else DEFAULT_DURATION
            dts = self.next_dts or 0
            self.next_dts = dts + duration
            self.seq += 1
            events.append(("media", media_segment(self.seq, dts, duration, cts, key, data), key))
        self.pending = frame
