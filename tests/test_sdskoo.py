"""Self-contained tests: they build small synthetic binaries, so no game files are needed.

Run with:  python -m unittest discover -s tests
"""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdskoo.bigfile import hash32, lz_decompress, file_uid  # noqa: E402
from sdskoo.decompiler import (CODE_ID, FormatError, Parser, Types, class_source,  # noqa: E402
                               read_brain, read_class_file)
from sdskoo.symbols import Symbols  # noqa: E402

NAMES = ['Object', 'Foo', 'Integer', 'Real', 'String', 'Boolean', 'None', 'Debug',
         'tick', 'x', 'add', 'greater?', 'print', '_run', '_wait', 'i_count', 'race',
         'assign', 'Bar', 'make', '!']


def h(name):
    return hash32(name)


class W:
    """Little-endian byte writer for building test binaries."""

    def __init__(self):
        self.b = bytearray()

    def u8(self, v):
        self.b += struct.pack('<B', v); return self

    def u16(self, v):
        self.b += struct.pack('<H', v); return self

    def u32(self, v):
        self.b += struct.pack('<I', v); return self

    def sym(self, name):
        return self.u32(h(name))

    def ref(self, cls):
        return self.u8(0).sym(cls)

    def raw(self, data):
        self.b += data; return self


# --- expression builders (each returns bytes of a *typed* expression) ---
def e_ident(name):
    return W().u8(1).u16(0).sym(name).b


def e_int(v):
    return W().u8(5).u16(0).u8(2).u32(v & 0xFFFFFFFF).b


def e_real(v):
    return W().u8(5).u16(0).u8(3).raw(struct.pack('<f', v)).b


def e_str(s):
    return W().u8(5).u16(0).u8(4).u32(len(s)).raw(s.encode()).b


def e_class(name):
    return W().u8(5).u16(0).u8(6).sym(name).b


def call(kind, name, args=(), scope=None):
    w = W().u8(kind).sym(name)
    w.u32(h(scope) if scope else 0xFFFFFFFF)
    w.u8(len(args))
    for a in args:
        w.raw(a)
    w.u8(0)
    return w.b


def e_invoke(recv, c):
    return W().u8(18).u16(0).raw(recv if recv is not None else b'\0').raw(c).b


def e_bind(ident, value):
    return W().u8(10).u16(0).raw(ident).raw(value).b


def e_code(temps, stmts):
    w = W().u8(13).u16(0).u32(len(temps))
    for t in temps:
        w.sym(t)
    w.u32(len(stmts))
    for s in stmts:
        w.raw(s)
    return w.b


def e_if(pairs):
    w = W().u8(14).u16(0).u32(len(pairs))
    for test, clause in pairs:
        w.raw(test if test is not None else b'\0').raw(clause)
    return w.b


def e_race(stmts):
    w = W().u8(26).u16(0).u8(len(stmts))
    for s in stmts:
        w.raw(s)
    return w.b


def e_instantiate(cls, ctor, args=()):
    w = W().u8(24).u16(0).sym(cls).sym(ctor).u32(0xFFFFFFFF).u8(len(args))
    for a in args:
        w.raw(a)
    w.u8(0)
    return w.b


def params(ret='None', args=()):
    """args: list of (type, name) unary parameters without defaults."""
    w = W().u8(len(args))
    for t, n in args:
        w.u8(0).sym(n).ref(t)
    w.u8(0).ref(ret)
    return w.b


def members(data=(), methods=(), class_methods=(), coroutines=()):
    w = W().u16(len(data))
    for name, cls in data:
        w.sym(name).ref(cls)
    w.u16(0)
    for group in (methods, class_methods, coroutines):
        w.u32(len(group))
        for itype, name, prm, body in group:
            w.u8(itype).sym(name).raw(prm)
            if body is not None:
                w.raw(body)
    return w.b


def brain(class_list):
    w = W().u32(0).u32(CODE_ID).u32(0).u32(0).u32(0).u32(0).u32(3)
    # hierarchy: Object -> (Foo, Bar)
    w.sym('Object').u32(0).u16(2)
    w.sym('Foo').u32(0x30).u16(0)
    w.sym('Bar').u32(0).u16(0)
    w.u32(0).u32(0).u32(0)            # typed, invokable, union counts
    w.u32(len(class_list))
    for cid, mem in class_list:
        w.sym(cid).raw(mem)
    w.raw(b'\0' * 8)                  # alignment padding is allowed
    return bytes(w.b)


def symbols():
    s = Symbols()
    for n in NAMES:
        s.add(n)
    return s


FOO = members(
    data=[('i_count', 'Integer')],
    methods=[(0, 'tick', params('None'), e_code(['x'], [
        e_bind(e_ident('x'), e_int(5)),
        e_invoke(e_ident('x'), call(1, 'add', [e_int(1)])),
        e_if([(e_invoke(e_ident('x'), call(1, 'greater?', [e_int(3)])),
               e_code([], [e_invoke(e_class('Debug'), call(1, 'print', [e_str('hi')]))])),
              (None, e_code([], [e_bind(e_ident('x'), e_int(-1))]))]),
    ])),
        (2, 'make', params('Integer', [('Real', 'x')]), None)],
    coroutines=[(3, '_run', params('None'), e_race([
        e_invoke(None, call(2, '_wait', [e_real(0.5)])),
        e_instantiate('Bar', '!'),
    ]))])


class HashTests(unittest.TestCase):
    def test_symbol_hash_matches_game(self):
        # Object is the root of the game's class hierarchy (0x30E28CCD in Classes.skoo-bin)
        self.assertEqual(hash32('Object'), 0x30E28CCD)

    def test_symbols_keep_leading_space(self):
        self.assertEqual(hash32(' Social_Assist'), 0x96812AD2)

    def test_file_uid_is_case_insensitive(self):
        self.assertEqual(file_uid('Data\\Scripts\\Classes.skoo-bin'),
                         file_uid('DATA/SCRIPTS/classes.SKOO-BIN'))


class LZTests(unittest.TestCase):
    def test_literal_and_backref(self):
        stream = bytes([2]) + b'abc' + bytes([2 << 5, 3])    # 'abc' then copy 3 bytes from 3 back
        body = stream
        header = struct.pack('<IHHIIqqq', 0x51434D50, 0, 0, 0x40, 0, 0x40 + len(body), 6, 0)
        buf = header.ljust(0x40, b'\0') + body
        self.assertEqual(lz_decompress(buf), b'abcabc')

    def test_overlapping_copy(self):
        stream = bytes([0]) + b'z' + bytes([3 << 5, 1])     # 'z' then 4 bytes from 1 back
        header = struct.pack('<IHHIIqqq', 0x51434D50, 0, 0, 0x40, 0, 0x40 + len(stream), 5, 0)
        self.assertEqual(lz_decompress(header.ljust(0x40, b'\0') + stream), b'zzzzz')


class DecompilerTests(unittest.TestCase):
    def setUp(self):
        self.sym = symbols()
        self.types = Types(self.sym)
        self.parser = Parser(self.types)

    def decompile(self):
        info, hierarchy, classes = read_brain(brain([('Foo', FOO)]), self.types, self.parser)
        self.assertEqual(len(hierarchy), 3)
        cid, mem = classes[0]
        return class_source(cid, mem, hierarchy, self.types, 'test')

    def test_source_output(self):
        src = self.decompile()
        expected = [
            '// Class Foo   (superclass: Object)',
            '!Integer i_count',
            'tick() None',
            '  !x',
            '  x: 5',
            '  x + 1',
            '  if x > 3 [',
            '    Debug.print("hi")',
            '  else [',
            '    x: -1',
            'make(Real x) Integer  // C++ method (mthd), no script body',
            '_run() None',
            '  race',
            '    _wait(0.5)',
            '    Bar!',
        ]
        for line in expected:
            self.assertIn(line, src)
        self.assertNotIn('sym_', src)

    def test_class_file_with_padding(self):
        data = W().u32(1).sym('Foo').raw(FOO).raw(b'\0\0\0\0').b
        read_brain(brain([]), self.types, self.parser)
        lst = read_class_file(bytes(data), self.parser)
        self.assertEqual(lst[0][0], h('Foo'))

    def test_trailing_garbage_is_an_error(self):
        data = W().u32(1).sym('Foo').raw(FOO).raw(b'\x01').b
        with self.assertRaises(FormatError):
            read_class_file(bytes(data), self.parser)

    def test_wrong_version_is_rejected(self):
        bad = bytearray(brain([]))
        bad[4:8] = struct.pack('<I', 0x16DEC0CB)
        with self.assertRaises(FormatError):
            read_brain(bytes(bad), self.types, self.parser)

    def test_unknown_names_are_reported(self):
        s = Symbols()
        types = Types(s)
        info, hierarchy, classes = read_brain(brain([('Foo', FOO)]), types, Parser(types))
        src = class_source(classes[0][0], classes[0][1], hierarchy, types, 'test')
        self.assertIn('sym_%08X' % h('tick'), src)
        self.assertIn(h('tick'), s.missing)


class SymbolFileTests(unittest.TestCase):
    def test_formats(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'names.txt')
            with open(p, 'w', encoding='utf-8') as fp:
                fp.write('0x%08X  Social_Assist\n' % 0x96812AD2)
                fp.write('%08X\tTabbed\n' % 0x12345678)
                fp.write('PlainWord\n')
            s = Symbols().load(p)
            self.assertEqual(s(0x96812AD2), ' Social_Assist')
            self.assertEqual(s(0x12345678), 'Tabbed')
            self.assertEqual(s(hash32('PlainWord')), 'PlainWord')
            self.assertIsNone(s(0xFFFFFFFF))


if __name__ == '__main__':
    unittest.main()
