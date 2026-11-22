"""Symbol names: script symbols are stored as 32-bit hashes (CRC-32/MPEG-2 of the exact,
case-sensitive text). Names come from the community QSymbolsDictionary
(https://github.com/SDmodding/QSymbolsDictionary), which is downloaded and cached on first
use, plus any extra name lists the user passes in.

Supported name list formats (auto-detected per line):
  0x0011B394 SomeName        QSymbolsDictionary_list.txt
  0011B394<TAB>SomeName      tab separated hash / name
  SomeName                   plain word (the hash is computed)
"""
import os
import urllib.request

from .bigfile import hash32

QSYMBOLS_URL = 'https://raw.githubusercontent.com/SDmodding/QSymbolsDictionary/main/QSymbolsDictionary_list.txt'
QSYMBOLS_FILE = 'QSymbolsDictionary_list.txt'
NULL_SYM = 0xFFFFFFFF


def cache_dir():
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_CACHE_HOME') \
        or os.path.join(os.path.expanduser('~'), '.cache')
    return os.path.join(base, 'sdskoo')


def ensure_qsymbols(path=None, download=True, log=print):
    """Returns the path of QSymbolsDictionary_list.txt, downloading it if needed."""
    if path:
        return path
    target = os.path.join(cache_dir(), QSYMBOLS_FILE)
    if os.path.exists(target):
        return target
    if not download:
        return None
    os.makedirs(os.path.dirname(target), exist_ok=True)
    log('Downloading the symbol dictionary (~7 MB, SDmodding/QSymbolsDictionary)...')
    tmp = target + '.part'
    try:
        req = urllib.request.Request(QSYMBOLS_URL, headers={'User-Agent': 'sdskoo'})
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, 'wb') as fp:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                fp.write(chunk)
        os.replace(tmp, target)
    except OSError as ex:
        if os.path.exists(tmp):
            os.remove(tmp)
        log('Could not download the dictionary (%s). Names will show as sym_XXXXXXXX.\n'
            'Download it manually from %s and pass it with --names.' % (ex, QSYMBOLS_URL))
        return None
    log('Saved to %s' % target)
    return target


class Symbols:
    """Callable: Symbols(hash) -> name, or 'sym_XXXXXXXX' when unknown, None for the null symbol."""

    def __init__(self):
        self.names = {}
        self.missing = set()

    def add(self, name, h=None, override=False):
        # Names are kept exactly as written: some real symbols start with a space
        # (e.g. ' Social_Assist' = 0x96812AD2).
        if not name:
            return
        if h is None:
            h = hash32(name)
        if override or h not in self.names:
            self.names[h] = name

    def load(self, path):
        with open(path, encoding='utf-8', errors='replace') as fp:
            for line in fp:
                line = line.rstrip('\r\n')
                if not line or line.startswith('#'):
                    continue
                if line.startswith('0x') and ' ' in line:
                    h, _, name = line.partition(' ')
                    try:
                        self.add(name, int(h, 16), override=True)
                    except ValueError:
                        continue
                    self.add(name)            # the dictionary mixes hash styles; add the exact one too
                elif '\t' in line:
                    h, _, name = line.partition('\t')
                    try:
                        self.add(name, int(h, 16), override=True)
                    except ValueError:
                        self.add(line)
                else:
                    self.add(line)
        return self

    def __call__(self, h):
        if h == NULL_SYM:
            return None
        n = self.names.get(h)
        if n is None:
            self.missing.add(h)
            return 'sym_%08X' % h
        return n
