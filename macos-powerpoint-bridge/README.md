# macos-powerpoint-bridge

**macOS-only, extraction-only.** This is a separately distributed
command-line tool, not a dependency of the main `matplotlib-extension`
package (the reverse direction never happens: the main package never
imports or depends on this tool).

It copies the native `figure.mpl.png` out of the embedded OLE object
that is currently selected in a real, running PowerPoint for Mac, into
a destination file you choose. That object is the one
[`save_pptx()`](../README.md) embeds per slide. This tool never
restores a `Figure`, never provides an in-place editing UI, never
executes anything embedded in the presentation, and never uploads the
presentation anywhere. See the main package's
[`docs/EDITABLE_FORMAT.md`](../docs/EDITABLE_FORMAT.md) "OLE Boundary"
section for the trust boundary this tool sits inside of.

## What it does, precisely

1. Reads PowerPoint's current selection via read-only AppleScript. If
   the selection is not exactly one shape on exactly one slide, or that
   shape's type is not exactly `shape type embedded OLE control`, it
   refuses.
2. Requires the presentation to already be fully saved (no unsaved
   edits). It never asks PowerPoint to export or "Save As" a copy of
   the live document — see [Design decisions](#design-decisions) for
   why — so it takes its own read-only filesystem copy of the
   presentation's own path instead.
3. Resolves the selected shape to exactly one embedded OLE part by
   walking the package's own OOXML relationships (slide list → slide
   part → slide relationships → embedded part), the same way any OOXML
   consumer would, never by guessing from file-naming conventions.
   Every relationship type, content type, shape type, and target is
   checked against an exact allowlist; anything unexpected rejects the
   whole package.
4. Hands the resolved part's raw bytes to
   `matplotlib_extension.pyplot.extract_editable_png()` — the same
   validated boundary function a Windows export path would use — which
   performs every PNG/OLE signature check and writes the destination
   file. This tool never performs that validation itself.

## Installation

From this directory, with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Usage

In PowerPoint for Mac, select exactly one embedded Figure object (make
sure the presentation has no unsaved changes), then:

```bash
uv run macos-powerpoint-bridge DESTINATION.mpl.png
```

- `DESTINATION.mpl.png` must end in `.mpl.png`.
- By default, the destination is created exclusively (fails if it
  already exists). Pass `--mode w` for an atomic overwrite.
- The written file is an ordinary editable PNG; open it with
  `matplotlib_extension.loadfig()` like any other `.mpl.png`.

## Design decisions

- **Why this never calls PowerPoint's `save` command on the live
  document.** An empirical pass against real PowerPoint for Mac
  (16.112.4) found that the generic
  `save <presentation> in <file> as <format>` AppleScript command
  behaves like interactive File > Save As: it rebinds the open
  document window to the new file, changing its reported name and
  path. That is exactly the kind of live-document mutation an
  extraction-only bridge must never risk. Requiring the presentation to
  already be saved, and reading its own file from disk, avoids the
  live window entirely; this tool only ever performs read-only
  AppleScript queries.
- **Why slides are resolved via `presentation.xml`'s slide list, not
  `slideN.xml` file-naming.** OOXML slide *order* is defined by
  `ppt/presentation.xml`'s `<p:sldIdLst>` plus
  `ppt/_rels/presentation.xml.rels`, not by a slide part's filename
  suffix. After a user reorders slides in PowerPoint, "slide 3" (the
  AppleScript selection's slide index) and the file `slide3.xml` can
  disagree. Resolving through the real relationship chain keeps this
  tool correct after reordering instead of silently extracting the
  wrong figure.
- **Why both a plain and an `mc:AlternateContent`-wrapped `p:oleObj`
  are allowlisted.** This project's own `save_pptx()` writes one plain
  `p:oleObj`. Real PowerPoint for Mac, on save, wraps it in
  `mc:AlternateContent` with two identical copies (one in `mc:Choice`,
  one in `mc:Fallback`) — confirmed by generating fixtures with
  `save_pptx()` and resaving them through real PowerPoint for Mac (see
  `../tests/fixtures/powerpoint_mac/`). Both shapes are accepted only
  when every copy present agrees exactly on name, relationship id, and
  `progId`; any other count, or disagreement between copies, rejects
  the package.

## Confirmed against real PowerPoint (issue #91)

Also confirmed on real PowerPoint for Mac 16.112 (build 16.112.26081010,
Microsoft 365), driving the actual `read_selection()` and relationship
resolver, not mocked responses:

- Slide reordering: after a real "move a slide to the front, then
  save" pass, the relationship resolver still extracts the right
  figure for every slide (`multi_figure_powerpoint_reordered.pptx` is
  that real file, and `test_resolves_the_real_powerpoint_reordered_fixture`
  pins it).
- Rejection, each failing closed with a `BridgeError` and no output
  file: a real two-shape selection (two shapes selected on one slide)
  and a real empty selection (`selection type none`).

See `../tests/fixtures/powerpoint_mac/README.md`'s matching section
for the exact AppleScript/UI steps used.

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

## Related reading

- The main package's
  [`docs/EDITABLE_FORMAT.md`](../docs/EDITABLE_FORMAT.md) "Container
  Bindings" and "OLE Boundary" sections.
- [Issue #77](https://github.com/y-marui/python-matplotlib-extension/issues/77)
  tracks this tool.

## Supported versions

Only PowerPoint for Mac 16.112.x (Microsoft 365) is verified: 16.112.4
for the relationship-mapping fixtures, 16.112.26081010 for the issue
#91 reorder and selection-rejection pass above. Older perpetual-license
versions are out of scope (not tested, not supported); a presentation
whose structure differs from the fixtures fails closed.
