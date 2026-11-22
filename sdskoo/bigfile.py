"""Minimal reader for Sleeping Dogs: Definitive Edition .bix/.big archives.

Only what the decompiler needs: the index (.bix), the PMCQ LZ decompressor and the
name hash. No third-party dependencies.

  .bix  = 16-byte chunk header + BIGFileIndex (PC64 layout: count at +0x60, entries via
          a relative 64-bit offset at +0x68). Entry: 6 x u32
          (uid, offset/4, load_offset, compressed_size, compressed_extra, uncompressed_size).
  .big  = blobs at offset*4. Compressed entries skip (load_offset & 0xFFF) bytes, then a
          'PMCQ' header (0x40 bytes) followed by an LZ stream with a 32-entry match cache.
  uid   = CRC-32/MPEG-2 of the upper-cased path (file names); script symbols use the same
          CRC on the exact text (see hash32()).
"""
import struct

_T = []
for _i in range(256):
    _c = _i << 24
    for _ in range(8):
        _c = ((_c << 1) ^ 0x04C11DB7) if _c & 0x80000000 else (_c << 1)
    _T.append(_c & 0xFFFFFFFF)


def hash32(text, upper=False):
    """CRC-32/MPEG-2 (poly 0x04C11DB7, init 0xFFFFFFFF, no reflection, no final xor)."""
    if isinstance(text, str):
        text = text.encode('latin-1', 'replace')
    h = 0xFFFFFFFF
    for b in text:
        if upper and 97 <= b <= 122:
            b -= 32
        h = ((h << 8) & 0xFFFFFFFF) ^ _T[((h >> 24) ^ b) & 0xFF]
    return h


def file_uid(path):
    """Hash used for file names inside .big archives (upper-cased, backslashes)."""
    return hash32(path.replace('/', '\\'), upper=True)


_ENTRY = struct.Struct('<6I')
_PMCQ = 0x51434D50


class BigArchive:
    """Opens <name>.bix + <name>.big and reads entries by uid."""

    def __init__(self, bix_path):
        self.bix_path = bix_path
        self.big_path = bix_path[:-4] + '.big'
        d = open(bix_path, 'rb').read()
        _uid, _size, _size2, doff = struct.unpack_from('<4I', d, 0)
        base = 0x10 + doff
        if d[base + 0x58:base + 0x60] != b'\xff' * 8:
            raise ValueError('%s is not a Definitive Edition (64-bit) archive index' % bix_path)
        count = struct.unpack_from('<I', d, base + 0x60)[0]
        rel = struct.unpack_from('<q', d, base + 0x68)[0]
        eoff = base + 0x68 + rel
        self.entries = {}
        for i in range(count):
            e = _ENTRY.unpack_from(d, eoff + i * 24)
            self.entries[e[0]] = e

    def __contains__(self, uid):
        return uid in self.entries

    def read(self, uid):
        uid_, odiv4, load_off, csize, _cext, usize = self.entries[uid]
        with open(self.big_path, 'rb') as f:
            f.seek(odiv4 * 4)
            if csize == 0 or csize == usize:
                return f.read(usize)
            skip = load_off & 0xFFF
            raw = f.read(skip + csize)[skip:]
        return lz_decompress(raw)

    def read_file(self, path):
        return self.read(file_uid(path))


def lz_decompress(buf):
    """Decompresses a PMCQ block (qCompressHeader + LZ stream)."""
    mid, _mtype, _mver, doff, _extra, csize, usize, _chk = struct.unpack_from('<IHHIIqqq', buf, 0)
    if mid != _PMCQ:
        raise ValueError('not a PMCQ block (id=%08X)' % mid)
    inp = memoryview(buf)
    i, end = doff, csize
    out = bytearray()
    cache = [(0, 0)] * 32
    cur = 0
    while i < end and len(out) < usize:
        bits = inp[i]; i += 1
        if bits < 32:                       # literal run of bits+1 bytes
            n = bits + 1
            out += inp[i:i + n]; i += n
            continue
        idx, et = bits & 31, bits >> 5
        if et == 1:                         # reuse cached (offset, length)
            off, ln = cache[idx]
        else:
            off = inp[i] | (idx << 8); i += 1
            ln = (inp[i] + 1) if et == 7 else (et + 1)
            if et == 7:
                i += 1
            cache[cur] = (off, ln); cur = (cur + 1) & 31
        start = len(out) - off
        if off >= ln:
            out += out[start:start + ln]
        else:
            for k in range(ln):
                out.append(out[start + k])
    return bytes(out)
