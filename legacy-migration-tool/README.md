# legacy-migration-tool

**Deprecated, migration-only. Not a general-purpose figure editor or a
supported way to work with legacy figures day to day.**

This is a separately distributed command-line tool that converts a
trusted, historical `.plt.pdf` file — one containing a `dill`-serialized
live Matplotlib `Figure` object, from before
[matplotlib-extension](../README.md) adopted its current safe, data-only
`.mpl.png`/`.mpl.pdf`/`.mpl.svg`/`.ole` format — into that safe format,
one time, so the figure can later be opened with the main package's
ordinary `loadfig()`.

It is intentionally kept out of the main `matplotlib-extension` package:
`dill` is a dependency of **this tool only** and is never a dependency of
`matplotlib-extension`, and `matplotlib_extension.loadfig()` never
imports `dill`, `pickle`, or `cloudpickle`, even as a compatibility
fallback. This tool imports `matplotlib_extension` as an ordinary
dependency (the reverse direction — the main package depending on, or
importing, this tool — never happens).

## Security model: read this before using the tool

**A legacy `.plt.pdf` file can contain arbitrary Python code.**
`dill.loads()` runs that code with the full privileges of whatever
process calls it. There is no way to deserialize a `dill` stream "safely"
in general; this tool does not attempt to.

This tool's confirmation prompt and its separation from the main package
are **informed consent, not a security boundary.** They make sure a human
(or an operator who has explicitly opted in) knowingly accepts the risk
before anything runs, and they keep the arbitrary-code-execution surface
out of the package every other user of this project depends on for safe
loading. They do **not** sandbox, contain, or neutralize what the
deserialized code can do once it runs.

**Only convert files you trust**, and run this tool in a disposable
environment:

- networking disabled;
- the input file(s) mounted read-only;
- write access limited to exactly one dedicated output directory (the
  `--output-dir` you pass below) — nowhere else the process can reach
  matters, because the deserialized code can do anything a normal
  process running as you can do.

This tool does **not** enforce any of that sandboxing itself — it has no
way to, from inside the same process that is about to run arbitrary code.
Setting up that disposable environment is the operator's responsibility
every time.

## Installation

From this directory, with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

This installs `dill` and `matplotlib-extension` (from the sibling
directory, via a local path dependency) into this tool's own virtual
environment — never into the main package's environment.

## Usage

```bash
uv run legacy-migration-tool INPUT.plt.pdf [MORE.plt.pdf ...] --output-dir OUT_DIR
```

- One or more legacy input files may be given; each is converted to
  `OUT_DIR/<input stem>.mpl.png`.
- You will be shown an arbitrary-code-execution warning and asked to
  type an exact confirmation phrase, once per invocation, before
  anything is converted — even if you declared several input files.
  Typing anything else aborts without converting anything.
- After writing each `.mpl.png`, the tool re-validates it by running
  `matplotlib_extension.loadfig()` on it in a **separate, freshly
  started subprocess** that never imports `dill` — the same ordinary
  path any other caller would use to open the file. If that validation
  fails, the tool reports the file as failed; a `.mpl.png` is only
  reported as converted once it has round-tripped through the normal
  safe reader, outside the legacy process.

### Non-interactive / automated use

By default, this tool refuses to run without a terminal to prompt in:

```
Refusing to run without a terminal to confirm in. ...
```

For scripted or CI use, you must pass the deliberately long, explicit
flag:

```bash
uv run legacy-migration-tool INPUT.plt.pdf --output-dir OUT_DIR \
    --allow-arbitrary-code-execution
```

**This flag does not make `dill` safe.** It only means you, the
operator, have already decided — outside of this tool, with your own
judgment about the input's trustworthiness and the environment it runs
in — to accept the arbitrary-code-execution risk, and are telling the
tool not to stop and ask interactively. There is no flag that reduces
the risk itself; `--allow-arbitrary-code-execution` only skips the
prompt, never the risk.

There is deliberately no generic `--yes` or `-y` shortcut: the flag name
itself must describe what it is authorizing.

## What this tool will never do

- Import `dill`, `pickle`, or `cloudpickle` anywhere outside this tool's
  own process — and never from `matplotlib_extension` itself.
- Deserialize anything before the confirmation gate in
  `legacy_migration_tool.confirm` has run for the current process.
- Write output through anything other than
  `matplotlib_extension.savefig(fig, ..., editable=True)` — the same
  allowlisted canonical serializer the main package uses everywhere
  else. There is no hand-rolled or weakened output path here.
- Add editing, viewing, or any other day-to-day feature. If you find
  yourself wanting to use this tool regularly instead of as a one-time
  migration step, that is a sign the input should instead be re-created
  from its original source and saved with the main package's normal
  `savefig()`.

## Design

- `legacy_migration_tool.confirm` — the confirmation/refusal gate.
  Never imports `dill`.
- `legacy_migration_tool.convert` — reads the legacy PDF attachment and
  calls `dill.loads()`, **the only place in this project that imports
  `dill`**, and only at call time (not at module import time), so merely
  importing this module does not pull in the risk. Writes output only
  through `matplotlib_extension.savefig(..., editable=True)`.
- `legacy_migration_tool.validate` — a standalone entry point
  (`python -m legacy_migration_tool.validate <path>`) that only calls
  `matplotlib_extension.loadfig()`. It never imports `dill` and is run
  as its own subprocess by the CLI, so the post-conversion check happens
  outside the process that did the legacy deserialization.
- `legacy_migration_tool.cli` — wires the above together: confirm once,
  then convert and validate each declared input file.

## Related reading

- The main package's [`docs/EDITABLE_FORMAT.md`](../docs/EDITABLE_FORMAT.md)
  "Legacy Files" and "Compatibility" sections describe the trust boundary
  this tool sits outside of.
- [Issue #35](https://github.com/y-marui/python-matplotlib-extension/issues/35)
  tracks this tool.
