# SkookumScript binary format in Sleeping Dogs: Definitive Edition

This file documents the compiled script format: `Data\Scripts\Classes.skoo-bin` plus `Data\Scripts\Class[<id>].skoo-bin`, stored inside `Global.big`. It applies to the Definitive Edition only.

- All values are little-endian.
- RVAs refer to `sdhdship.exe` (2017 build, image base `0x140000000`). They are the functions that read each structure. They were found with Ghidra, as described in [Reproducing the research](#reproducing-the-research).

## Symbols

A symbol (`ASymbol`) is 4 bytes: the **CRC-32/MPEG-2 of the exact, case-sensitive text**.

- The CRC uses poly `0x04C11DB7`, init `0xFFFFFFFF`, no reflection and no final xor.
- `Object` = `0x30E28CCD`. It is the root of the class hierarchy.
- `0xFFFFFFFF` is the null symbol.
- Some real symbols start with a space, for example `' Social_Assist'` = `0x96812AD2`.
- File names inside `.big` archives use the same CRC on the **upper-cased** path.

## Type reference: 5 bytes (`SSClassDescBase::from_binary_ref`, 0x116830)

A type reference is `u8 kind` + `u32 value`:

| kind | meaning | u32 |
|---|---|---|
| 0 | class | class name symbol |
| 1 | metaclass (`<Class>`) | class name symbol |
| 2 | typed class (`List{T}`) | index into the typed class table |
| 3 | invokable class (closure signature) | index into the invokable table |
| 4 | class union (`<A\|B>`) | index into the union table |

## `Classes.skoo-bin`

Loaded by `SkookumMgr::LoadCompiledBinary` (0x4E2730). The version check is at 0x11EA90; the body is read by `SSBrain::assign_binary` (0x10F3A0).

**Header**

```
u32  ?
u32  code id = 0x1CDEC0CB
u32  folder checksum
u32  file checksum
u32  allocation bytes
u32  debug bytes
u32  class count
```

**Class hierarchy**, recursive from `Object` (0x111490):

```
u32 name, u32 flags, u16 subclass count, then each subclass
```

**Global type tables**

```
u32 typed count
u32 invokable count
u32 union count
unions:     common ref (5), u8 n, n x ref (5)
typed:      u32 class, item ref (5)
invokable:  u32 class, parameters, u8 invoke type          (0x111270)
```

**Resident classes**: the same class list as a `Class[...]` file (below).

The file ends with zero padding.

## `Class[<id>].skoo-bin` (demand-loaded class)

Requested by the script cache (0x4B6600, load callback 0x4B16E0) and read by 0x116180:

```
u32 n
n x ( u32 class id, class members )
```

Some files end with zero padding.

## Class members (`SSClass` vtable slot 0x110)

```
u16 instance data count    x ( u32 name, ref (5) )
u16 class data count       x ( u32 name, ref (5) )
u32 method count           x invokable
u32 class method count     x invokable
u32 coroutine count        x invokable
```

Each **invokable** is:

```
u8 kind
u32 name
parameters
if kind is 0 or 3: typed expression (the body)
```

Invokable kinds:

| kind | meaning |
|---|---|
| 0 | script method |
| 1 | C++ method (func) |
| 2 | C++ method (mthd) |
| 3 | script coroutine |
| 4 | C++ coroutine (func) |
| 5 | C++ coroutine (mthd) |

## Parameters (`SSParameters`, 0x105F30)

1. `u8 n`, then `n` parameters (read by 0x116790). Each parameter starts with `u8 header`, where `kind = header & 3` and `info = header >> 2`.
   - **kind 3, group parameter** (0x104E50): `u32 name`, then `info x ref (5)`.
   - **otherwise, unary parameter** (0x106510): `u32 name`, then `ref (5)`. If `kind == 1` (has a default value), it is followed by `u16 source position` and an expression body whose type is `info`.
2. `u8 n_ret`, then `n_ret x ( u32 name, ref (5) )`: the return parameters.
3. `ref (5)`: the result type.

## Expressions (`SSExpressionBase::from_binary_new`, 0x116250)

A **typed expression** is:

- `u8 type`. Type 0 means no expression (implicit `this`, or an omitted argument).
- `u16 source position`.
- The body for that type.

| # | type | body |
|---|---|---|
| 1 | identifier | `u32 name` |
| 2 | identifier_member | `u32 name`, expr owner |
| 3 | identifier_class_member | `u32 name`, expr owner |
| 4 | object_id | `u32 name`, `u32 class`, `u8 flags` |
| 5 | literal | `u8 kind`, then a payload by kind (see table below) |
| 6 | literal_list | call (constructor, may be 0), `u16 n`, `n x` expr |
| 7/8 | closure method/coroutine | expr receiver, `u32 n` captured symbols, parameters, expr body |
| 9 | closure_member | not supported by the game |
| 10 | bind | expr identifier, expr value |
| 11 | cast (`<>`) | ref (5), expr |
| 12 | conversion (`>>`) | `u32 class`, expr |
| 13 | code `[ ]` | `u32 n` temporaries (u32), `u32 n` statements (expr) |
| 14 | conditional (`if`) | `u32 n x (expr test, expr clause)`; a null test means `else` |
| 15 | case | expr, `u32 n x (expr test, expr clause)` |
| 16 | loop | `u32 name`, expr |
| 17 | loop_exit | `u32 name` |
| 18 | invoke | expr receiver, call |
| 19 | invoke_sync (`%`) | expr, call |
| 20 | invoke_race (`%>`) | expr, call |
| 21 | invoke_cascade | expr, `u8 n x` call |
| 22/23 | invoke closure method/coroutine | expr, `u8 n` args (expr), `u8 n` return args (expr) |
| 24 | instantiate (`Class!ctor()`) | `u32 class`, invoke base without the call-type byte |
| 25 | concurrent_sync (`sync [ ]`) | `u8 n x` expr |
| 26 | concurrent_race (`race [ ]`) | `u8 n x` expr |
| 27 | concurrent_branch (`branch`) | expr |
| 28 | divert | expr |

**Literal kinds** (expression type 5):

| kind | meaning | payload |
|---|---|---|
| 0 | Boolean | u32 |
| 1 | Char? | u32; never used by the game |
| 2 | Integer | i32 |
| 3 | Real | f32 |
| 4 | String | `u32 length` + bytes |
| 5 | Symbol | u32 |
| 6 | Class | u32 |
| 7 | nil | none |
| 8 | this | none |
| 9 | this_class | none |
| 10 | this_code | none |

## Calls (`SSInvokeBase::from_binary_new` 0x116B70, `assign_binary` 0x111330)

```
u8 call type    0 none, 1 method, 2 coroutine
u32 name
u32 scope       class for Class@method, or 0xFFFFFFFF
u8 n arguments  x expr (null = omitted argument)
u8 n returns    x expr
```

## Reproducing the research

The 37 MB executable makes Ghidra's full auto-analysis run out of memory, even with a 9 GB heap. The scripts in `tools/ghidra/` avoid that by importing the executable without analysis and decompiling only the requested functions:

```bat
set GHIDRA_HOME=C:\path\to\ghidra_12.x_PUBLIC
set SD_EXE=C:\path\to\sdhdship.exe
tools\ghidra\decompile.bat out.c 0 116250=SSExpressionBase_from_binary_new 111330=SSInvokeBase_assign_binary
```

`tools/ghidra/find_xrefs.py` finds the code that references a string, for example `Data\Scripts\Classes.skoo-bin`, by scanning for RIP-relative operands. It does not need Ghidra.

The public SkookumScript runtime ([EpicSkookumScript/SkookumScript-Plugin](https://github.com/EpicSkookumScript/SkookumScript-Plugin)) is a later version of the same language. It served as a reference for naming and syntax, but its binary format differs from the one in Sleeping Dogs.
