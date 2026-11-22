# Sleeping Dogs SkookumScript Decompiler

Decompiles the **SkookumScript** scripts of **Sleeping Dogs: Definitive Edition** back into readable source code, one `.sk` file per class. Those scripts hold the missions, side events, objectives, fail conditions and most of the high-level gameplay logic.

- **Complete:** reads 100% of the game's script binaries (`Classes.skoo-bin` + 859 `Class[<id>].skoo-bin`) byte for byte, with no errors. It produces 2,078 classes and about 560,000 expressions.
- **Readable:** methods, coroutines, `if`/`case`/`loop`, `race`/`sync`/`branch`, operators, literals, typed lists and class unions all come out as SkookumScript syntax.
- **Named:** every symbol gets its real name through the community [QSymbolsDictionary](https://github.com/SDmodding/QSymbolsDictionary).
- **No dependencies:** plain Python 3.8+ (tested on 3.10 to 3.13). It reads the scripts straight out of the game's `Global.big`.
- **No game files included.** You need your own copy of the game.

## Quick start

```bat
git clone https://github.com/Yuriinm/sleeping-dogs-skookum-decompiler
cd sleeping-dogs-skookum-decompiler
python sdskoo.py "C:\Program Files (x86)\Steam\steamapps\common\SleepingDogsDefinitiveEdition" output
```

Point the first argument at the folder that contains `sdhdship.exe` and `Global.bix`. The first run downloads the symbol dictionary (about 7 MB) into a cache folder. A full run takes about 10 seconds.

```
Reading scripts from ...\Global.bix
2078 classes in the hierarchy, 859 class files, 39 typed classes, 0 closure types, 70 unions
Wrote 2078 classes to output
Unnamed symbols: 0
```

You can also install it as a command:

```bat
pip install .
sdskoo "<game folder>" output
```

## Example output

From the mission class `AM2_Drive`, coroutine `_gameslice_main`:

```
data().i_amanda: SpawnPoint.spawn('AMMission-spAmanda')<>Character
data().i_amanda.set_faction('TRIAD_WINSTON')
enable_objective("M_AM_Get_Car")
race
[
  _wait_infinite
  [
    World.c_player._wait_take_out_vehicle
    World.c_player._wait_until_using_vehicle_any
  ]
]
_wait(0.5)
```

## Options

| Option | What it does |
|---|---|
| `source` | Game folder, `Global.bix`, or a folder with extracted `.skoo-bin` files |
| `out` | Output folder for the `.sk` files |
| `--class NAME` | Decompile only this class, by name or hex id. Can be repeated. |
| `--list` | List all classes with their member counts and exit |
| `--extract DIR` | Also save the raw `.skoo-bin` files |
| `--names FILE` | Extra name list. Can be repeated. Accepts three line formats: `0xHASH name`, `HASH<TAB>name`, or plain words. |
| `--offline` | Do not download the dictionary. Unknown names show as `sym_XXXXXXXX`. |
| `-q` | Quiet |

The output folder also gets two extra files:
- `_hierarchy.txt`: the full class tree.
- `_unnamed_symbols.txt`: hashes that had no name, if any.

## How it works

The compiled format is not documented anywhere. It was recovered from the game executable (`sdhdship.exe`) with Ghidra, by decompiling the routines that load the scripts:
- `SSExpressionBase::from_binary_new` (28 expression types)
- `SSInvokeBase::assign_binary`
- `SSParameters`
- `SSClassDescBase::from_binary_ref`
- `SSBrain::assign_binary`

Each piece was then checked against every script file in the game.

The full specification is in **[FORMAT.md](FORMAT.md)**. It covers symbols, type references, the class hierarchy, members, parameters, every expression type and calls, with the address of each routine. The helper scripts used for the research are in `tools/ghidra/`.

## Limitations

- **No original comments or formatting:** these are not stored in the binary, so the code is regenerated from the expression tree. The binary does keep the source position of every expression, but the decompiler does not use it yet.
- **Bindings:** a binding is printed as `name: value`, which is how the binary stores it. The original source may have used `!name: value` (new temporary) or `name := value`.
- **Operators** such as `+`, `:=`, `=` and `and` are rebuilt from the method calls they compile to (`add`, `assign`, `equal?`…).
- **Edition:** only the Definitive Edition is supported. The 2012 original uses an older script binary (`0x16DEC0CB`) with different numbering.
- **One-way:** it does not recompile `.sk` files back into `.skoo-bin`.

## Tests

```bat
python -m unittest discover -s tests
```

The tests build small synthetic binaries, so they run without the game.

## Credits

- [SDmodding](https://github.com/SDmodding) for QSymbolsDictionary (symbol names), the TheoryEngine and SDK research and the rest of the Sleeping Dogs modding tools.
- [EpicSkookumScript/SkookumScript-Plugin](https://github.com/EpicSkookumScript/SkookumScript-Plugin), the public runtime of a later SkookumScript version, used as a syntax reference.
- [Ghidra](https://github.com/NationalSecurityAgency/ghidra).

## Legal

This project contains no game code or assets. It reads files from a copy of the game you own, for study and modding. Sleeping Dogs is a trademark of Square Enix. This project is not affiliated with Square Enix or United Front Games. Released under the [MIT License](LICENSE).
