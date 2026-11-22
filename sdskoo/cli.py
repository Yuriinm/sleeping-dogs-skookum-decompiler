"""Command line interface: sdskoo <source> <output folder> [options]

<source> can be:
  * the Sleeping Dogs: Definitive Edition install folder (the one with sdhdship.exe and Global.bix)
  * the Global.bix file itself
  * a folder with already extracted Classes.skoo-bin and Class[<id>].skoo-bin files
"""
import argparse
import os
import sys

from . import __version__
from .bigfile import BigArchive
from .decompiler import (EXPR_NAMES, FormatError, Parser, Types, class_source, read_brain,
                         read_class_file)
from .symbols import Symbols, ensure_qsymbols

BRAIN = 'Data\\Scripts\\Classes.skoo-bin'
CLASS_FILE = 'Data\\Scripts\\Class[%x].skoo-bin'


class Source:
    """Gives access to Classes.skoo-bin and the per-class files, from the game or a folder."""

    def __init__(self, path):
        self.archive = None
        self.folder = None
        if os.path.isdir(path):
            if os.path.exists(os.path.join(path, 'Classes.skoo-bin')):
                self.folder = path
            elif os.path.exists(os.path.join(path, 'Data', 'Scripts', 'Classes.skoo-bin')):
                self.folder = os.path.join(path, 'Data', 'Scripts')
            elif os.path.exists(os.path.join(path, 'Global.bix')):
                self.archive = BigArchive(os.path.join(path, 'Global.bix'))
            else:
                raise SystemExit('error: %s has no Global.bix and no Classes.skoo-bin.\n'
                                 'Point it at the Sleeping Dogs: Definitive Edition install folder.' % path)
        elif path.lower().endswith('.bix'):
            self.archive = BigArchive(path)
        else:
            raise SystemExit('error: %s is not a folder or a .bix file' % path)

    def describe(self):
        return self.archive.bix_path if self.archive else self.folder

    def brain(self):
        if self.archive:
            return self.archive.read_file(BRAIN)
        return open(os.path.join(self.folder, 'Classes.skoo-bin'), 'rb').read()

    def class_files(self, class_ids):
        """Yields (file name, bytes) for every demand-loaded class file that exists."""
        if self.archive:
            for cid in sorted(class_ids):
                path = CLASS_FILE % cid
                try:
                    data = self.archive.read_file(path)
                except KeyError:
                    continue
                yield os.path.basename(path), data
        else:
            for f in sorted(os.listdir(self.folder)):
                if f.startswith('Class[') and f.endswith('.skoo-bin'):
                    yield f, open(os.path.join(self.folder, f), 'rb').read()


def safe_name(s):
    return ''.join(c if c.isalnum() or c in '_-!?' else '_' for c in s)


def build_symbols(args, log):
    sym = Symbols()
    qpath = ensure_qsymbols(None, download=not args.offline, log=log)
    if qpath:
        sym.load(qpath)
    for extra in args.names or []:
        sym.load(extra)
    return sym


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='sdskoo',
        description='Decompiles the SkookumScript scripts of Sleeping Dogs: Definitive Edition '
                    '(missions, events, gameplay logic) into readable .sk source files.',
        epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('source', help='game folder, Global.bix, or folder with .skoo-bin files')
    ap.add_argument('out', nargs='?', help='output folder for the .sk files')
    ap.add_argument('--class', dest='only', action='append', metavar='NAME',
                    help='decompile only this class (name or hex id); can be repeated')
    ap.add_argument('--names', action='append', metavar='FILE',
                    help='extra name list (hash/name pairs or plain words); can be repeated')
    ap.add_argument('--offline', action='store_true',
                    help='do not download the symbol dictionary')
    ap.add_argument('--extract', metavar='FOLDER',
                    help='also save the raw .skoo-bin files to this folder')
    ap.add_argument('--list', action='store_true', help='only list the classes and exit')
    ap.add_argument('-q', '--quiet', action='store_true')
    ap.add_argument('--version', action='version', version='sdskoo ' + __version__)
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):      # never crash on unusual symbol names
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    if not args.out and not args.list and not args.extract:
        ap.error('an output folder is required (or use --list / --extract)')
    log = (lambda *a: None) if args.quiet else print

    src = Source(args.source)
    log('Reading scripts from %s' % src.describe())
    sym = build_symbols(args, log)
    types = Types(sym)
    stats = {}
    parser = Parser(types, stats)

    brain = src.brain()
    info, hierarchy, resident = read_brain(brain, types, parser)
    units = [(cid, m, 'Classes.skoo-bin') for cid, m in resident]
    raw_files = [('Classes.skoo-bin', brain)]
    errors = []
    for fname, data in src.class_files(hierarchy.keys()):
        raw_files.append((fname, data))
        try:
            units += [(cid, m, fname) for cid, m in read_class_file(data, parser)]
        except (FormatError, IndexError, ValueError) as ex:
            errors.append((fname, str(ex)))
        except Exception as ex:  # struct.error and friends: keep going, report at the end
            errors.append((fname, '%s: %s' % (type(ex).__name__, ex)))
    log('%d classes in the hierarchy, %d class files, %d typed classes, %d closure types, %d unions'
        % (len(hierarchy), len(raw_files) - 1, len(types.typed), len(types.invokable), len(types.unions)))

    if args.extract:
        os.makedirs(args.extract, exist_ok=True)
        for fname, data in raw_files:
            with open(os.path.join(args.extract, fname), 'wb') as fp:
                fp.write(data)
        log('Saved %d raw files to %s' % (len(raw_files), args.extract))

    if args.list:
        try:
            for cid, members, origin in sorted(units, key=lambda u: sym(u[0]).lower()):
                n = sum(len(members[k]) for k in ('methods', 'class_methods', 'coroutines'))
                print('%-40s 0x%08X  %4d members  %s' % (sym(cid), cid, n, origin))
        except (BrokenPipeError, OSError):       # output piped into head/more and closed
            return 0
        return 1 if errors else 0

    written = 0
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        wanted = set(args.only or [])
        for cid, members, origin in units:
            name = sym(cid)
            if wanted and not (wanted & {name, '%08X' % cid, '0x%08X' % cid, '%08x' % cid}):
                continue
            text = class_source(cid, members, hierarchy, types, origin)
            with open(os.path.join(args.out, safe_name(name) + '.sk'), 'w', encoding='utf-8') as fp:
                fp.write(text)
            written += 1
        write_hierarchy(os.path.join(args.out, '_hierarchy.txt'), hierarchy, sym)
        with open(os.path.join(args.out, '_unnamed_symbols.txt'), 'w', encoding='utf-8') as fp:
            for h in sorted(sym.missing):
                fp.write('%08X\n' % h)
        log('Wrote %d classes to %s' % (written, args.out))
        if not args.quiet:
            log('Expressions: ' + ', '.join('%s=%d' % (EXPR_NAMES.get(k, k), v)
                                            for k, v in sorted(stats.items())))
            log('Unnamed symbols: %d%s' % (len(sym.missing),
                                           ' (see _unnamed_symbols.txt)' if sym.missing else ''))
    if errors:
        print('%d files could not be read:' % len(errors), file=sys.stderr)
        for f, e in errors[:30]:
            print('  %s: %s' % (f, e), file=sys.stderr)
        return 1
    return 0


def write_hierarchy(path, hierarchy, sym):
    kids = {}
    for c, (p, _fl) in hierarchy.items():
        kids.setdefault(p, []).append(c)
    with open(path, 'w', encoding='utf-8') as fp:
        def dump(c, lvl):
            fp.write('  ' * lvl + sym(c) + '\n')
            for k in sorted(kids.get(c, []), key=lambda x: sym(x).lower()):
                dump(k, lvl + 1)
        for root in kids.get(None, []):
            dump(root, 0)


if __name__ == '__main__':
    sys.exit(main())
