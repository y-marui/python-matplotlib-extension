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

**Not yet confirmed** (see the handoff notes for details and current
status):

- Whether `GetActiveObject` can see an interactively, user-driven
  PowerPoint session's selection from the process that would run this
  tool, or whether Windows session isolation blocks it. **This is the
  one open question that could force a design change** if it comes
  back negative -- see "Fallback if COM can't see an interactive
  selection" below for why it likely still wouldn't block real usage
  even then. Confirmed so far: it fails with `MK_E_UNAVAILABLE`
  (`0x800401E3`) when called from an SSH/automation session (a
  *different* Windows session than the interactive desktop) -- exactly
  the cross-session isolation expected, and not evidence either way
  about same-session use. Tracked as
  [issue #89](https://github.com/y-marui/python-matplotlib-extension/issues/89),
  which needs a session running directly on the Windows machine itself
  to test from within the interactive session.
- `Selection.SlideRange`'s behavior for a `ppSelectionShapes`-type
  selection specifically.
- Slide reordering, against a real "drag slide 3 to the front, then
  resave" pass (covered only by a synthetic test that edits the real
  fixture's `sldIdLst` in memory -- same caveat the macOS bridge's own
  fixtures have).

## Fallback if COM can't see an interactive selection

The empirical check for the open question above is being run from an
automation/SSH session (Windows session 0, a service-type session),
which is a different Windows session than the interactive desktop
session (e.g. session 2) PowerPoint actually runs in -- so
`GetActiveObject` may fail there purely as an artifact of *how that
check is being run*, not of this tool's design. This tool itself is
meant to be run by the end user, from their own interactive session,
at the same time as PowerPoint -- the same session, by construction.
In that deployment, `GetActiveObject` has no cross-session boundary to
cross: a script run from a PowerShell/terminal window the user opened
themselves, in the same desktop session as PowerPoint, should see the
Running Object Table entry PowerPoint registers there. If this still
needs independent confirmation, the way to get it is to have a user
run the check *from inside* that same interactive session (not via
remote automation) -- see the handoff notes for a ready-to-paste
PowerShell snippet for that.

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
