---
name: labview-vi-reader
description: Read and explain NI LabVIEW files (.vi, .ctl, .vit, .vim) directly from disk, including files saved by LabVIEW 2026 - front panel controls, block diagram nodes, wiring/dataflow, constants, comments, subVI and class dependencies. Use this whenever the user points at a LabVIEW VI or control and wants to know what it does, review or debug its logic, document it, compare VIs, find which subVIs or classes a VI uses, or audit a folder of VIs (e.g. myRIO / cRIO / FPGA projects) - even if they only say "看一下這個 VI", "這個 .vi 在做什麼", or paste a .vi path. A .vi file is binary, so reading it with plain file tools shows garbage; use this skill instead of asking for screenshots.
---

# LabVIEW VI reader

A `.vi` is a binary resource container (RSRC) with zlib-compressed object heaps for the
front panel and block diagram. This skill bundles a fork of
[pylabview](https://github.com/mefistotelis/pylabview) that was extended and verified on
LabVIEW 2017-2026 files, plus `vi_summary.py`, which turns one VI into a short Markdown
digest you can reason about. Only Python 3.8+ is needed (Pillow is optional; without it
icon images are just skipped).

## Quick start

```bash
python "<skill-dir>/vi_summary.py" "path/to/My VI.vi"
```

`<skill-dir>` is the folder containing this SKILL.md. The script is read-only: it
extracts to a temp folder and never touches the VI.

Typical output is 1-10k characters. Large VIs can reach ~100k, so for those redirect to
a file and read it in parts rather than flooding the context:

```bash
python "<skill-dir>/vi_summary.py" "Big.vi" > big_summary.md
```

For many VIs (a project folder), loop over them and summarize each; read the small ones
fully and skim headers/dependencies of the rest before diving in.

## Reading the digest

- **Saved in LabVIEW version** - from the `vers` block (e.g. `26.3.1` = LabVIEW 2026 Q3).
- **Description** - the VI documentation text, often the best statement of intent.
- **Front panel** - every control/indicator: `"label" (kind)`. Whether it is a control
  or an indicator is visible from the wires: `FP "x" -> ...` means data flows *out of* the
  terminal (a control); `... -> FP "x"` means an indicator.
  Typedef controls show their `.ctl` file.
- **Block diagram** - an indented tree. Structures (`While Loop#53`, `Case Structure#139`,
  `For Loop`, sequences, event structures) contain their subdiagrams. Case structures list
  each case with its selector values exactly as LabVIEW shows them (`case "apple"`,
  `case "Option 2".."Option 4"`, `case ..-2`, `case No Error`, `case True`,
  `case Default`); other multi-frame structures show `frame N`. `#N` is the object's uid,
  only meaningful for matching items within the same digest.
- **wire: A -> B, C** - one wire, source first, then every sink. Endpoint names:
  - `FP "label"` front panel terminal
  - `const <value> "label"` diagram constant (ints shown as decimal plus hex; strings quoted)
  - `Wait (ms) [prim 1302]#uid[tK]` built-in function, terminal index K. Names come from
    a table built from LabVIEW's palette files (~99% coverage); a bare
    `prim(resID N)` is one not in the table.
  - `Build Array [aBuild]#uid` built-in nodes that LabVIEW stores as their own class
    (bundle/unbundle, index array, format into string, property/invoke nodes, ...).
  - `subVI call (iUse) "Name.vi"#uid[error in (no error)]` subVI / polymorphic VI /
    class method call, named from the VI's link table. Its terminals are shown by the
    callee's control/indicator name (LabVIEW appends defaults in parentheses, e.g.
    `error code (0)`).
  - `<Structure>#uid selTun#n` - a terminal on a structure border: `selTun` case tunnel,
    `caseSel` case selector, `lpTun` loop tunnel, `lSR`/`rSR` left/right shift register,
    `seqTun`/`flatSeqTun` sequence tunnels. The same name appears inside and outside the
    structure, which is how you follow data into and out of it.
- **comment** - free text labels placed on the diagram.
- **Dependencies** - link objects with paths: `VIVI`/`VICC`/`TDCC` = subVIs, typedefs,
  controls; `VILB` = owning library/class; `VIPI`/`FPPI`/`DDPI`/`TCPI`/`DyOM` = LVOOP class
  links. `<vilib>` = LabVIEW's vi.lib, `<userlib>` = user.lib.
- **Parser notes** - blocks pylabview could not decode; their data is simply missing from
  the digest (see limitations).
- **Express VI instance N (embedded code)** - Express VIs (Vision Assistant, DAQ Assistant,
  ...) are called as `subVI call "Express VI instance N"`; their generated code is embedded
  in the caller and summarized at the end under the same name (e.g. IMAQ ColorThreshold
  with its ranges, Particle Analysis). 8-byte constants also show as two I32, since IMAQ
  ranges are `{lower, upper}` clusters.
- **Text encoding** - labels/strings are stored in the saving PC's code page. Big5 (Taiwan),
  GBK and Shift-JIS are auto-detected; force one with `--textcp cp950` if text looks garbled.

### Gaps and how to cope

- **Unnamed prims.** For a bare `prim(resID N)`, infer the function from its terminal
  count, what is wired to it (control/constant labels) and the surrounding logic, and
  say that the identification is an inference.
- **Prim / built-in node terminals** stay as `[tK]` (index). Their names are not stored
  in the VI, and the type labels on them belong to whatever is wired in, so they would be
  misleading. Use the function's known connector (e.g. Wait (ms) t1 = milliseconds to
  wait) and the labels of the wired controls/constants.
- **Property/invoke nodes** show as nodes, but which properties they access is not in
  the digest; grep the `--keep` XML for that node's uid if it matters.
- **Wire geometry / layout.** Positions are omitted on purpose; reason about dataflow,
  not pixels.

## Going deeper

Keep the full extraction when the digest is not enough (exact constant types, property
node details, connector pane, default values):

```bash
python "<skill-dir>/vi_summary.py" "My VI.vi" --keep out_dir
```

`out_dir` then contains `vi.xml` (all blocks: version, description, type table `VCTP`,
link lists `LIvi`/`LIfp`/`LIbd`), `vi_FPHb.xml` (front panel heap), `vi_BDHb.xml`
(block diagram heap), PNG icons and `.bin` blobs. Search them with grep by uid
(`uid="145"`) or class (`class="prim"`, `class="propNode"`, `class="iUse"`) rather than
reading whole files - heaps for real VIs are tens of thousands of lines.

The raw tool is also available: `python -m pylabview.readRSRC -x -i file.vi -m out/x.xml`
(run from `<skill-dir>`). It can rebuild a VI from edited XML (`-c`), but do not
modify a user's VI that way unless they explicitly ask - a rebuilt file that LabVIEW
rejects is a real loss, so work on a copy and keep the original.

## Limitations

- Not decoded (kept raw, invisible in the digest): `VICD` compiled code, a few rare link
  types (`EiVr`, `HpEr`, `HpVr`, `SCVI`, `GUGV` - FPGA/EPICS/shared-variable links; when
  present, that block's whole dependency list is missing), fixed-point min/max values.
- Password-protected block diagrams are still stored in the file, but respect the
  author's intent: tell the user the diagram is protected and ask before analysing it.
- `.llb` libraries, `.lvproj`, `.lvlib`, `.lvclass` are not RSRC VIs; `.lvproj`/`.lvlib`/
  `.lvclass` are XML and can be read directly.
- The LabVIEW 2020 variant of the LVOOP link format is inferred (2019 and 2021 verified).
