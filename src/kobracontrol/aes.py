"""AES-128 in CBC mode with PKCS#7 padding, pure Python (FIPS-197, NIST SP 800-38A).

The printer's /ctrl answer is AES-128-CBC encrypted; OrcaSlicer's bundled Python has no crypto
package, so the block cipher is implemented here. Speed is irrelevant: it decrypts a few hundred bytes.
"""

BLOCK = 16


def _xtime(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _mul(a, b):
    out = 0
    while b:
        if b & 1:
            out ^= a
        a, b = _xtime(a), b >> 1
    return out


def _sbox():
    exp, log, p = [0] * 255, [0] * 256, 1
    for i in range(255):  # 3 generates GF(2^8)*, so inverses come from log/antilog tables
        exp[i], log[p] = p, i
        p = _mul(p, 3)
    box = [0] * 256
    for x in range(256):
        inv = exp[(255 - log[x]) % 255] if x else 0
        s = inv
        for shift in range(1, 5):
            s ^= ((inv << shift) | (inv >> (8 - shift))) & 0xFF
        box[x] = s ^ 0x63
    return box


SBOX = _sbox()
INV_SBOX = [SBOX.index(i) for i in range(256)]
MUL = {k: [_mul(x, k) for x in range(256)] for k in (1, 2, 3, 9, 11, 13, 14)}


def _expand(key):
    if len(key) != 16:
        raise ValueError("AES-128 key must be 16 bytes")
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        w = list(words[i - 1])
        if i % 4 == 0:
            w = [SBOX[b] for b in w[1:] + w[:1]]
            w[0] ^= rcon
            rcon = _xtime(rcon)
        words.append([a ^ b for a, b in zip(words[i - 4], w)])
    return [sum(words[r * 4:r * 4 + 4], []) for r in range(11)]


def _check_block(block):
    if len(block) != BLOCK:
        raise ValueError("AES block must be 16 bytes")


def _add(state, rk):
    return [a ^ b for a, b in zip(state, rk)]


def _shift(state, sign):
    # State is column-major: byte (row r, column c) sits at index 4*c + r.
    return [state[4 * ((c + sign * r) % 4) + r] for c in range(4) for r in range(4)]


def _mix(state, m):
    out = []
    for c in range(4):
        col = state[4 * c:4 * c + 4]
        for r in range(4):
            out.append(MUL[m[0]][col[r]] ^ MUL[m[1]][col[(r + 1) % 4]] ^ MUL[m[2]][col[(r + 2) % 4]] ^ MUL[m[3]][col[(r + 3) % 4]])
    return out


def _encrypt(rks, block):
    s = _add(list(block), rks[0])
    for rnd in range(1, 11):
        s = _shift([SBOX[b] for b in s], 1)
        if rnd != 10:
            s = _mix(s, (2, 3, 1, 1))
        s = _add(s, rks[rnd])
    return bytes(s)


def _decrypt(rks, block):
    s = _add(list(block), rks[10])
    for rnd in range(9, -1, -1):
        s = [INV_SBOX[b] for b in _shift(s, -1)]
        s = _add(s, rks[rnd])
        if rnd:
            s = _mix(s, (14, 11, 13, 9))
    return bytes(s)


def encrypt_block(key, block):
    _check_block(block)
    return _encrypt(_expand(key), block)


def decrypt_block(key, block):
    _check_block(block)
    return _decrypt(_expand(key), block)


def encrypt_cbc(key, iv, data, pad=True):
    _check_block(iv)
    rks = _expand(key)
    if pad:
        n = BLOCK - len(data) % BLOCK
        data = bytes(data) + bytes([n]) * n
    elif len(data) % BLOCK:
        raise ValueError("data length must be a multiple of 16 without padding")
    out, prev = bytearray(), bytes(iv)
    for i in range(0, len(data), BLOCK):
        prev = _encrypt(rks, bytes(a ^ b for a, b in zip(data[i:i + BLOCK], prev)))
        out += prev
    return bytes(out)


def decrypt_cbc(key, iv, data, unpad=True):
    _check_block(iv)
    rks = _expand(key)
    if not data or len(data) % BLOCK:
        raise ValueError("ciphertext length must be a non-zero multiple of 16")
    out, prev = bytearray(), bytes(iv)
    for i in range(0, len(data), BLOCK):
        block = bytes(data[i:i + BLOCK])
        out += bytes(a ^ b for a, b in zip(_decrypt(rks, block), prev))
        prev = block
    if not unpad:
        return bytes(out)
    n = out[-1]
    if not 1 <= n <= BLOCK or out[-n:] != bytes([n]) * n:
        raise ValueError("bad PKCS#7 padding")
    return bytes(out[:-n])
