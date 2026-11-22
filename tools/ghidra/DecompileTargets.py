# Decompiles selected functions without running Ghidra's full auto-analysis
# (sdhdship.exe is 37 MB and the full analysis runs out of memory).
#
# Usage (through decompile.bat / pyghidra.ghidra_launch ... AnalyzeHeadless ... -postScript):
#   DecompileTargets.py <output.c> <depth> <target>...
#   target = RVA or VA in hex, optionally "address=name" to name the function.
# From every target it follows direct calls up to <depth> levels, creates the functions and
# writes the pseudo-C of all of them to a single file.
# @runtime PyGhidra

from ghidra.app.cmd.disassemble import DisassembleCommand
from ghidra.app.cmd.function import CreateFunctionCmd
from ghidra.app.decompiler import DecompInterface
from ghidra.program.model.symbol import SourceType

args = list(getScriptArgs())
out_path, depth = args[0], int(args[1])
prog = currentProgram
base = prog.getImageBase().getOffset()
space = prog.getAddressFactory().getDefaultAddressSpace()
listing = prog.getListing()


def to_addr(text):
    v = int(text, 16)
    if v < base:
        v += base
    return space.getAddress(v)


def ensure_function(a):
    f = getFunctionAt(a)
    if f is None:
        DisassembleCommand(a, None, True).applyTo(prog, monitor)
        CreateFunctionCmd(a).applyTo(prog, monitor)
        f = getFunctionAt(a)
    return f


def callees(f):
    res = []
    mem = prog.getMemory()
    for ins in listing.getInstructions(f.getBody(), True):
        if ins.getFlowType().isCall():
            for ref in ins.getReferencesFrom():
                t = ref.getToAddress()
                block = mem.getBlock(t) if t.isMemoryAddress() else None
                if block is not None and block.isExecute():
                    res.append(t)
    return res


queue, seen, order = [], set(), []
for t in args[2:]:
    name = None
    if '=' in t:
        t, name = t.split('=', 1)
    a = to_addr(t)
    f = ensure_function(a)
    if f is not None and name:
        f.setName(name, SourceType.USER_DEFINED)
    queue.append((a, 0))

while queue:
    a, d = queue.pop(0)
    if a in seen:
        continue
    seen.add(a)
    f = ensure_function(a)
    if f is None:
        continue
    order.append(f)
    if d < depth:
        for c in callees(f):
            if c not in seen:
                queue.append((c, d + 1))

dec = DecompInterface()
dec.openProgram(prog)
with open(out_path, 'w', encoding='utf-8') as fp:
    fp.write('// Decompiled functions: %d (depth %d)\n\n' % (len(order), depth))
    for f in order:
        r = dec.decompileFunction(f, 120, monitor)
        rva = f.getEntryPoint().getOffset() - base
        fp.write('// ===== %s  VA=%s  RVA=0x%X =====\n' % (f.getName(), f.getEntryPoint(), rva))
        if r is not None and r.decompileCompleted():
            fp.write(r.getDecompiledFunction().getC())
        else:
            fp.write('// (failed: %s)\n' % (r.getErrorMessage() if r else '?'))
        fp.write('\n')
print('DecompileTargets: %d functions -> %s' % (len(order), out_path))
