"""Finds x64 instructions that reference an address through a RIP-relative operand
(LEA/MOV reg, [rip+rel32]), without Ghidra. Useful to locate the code that uses a string.

Usage:  python find_xrefs.py <exe> <text or 0xVA>...

Text arguments are searched in the file; each occurrence is resolved to its virtual address.
The code usually references the *start* of a string, so search for the full string
(e.g. 'Data\\Scripts\\Classes.skoo-bin') or pass the start VA explicitly.
"""
import struct
import sys


def load_sections(d):
    pe = struct.unpack_from('<I', d, 0x3C)[0]
    nsec = struct.unpack_from('<H', d, pe + 6)[0]
    optsz = struct.unpack_from('<H', d, pe + 20)[0]
    base = struct.unpack_from('<Q', d, pe + 24 + 24)[0]
    secs = []
    for i in range(nsec):
        o = pe + 24 + optsz + i * 40
        name = d[o:o + 8].rstrip(b'\0').decode()
        vsize, va, rsize, raddr = struct.unpack_from('<IIII', d, o + 8)
        secs.append((name, va, vsize, raddr, rsize))
    return base, secs


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    d = open(sys.argv[1], 'rb').read()
    base, secs = load_sections(d)

    def off2va(off):
        for _n, va, _vs, ra, rs in secs:
            if ra <= off < ra + rs:
                return base + va + off - ra
        return None

    text = next(s for s in secs if s[0] == '.text')
    for arg in sys.argv[2:]:
        if arg.startswith('0x'):
            targets = [int(arg, 16)]
        else:
            targets = []
            i = d.find(arg.encode())
            while i >= 0:
                targets.append(off2va(i))
                i = d.find(arg.encode(), i + 1)
        for t in targets:
            print('== %s @ 0x%X' % (arg, t))
            _n, _va, _vs, ra, rs = text
            for p in range(ra, ra + rs - 7):
                rel = struct.unpack_from('<i', d, p)[0]
                if off2va(p) + 4 + rel == t:
                    print('   referenced at VA 0x%X (preceding bytes: %s)' % (off2va(p) - 3, d[p - 3:p].hex()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
