"""SkookumScript binary reader and source printer for Sleeping Dogs: Definitive Edition.

The binary layout was recovered from the game executable (sdhdship.exe, 2017 build,
image base 0x140000000). Relevant routines (RVA):

  SSExpressionBase::from_binary_new   0x116250   28 expression types
  SSInvokeBase::from_binary_new       0x116B70   call type byte (method / coroutine)
  SSInvokeBase::assign_binary         0x111330   name, scope, arguments, return arguments
  SSParameters (binary constructor)   0x105F30
  SSParameterBase::from_binary_new    0x116790
  SSClassDescBase::from_binary_ref    0x116830   type reference: 1 byte kind + 4 bytes
  SSBrain::assign_binary              0x10F3A0   Classes.skoo-bin
  SkookumMgr::LoadCompiledBinary      0x4E2730

See FORMAT.md for the full specification.
"""
import struct

NULL_SYM = 0xFFFFFFFF
CODE_ID = 0x1CDEC0CB          # Classes.skoo-bin version accepted by the Definitive Edition


class FormatError(Exception):
    pass


# --------------------------------------------------------------------------- reader
class Reader:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def u8(self):
        if self.p >= len(self.d):
            raise FormatError('unexpected end of data at 0x%X' % self.p)
        v = self.d[self.p]; self.p += 1; return v

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.p)[0]; self.p += 2; return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v

    def raw(self, n):
        v = self.d[self.p:self.p + n]
        if len(v) != n:
            raise FormatError('unexpected end of data at 0x%X' % self.p)
        self.p += n; return v

    def rest_is_padding(self):
        return not any(self.d[self.p:])


# --------------------------------------------------------------------------- class types
# Type reference kinds (eSSClassType): 0 class, 1 metaclass, 2 typed class (List{T}),
# 3 invokable class (closure signature), 4 class union.
class Types:
    def __init__(self, sym):
        self.sym = sym
        self.typed = []      # (class, item_ref)
        self.invokable = []  # (class, params, invoke_type)
        self.unions = []     # (common_ref, [refs])

    @staticmethod
    def read_ref(r):
        return (r.u8(), r.u32())

    def name(self, ref, depth=0):
        kind, v = ref
        if depth > 8:
            return '?'
        if kind == 0:
            return self.sym(v) or 'Object'
        if kind == 1:
            return '<%s>' % (self.sym(v) or 'Object')
        if kind == 2:
            if v < len(self.typed):
                cls, item = self.typed[v]
                return '%s{%s}' % (self.sym(cls), self.name(item, depth + 1))
            return 'TypedClass#%d' % v
        if kind == 3:
            if v < len(self.invokable):
                _cls, params, itype = self.invokable[v]
                return '%s%s' % ('_' if itype == 1 else '', params_code(params, self, depth + 1))
            return 'InvokableClass#%d' % v
        if kind == 4:
            if v < len(self.unions):
                _common, refs = self.unions[v]
                return '<' + '|'.join(self.name(x, depth + 1) for x in refs) + '>'
            return 'ClassUnion#%d' % v
        return 'ClassType%d#%X' % (kind, v)


# --------------------------------------------------------------------------- expressions
EXPR_NAMES = {
    1: 'identifier', 2: 'identifier_member', 3: 'identifier_class_member', 4: 'object_id',
    5: 'literal', 6: 'literal_list', 7: 'closure_method', 8: 'closure_coroutine',
    9: 'closure_member', 10: 'bind', 11: 'cast', 12: 'conversion', 13: 'code',
    14: 'conditional', 15: 'case', 16: 'loop', 17: 'loop_exit', 18: 'invoke',
    19: 'invoke_sync', 20: 'invoke_race', 21: 'invoke_cascade', 22: 'invoke_closure_method',
    23: 'invoke_closure_coroutine', 24: 'instantiate', 25: 'concurrent_sync',
    26: 'concurrent_race', 27: 'concurrent_branch', 28: 'divert',
}

# Invokable kinds stored before every method / coroutine
INVOKABLE_KINDS = {0: 'method', 1: 'C++ method (func)', 2: 'C++ method (mthd)',
                   3: 'coroutine', 4: 'C++ coroutine (func)', 5: 'C++ coroutine (mthd)'}


class Parser:
    """Turns the binary into a small tuple-based syntax tree."""

    def __init__(self, types, stats=None):
        self.t = types
        self.stats = stats if stats is not None else {}

    # typed expression: u8 kind (0 = none) + u16 source position + body
    def typed(self, r):
        kind = r.u8()
        if kind == 0:
            return None
        src = r.u16()
        return self.expr(kind, r, src)

    def expr(self, kind, r, src=0):
        self.stats[kind] = self.stats.get(kind, 0) + 1
        sym = r.u32
        if kind == 1:
            return ('ident', sym())
        if kind in (2, 3):
            name = sym()
            return ('member' if kind == 2 else 'class_member', name, self.typed(r))
        if kind == 4:
            name = sym(); cls = sym(); flags = r.u8()
            return ('object_id', name, cls, flags)
        if kind == 5:
            return self.literal(r)
        if kind == 6:
            ctor = self.invoke_call(r)
            n = r.u16()
            return ('list', ctor, [self.typed(r) for _ in range(n)])
        if kind in (7, 8):
            recv = self.typed(r)
            captured = [sym() for _ in range(r.u32())]
            params = self.params(r)
            body = self.typed(r)
            return ('closure', kind == 8, recv, captured, params, body)
        if kind == 9:
            raise FormatError('closure_member is not supported by the game (offset 0x%X)' % r.p)
        if kind == 10:
            return ('bind', self.typed(r), self.typed(r))
        if kind == 11:
            ref = self.t.read_ref(r)
            return ('cast', ref, self.typed(r))
        if kind == 12:
            cls = sym()
            return ('conversion', cls, self.typed(r))
        if kind == 13:
            temps = [sym() for _ in range(r.u32())]
            stmts = [self.typed(r) for _ in range(r.u32())]
            return ('code', temps, stmts)
        if kind == 14:
            n = r.u32()
            return ('if', [(self.typed(r), self.typed(r)) for _ in range(n)])
        if kind == 15:
            cmp = self.typed(r)
            n = r.u32()
            return ('case', cmp, [(self.typed(r), self.typed(r)) for _ in range(n)])
        if kind == 16:
            name = sym()
            return ('loop', name, self.typed(r))
        if kind == 17:
            return ('exit', sym())
        if kind in (18, 19, 20):
            recv = self.typed(r)
            call = self.invoke_call(r)
            return ({18: 'invoke', 19: 'invoke_sync', 20: 'invoke_race'}[kind], recv, call)
        if kind == 21:
            recv = self.typed(r)
            calls = [self.invoke_call(r) for _ in range(r.u8())]
            return ('cascade', recv, calls)
        if kind in (22, 23):
            recv = self.typed(r)
            args = [self.typed(r) for _ in range(r.u8())]
            rets = [self.typed(r) for _ in range(r.u8())]
            return ('invoke_closure', kind == 23, recv, args, rets)
        if kind == 24:
            cls = sym()
            call = self.invoke_base(r, 1)
            return ('instantiate', cls, call)
        if kind in (25, 26):
            n = r.u8()
            return ('sync' if kind == 25 else 'race', [self.typed(r) for _ in range(n)])
        if kind == 27:
            return ('branch', self.typed(r))
        if kind == 28:
            return ('divert', self.typed(r))
        raise FormatError('unknown expression type %d at 0x%X' % (kind, r.p))

    def literal(self, r):
        k = r.u8()
        if k == LIT_STR:
            n = r.u32()
            return ('lit', k, r.raw(n).decode('latin-1'))
        if k in (LIT_SYM, LIT_CLASS):
            return ('lit', k, r.u32())
        if k in LIT_FIXED:
            return ('lit', k, None)
        return ('lit', k, r.u32())

    # call: u8 kind (0 none, 1 method, 2 coroutine) + SSInvokeBase
    def invoke_call(self, r):
        kind = r.u8()
        if kind == 0:
            return None
        if kind not in (1, 2):
            raise FormatError('unknown call type %d at 0x%X' % (kind, r.p - 1))
        return self.invoke_base(r, kind)

    def invoke_base(self, r, kind):
        name = r.u32()
        scope = r.u32()
        args = [self.typed(r) for _ in range(r.u8())]
        rets = [self.typed(r) for _ in range(r.u8())]
        return ('call', kind, name, scope, args, rets)

    # parameters: u8 n + params, u8 n_ret + (symbol + type), result type
    def params(self, r):
        plist = []
        for _ in range(r.u8()):
            b = r.u8()
            kind, info = b & 3, b >> 2
            name = r.u32()
            if kind == 3:                                   # group parameter
                plist.append(('group', name, [self.t.read_ref(r) for _ in range(info)]))
            else:                                           # unary parameter
                ref = self.t.read_ref(r)
                default = None
                if kind == 1:                               # with default value (expr type = info)
                    src = r.u16()
                    default = self.expr(info, r, src)
                plist.append(('unary', name, ref, default))
        rets = []
        for _ in range(r.u8()):
            name = r.u32()
            rets.append((name, self.t.read_ref(r)))
        result = self.t.read_ref(r)
        return (plist, rets, result)

    # class members (SSClass vtable +0x110)
    def class_members(self, r):
        cls = {'data': [], 'class_data': [], 'methods': [], 'class_methods': [], 'coroutines': []}
        for key in ('data', 'class_data'):
            for _ in range(r.u16()):
                name = r.u32()
                cls[key].append((name, self.t.read_ref(r)))
        for key in ('methods', 'class_methods', 'coroutines'):
            for _ in range(r.u32()):
                itype = r.u8()
                name = r.u32()
                params = self.params(r)
                body = None
                if itype in (0, 3):                 # written in script
                    body = self.typed(r)
                elif itype not in (1, 2, 4, 5):     # 1/2 and 4/5 are implemented in C++
                    raise FormatError('unknown invokable type %d at 0x%X' % (itype, r.p))
                cls[key].append((itype, name, params, body))
        return cls


def read_brain(data, types, parser):
    """Reads Classes.skoo-bin. Returns (info, hierarchy, resident_classes).
    hierarchy maps class id -> (superclass id or None, flags)."""
    r = Reader(data)
    info = {'prefix': r.u32(), 'code_id': r.u32(), 'checksum_folder': r.u32(),
            'checksum_file': r.u32(), 'alloc_bytes': r.u32(), 'debug_bytes': r.u32()}
    if info['code_id'] != CODE_ID:
        raise FormatError('Classes.skoo-bin has version 0x%08X; only the Definitive Edition '
                          '(0x%08X) is supported' % (info['code_id'], CODE_ID))
    info['class_count'] = r.u32()
    hierarchy = {}

    def walk(parent):
        name = r.u32(); flags = r.u32(); nsub = r.u16()
        hierarchy[name] = (parent, flags)
        for _ in range(nsub):
            walk(name)
    walk(None)
    n_typed, n_inv, n_union = r.u32(), r.u32(), r.u32()
    for _ in range(n_union):
        common = types.read_ref(r)
        refs = [types.read_ref(r) for _ in range(r.u8())]
        types.unions.append((common, refs))
    for _ in range(n_typed):
        cls = r.u32()
        types.typed.append((cls, types.read_ref(r)))
    for _ in range(n_inv):
        cls = r.u32()
        params = parser.params(r)
        types.invokable.append((cls, params, r.u8()))
    classes = read_class_list(r, parser)
    if not r.rest_is_padding():
        raise FormatError('Classes.skoo-bin: %d unread bytes at 0x%X' % (len(data) - r.p, r.p))
    return info, hierarchy, classes


def read_class_list(r, parser):
    """u32 count + count x (u32 class id + members). Used by Class[<id>].skoo-bin files."""
    out = []
    for _ in range(r.u32()):
        cid = r.u32()
        out.append((cid, parser.class_members(r)))
    return out


def read_class_file(data, parser):
    r = Reader(data)
    lst = read_class_list(r, parser)
    if not r.rest_is_padding():          # some files end with alignment zeros
        raise FormatError('%d unread bytes at 0x%X' % (len(data) - r.p, r.p))
    return lst


# --------------------------------------------------------------------------- printer
# Literal kinds, confirmed against the values stored in the game scripts
# (0: only 0/1, 2: small integers and -1, 3: IEEE floats such as 0x3F800000).
# Kind 1 never occurs in the game scripts (most likely Char).
LIT_BOOL, LIT_CHAR, LIT_INT, LIT_REAL, LIT_STR, LIT_SYM, LIT_CLASS = range(7)
LIT_FIXED = {7: 'nil', 8: 'this', 9: 'this_class', 10: 'this_code'}
BINARY_OPS = {
    'assign': ':=', 'add': '+', 'subtract': '-', 'multiply': '*', 'divide': '/',
    'equal?': '=', 'not_equal?': '~=', 'greater?': '>', 'greater_or_equal?': '>=',
    'less?': '<', 'less_or_equal?': '<=', 'and': 'and', 'or': 'or', 'xor': 'xor',
    'nand': 'nand', 'nor': 'nor', 'nxor': 'nxor', 'add_assign': '+=',
    'subtract_assign': '-=', 'multiply_assign': '*=', 'divide_assign': '/=',
}
UNARY_POST = {'increment': '++', 'decrement': '--'}
UNARY_PRE = {'not': 'not ', 'negated': '-'}
IND = '  '


def params_code(p, types, depth=0):
    plist, rets, result = p
    sym = types.sym
    out = []
    for prm in plist:
        if prm[0] == 'group':
            out.append('{%s} %s' % (' '.join(types.name(x, depth) for x in prm[2]), sym(prm[1])))
        else:
            s = '%s %s' % (types.name(prm[2], depth), sym(prm[1]))
            if prm[3] is not None:
                s += ': ' + Printer(types).expr(prm[3], 0)
            out.append(s)
    s = '(' + ', '.join(out)
    if rets:
        s += '; ' + ', '.join('%s %s' % (types.name(t, depth), sym(n)) for n, t in rets)
    s += ')'
    rn = types.name(result, depth)
    if rn not in ('Object', 'InvokedCoroutine'):
        s += ' ' + rn
    return s


class Printer:
    def __init__(self, types):
        self.t = types
        self.sym = types.sym

    def block(self, e, lvl):
        """Prints e as a [ ... ] block (body of a method, if, loop...)."""
        if e is None:
            return '[]'
        if e[0] == 'code':
            return self.code(e, lvl)
        return '[\n' + IND * (lvl + 1) + self.expr(e, lvl + 1) + '\n' + IND * lvl + ']'

    def code(self, e, lvl):
        _, temps, stmts = e
        lines = [IND * (lvl + 1) + '!' + self.sym(t) for t in temps]
        for s in stmts:
            lines.append(IND * (lvl + 1) + (self.expr(s, lvl + 1) if s is not None else 'nil'))
        if not lines:
            return '[]'
        return '[\n' + '\n'.join(lines) + '\n' + IND * lvl + ']'

    def args(self, args, rets, lvl):
        a = ', '.join('' if x is None else self.expr(x, lvl) for x in args)
        while a.endswith(', '):
            a = a[:-2]
        if rets:
            a += '; ' + ', '.join('' if x is None else self.expr(x, lvl) for x in rets)
        return a

    def call(self, c, lvl, recv_code=None):
        _, kind, name, scope, args, rets = c
        n = self.sym(name)
        if scope != NULL_SYM:
            n = '%s@%s' % (self.sym(scope), n)
        if recv_code is not None and not rets:
            if n in BINARY_OPS and len(args) == 1 and args[0] is not None:
                return '%s %s %s' % (recv_code, BINARY_OPS[n], self.wrap(args[0], lvl))
            if n in UNARY_POST and not args:
                return recv_code + UNARY_POST[n]
            if n in UNARY_PRE and not args:
                return UNARY_PRE[n] + recv_code
        a = self.args(args, rets, lvl)
        s = '%s(%s)' % (n, a) if (args or rets or kind == 1) else n
        return s if recv_code is None else '%s.%s' % (recv_code, s)

    def _is_operator(self, e):
        return (e is not None and e[0] == 'invoke' and e[2] is not None
                and self.sym(e[2][2]) in BINARY_OPS)

    def wrap(self, e, lvl):
        s = self.expr(e, lvl)
        return '(' + s + ')' if self._is_operator(e) else s

    def recv(self, e, lvl):
        if e is None:
            return None
        return self.wrap(e, lvl)

    def lit(self, e):
        _, k, v = e
        if k == LIT_BOOL:
            return 'true' if v else 'false'
        if k == LIT_INT:
            return str(struct.unpack('<i', struct.pack('<I', v))[0])
        if k == LIT_REAL:
            f = struct.unpack('<f', struct.pack('<I', v))[0]
            s = repr(round(f, 6))
            return s if ('.' in s or 'e' in s or 'n' in s) else s + '.0'
        if k == LIT_CHAR:
            return "'%s'" % chr(v) if 32 <= v < 127 else 'Char(%d)' % v
        if k == LIT_STR:
            return '"' + v.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'
        if k == LIT_SYM:
            return "'%s'" % (self.sym(v) or '')
        if k == LIT_CLASS:
            return self.sym(v)
        if k in LIT_FIXED:
            return LIT_FIXED[k]
        return 'literal%d(0x%X)' % (k, v or 0)

    def expr(self, e, lvl):
        if e is None:
            return 'this'
        k = e[0]
        sym = self.sym
        if k == 'ident':
            return sym(e[1])
        if k == 'member':
            owner = '' if e[2] is None else self.recv(e[2], lvl) + '.'
            return owner + sym(e[1])
        if k == 'class_member':
            owner = 'this_class' if e[2] is None else self.recv(e[2], lvl)
            return '%s.%s' % (owner, sym(e[1]))
        if k == 'object_id':
            return "%s@'%s'" % (sym(e[2]), sym(e[1]))
        if k == 'lit':
            return self.lit(e)
        if k == 'list':
            return '{%s}' % ', '.join(self.expr(x, lvl) for x in e[2])
        if k == 'closure':
            _, coro, recv, captured, params, body = e
            s = '^_' if coro else '^'
            if recv is not None:
                s = self.expr(recv, lvl) + ' ' + s
            pc = params_code(params, self.t)
            s += (' ' + pc if pc != '()' else '') + ' ' + self.block(body, lvl)
            if captured:
                s = '/* captures: %s */ ' % ', '.join(sym(c) for c in captured) + s
            return s
        if k == 'bind':
            return '%s: %s' % (self.expr(e[1], lvl), self.expr(e[2], lvl))
        if k == 'cast':
            return '%s<>%s' % (self.recv(e[2], lvl) or 'this', self.t.name(e[1]))
        if k == 'conversion':
            return '%s>>%s' % (self.recv(e[2], lvl) or 'this', sym(e[1]))
        if k == 'code':
            return self.code(e, lvl)
        if k == 'if':
            out = ''
            for i, (test, clause) in enumerate(e[1]):
                t = 'else' if test is None else self.expr(test, lvl)
                out += ('if ' if i == 0 else '\n' + IND * lvl) + t + ' ' + self.block(clause, lvl)
            return out or 'if'
        if k == 'case':
            out = 'case ' + self.expr(e[1], lvl)
            for test, clause in e[2]:
                t = 'else' if test is None else self.expr(test, lvl + 1)
                out += '\n' + IND * (lvl + 1) + t + ' ' + self.block(clause, lvl + 1)
            return out
        if k == 'loop':
            n = sym(e[1])
            return 'loop' + (' ' + n if n else '') + ' ' + self.block(e[2], lvl)
        if k == 'exit':
            n = sym(e[1])
            return 'exit' + (' ' + n if n else '')
        if k == 'invoke':
            if e[2] is None:
                return self.recv(e[1], lvl) or 'this'
            return self.call(e[2], lvl, self.recv(e[1], lvl))
        if k in ('invoke_sync', 'invoke_race'):
            op = '%' if k == 'invoke_sync' else '%>'
            return '%s%s%s' % (self.recv(e[1], lvl) or 'this', op, self.call(e[2], lvl))
        if k == 'cascade':
            r = self.recv(e[1], lvl) or 'this'
            inner = '\n'.join(IND * (lvl + 1) + self.call(c, lvl + 1) for c in e[2] if c)
            return '%s.\n%s[\n%s\n%s]' % (r, IND * lvl, inner, IND * lvl)
        if k == 'invoke_closure':
            _, _coro, recv, args, rets = e
            return '%s(%s)' % (self.recv(recv, lvl) or 'this', self.args(args, rets, lvl))
        if k == 'instantiate':
            cls = sym(e[1])
            c = e[2]
            cname = sym(c[2])
            a = self.args(c[4], c[5], lvl)
            if cname == '!':
                return '%s!(%s)' % (cls, a) if a else '%s!' % cls
            return '%s!%s(%s)' % (cls, cname.lstrip('!'), a)
        if k in ('sync', 'race'):
            inner = '\n'.join(IND * (lvl + 1) + self.expr(x, lvl + 1) for x in e[1])
            return '%s\n%s[\n%s\n%s]' % (k, IND * lvl, inner, IND * lvl)
        if k == 'branch':
            return 'branch ' + self.block(e[1], lvl)
        if k == 'divert':
            return 'divert ' + self.block(e[1], lvl)
        return '/* ? %r */' % (k,)


def class_source(cid, members, hierarchy, types, origin):
    """Returns the SkookumScript source text for one class."""
    sym = types.sym
    p = Printer(types)
    parent, flags = hierarchy.get(cid, (None, 0))
    lines = ['// ' + '=' * 76,
             '// Class %s   (superclass: %s)' % (sym(cid), sym(parent) if parent else '-'),
             '// id 0x%08X, flags 0x%X, source: %s' % (cid, flags, origin),
             '// Decompiled from compiled SkookumScript (Sleeping Dogs: Definitive Edition).',
             '// Original comments and formatting are not stored in the binary.',
             '// ' + '=' * 76, '']
    for key, title, prefix in (('data', 'Instance data', '!'), ('class_data', 'Class data', '!!')):
        if members[key]:
            lines.append('// --- %s ---' % title)
            for name, ref in members[key]:
                lines.append('%s%s %s' % (prefix, types.name(ref), sym(name)))
            lines.append('')
    for key, title in (('methods', 'Methods'), ('class_methods', 'Class methods'),
                       ('coroutines', 'Coroutines')):
        if not members[key]:
            continue
        lines.append('// --- %s ---' % title)
        lines.append('')
        for itype, name, params, body in members[key]:
            head = sym(name) + params_code(params, types)
            if key == 'class_methods':
                head = '// (class method)\n' + head
            if body is None:
                lines.append('%s  // %s, no script body' % (head, INVOKABLE_KINDS.get(itype, itype)))
            else:
                lines.append(head)
                lines.append(p.block(body, 0))
            lines.append('')
    return '\n'.join(lines) + '\n'
