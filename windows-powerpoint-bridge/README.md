# windows-powerpoint-bridge

**Windows-only, extraction-only.** This is a separately distributed
command-line tool, not a dependency of the main `matplotlib-extension`
package (the reverse direction never happens: the main package never
imports or depends on this tool). It mirrors
[`macos-powerpoint-bridge/`](../macos-powerpoint-bridge/) (issue #77):
same extraction-only boundary, same OOXML relationship resolver, a
different OS-automation layer (COM instead of AppleScript).

It copies the native `figure.mpl.png` out of the embedded OLE object
that is currently selected in a real, running PowerPoint for Windows,
into a destination file you choose. That object is the one
[`save_pptx()`](../README.md) embeds per slide. This tool never
restores a `Figure`, never provides an in-place editing UI, never
executes anything embedded in the presentation, and never uploads the
presentation anywhere. See the main package's
[`docs/EDITABLE_FORMAT.md`](../docs/EDITABLE_FORMAT.md) "OLE Boundary"
section for the trust boundary this tool sits inside of.

## Why this tool exists (it is not a thin wrapper around a PowerPoint export verb)

PowerPoint's own `Shape.Export(path, ppShapeFormatPNG)` -- the
COM/generic equivalent of right-click -> "Save as Picture" -- was
tested against a real embedded OLE Package object produced by
`save_pptx()`, opened in a real PowerPoint for Windows. It reports
success, but **does not preserve the native file**: it produced a
41,715-byte re-rendered PNG with a different SHA-256 than the real
embedded native file (25,272 bytes), extracted via
`extract_ole_native_png()`. So a standard export is insufficient, and
this extraction-only adapter is necessary. See
[Issue #78](https://github.com/y-marui/python-matplotlib-extension/issues/78)
for the full decision trail.

## What it does, precisely

1. Reads PowerPoint's current selection via read-only COM (never
   `Dispatch()`, which would launch a new, empty instance --
   `GetActiveObject("PowerPoint.Application")` only connects to one
   already running). If the selection is not exactly one shape on
   exactly one slide, it refuses.
2. Requires the presentation to have no unsaved changes
   (`Presentation.Saved`). It never asks PowerPoint to export or
   "Save As" a copy of the live document; it takes its own read-only
   filesystem copy of the presentation's own path (`Presentation.FullName`)
   instead -- the same reasoning as the macOS bridge's design, which
   found that driving a save/export API rebinds the live document
   window.
3. Resolves the selected shape to exactly one embedded OLE part by
   walking the package's own OOXML relationships (slide list → slide
   part → slide relationships → embedded part) -- the same resolver
   module the macOS bridge uses, ported near-verbatim since it is pure
   OOXML parsing with no OS dependency. Every relationship type,
   content type, shape type, and target is checked against an exact
   allowlist; anything unexpected rejects the whole package.
4. Hands the resolved part's raw bytes to
   `matplotlib_extension.pyplot.extract_editable_png()` -- the same
   validated boundary function the macOS bridge uses -- which performs
   every PNG/OLE signature check and writes the destination file. This
   tool never performs that validation itself.

## Installation

From this directory, with [uv](https://docs.astral.sh/uv/), **on
Windows** (`pywin32` is a Windows-only dependency, declared with a
`sys_platform == "win32"` marker so `uv sync` on macOS/Linux installs
everything except it, for development/testing of the non-COM parts
only):

```bash
uv sync
```

## Usage

In PowerPoint for Windows, select exactly one embedded Figure object
(make sure the presentation has no unsaved changes), then:

```bash
uv run windows-powerpoint-bridge DESTINATION.mpl.png
```

- `DESTINATION.mpl.png` must end in `.mpl.png`.
- By default, the destination is created exclusively (fails if it
  already exists). Pass `--mode w` for an atomic overwrite.
- The written file is an ordinary editable PNG; open it with
  `matplotlib_extension.loadfig()` like any other `.mpl.png`.

## What is confirmed vs. not yet confirmed against real PowerPoint for Windows

Confirmed (against a real Windows machine, relayed through the main
session that has access to it -- see the handoff notes for exact
commands):

- `Shape.Type` for the embedded OLE Package object is exactly `7`
  (`msoEmbeddedOLEObject`).
- `Shape.OLEFormat.ProgID` is exactly `"Package"`.
- `Shape.Export(path, ppShapeFormatPNG)` does **not** preserve the
  native file (see above) -- this is why the tool exists.
- PowerPoint for Windows wraps the slide's `p:oleObj` in
  `mc:AlternateContent` on resave, but *not* the same way PowerPoint for
  Mac does: the two copies are not structurally identical. `mc:Choice`
  holds a minimal `p:oleObj` (`<p:embed/>` only), `mc:Fallback` holds
  the full one (`<p:embed/>` plus the `<p:pic>` fallback image). Both
  agree on `name`/`r:id`/`progId` -- the only three attributes
  `windows_powerpoint_bridge.relationship` actually compares, so this
  asymmetry needed no code change. Confirmed against both the
  single-figure and multi-figure (3-slide) resaved fixtures, now
  committed at `tests/fixtures/powerpoint_windows/*_powerpoint_resaved.pptx`.
- The embedded `oleObjectN.bin` is preserved byte-for-byte across a
  real Windows PowerPoint resave -- confirmed directly in this
  repository's own test suite (`resolve_ole_part()` against the real
  committed fixture resolves to exactly the pre-resave bytes, for every
  slide of both fixtures), not just relayed as a claim.

Also confirmed on a real PowerPoint for Windows (16.0 build 20527,
Microsoft 365), driving the CLI end to end from the same interactive
session (issue #91):

- Slide reordering: after a real `Slide.MoveTo(1)` of slide 3 and a
  save, selecting each slide's shape extracts the right figure
  (`multi_figure_powerpoint_reordered.pptx` is that real file, and
  `test_resolves_the_real_powerpoint_reordered_fixture` pins it).
- `Selection.SlideRange` for a `ppSelectionShapes` selection reports
  exactly one slide with the correct `SlideIndex`.
- Rejection, each failing closed with a `BridgeError` and no output
  file: no selection (`Selection.Type` 0), a slide selection (type 1),
  two shapes selected on one slide, and an unsaved presentation.

**Supported versions**: only PowerPoint for Windows 16.0 as shipped with
Microsoft 365 (build 20527) is verified. Older perpetual-license
versions are out of scope (not tested, not supported); a presentation
whose structure differs from the fixtures fails closed.

## Interactive-session COM access (confirmed)

Confirmed on a real Windows machine ([issue #89](https://github.com/y-marui/python-matplotlib-extension/issues/89)):
run from a process in the same interactive desktop session as
PowerPoint, `GetActiveObject("PowerPoint.Application")` -- both
Windows PowerShell 5.1's `Marshal.GetActiveObject` and pywin32's
`win32com.client.GetActiveObject` -- reads the live selection
(`Selection.Type == 2`, the OLE shape's `Type == 7`, the slide index).
From a different session (SSH/service, session 0) it fails with
`MK_E_UNAVAILABLE` (`0x800401E3`), because the Running Object Table is
per-session; the bridge is meant to be run by the user from their own
desktop session, so that case is out of scope. PowerShell 7 (.NET Core)
has no `Marshal.GetActiveObject`; use Windows PowerShell 5.1 or this
Python tool.

## What this tool will never do

- Deserialize, restore, or construct a `Figure`.
- Provide an in-place Office editing UI, or execute anything embedded
  in the presentation.
- Upload or otherwise transmit the presentation.
- Scan a presentation to guess which embedded object is "probably" the
  one the user meant; it only resolves the one object PowerPoint itself
  reports as selected.
- Write anything other than the one destination file, through anything
  other than `matplotlib_extension.pyplot.extract_editable_png()`.
- Launch a new PowerPoint instance, or call any PowerPoint method that
  saves, exports, or otherwise mutates the live, open document.

## Related reading

- The main package's
  [`docs/EDITABLE_FORMAT.md`](../docs/EDITABLE_FORMAT.md) "Container
  Bindings" and "OLE Boundary" sections.
- [`macos-powerpoint-bridge/README.md`](../macos-powerpoint-bridge/README.md)
  for the architecture this tool mirrors.
- [Issue #78](https://github.com/y-marui/python-matplotlib-extension/issues/78)
  tracks this tool.
