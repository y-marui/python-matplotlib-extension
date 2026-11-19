# Windows PowerPoint bridge fixtures

Used by `windows-powerpoint-bridge/tests/test_relationship.py` to pin
the Shape-to-OOXML-relationship mapping the bridge relies on. Mirrors
`tests/fixtures/powerpoint_mac/` (issue #77).

| File | Produced by |
| --- | --- |
| `single_figure.pptx` | `generate_originals.py` (reproducible; never opened in PowerPoint) |
| `multi_figure.pptx` | `generate_originals.py` (reproducible; never opened in PowerPoint) |
| `single_figure_powerpoint_resaved.pptx` | `single_figure.pptx`, opened and resaved via COM (`Presentation.SaveCopyAs`) in real PowerPoint for Windows (16.0 / Microsoft 365) by the main session, relayed via the shared notes folder |
| `multi_figure_powerpoint_resaved.pptx` | `multi_figure.pptx`, same as above |
| `multi_figure_powerpoint_reordered.pptx` | `multi_figure.pptx`, opened in real PowerPoint for Windows 16.0 (build 20527), slide 3 moved to the front with `Slide.MoveTo(1)`, then saved (issue #91); slide order is Figure 3, Figure 1, Figure 2 |

Unlike `tests/fixtures/powerpoint_mac/`'s own resaved fixtures, these
two were not captured by this implementing session's own hands: this
session had no direct access to a real Windows machine (per issue
#78's permission boundary), so the main session ran the resave on a
real Windows machine it has access to and relayed the resulting
`.pptx` files back. They were verified in this session before being
committed here: `resolve_ole_part()` resolves every slide of both
files to the exact same `oleObjectN.bin` bytes as the corresponding
original (`single_figure.pptx`/`multi_figure.pptx`), confirming
byte-for-byte preservation across the real resave independently of
what the main session separately reported.

## Regenerating the originals

```bash
uv run python tests/fixtures/powerpoint_windows/generate_originals.py
```

This is deterministic (fixed figure content, fixed PPTX part
timestamps from `embed_pptx()`) and produces byte-identical output
every time, so it is safe to re-run.

## Regenerating the `*_powerpoint_resaved.pptx` fixtures

These are **not** produced by any script in this repository -- there
is no supported way to drive a real, licensed copy of PowerPoint for
Windows from this (macOS) development machine. They were captured via
COM against PowerPoint for Windows 16.0 (Microsoft 365, current as of
2026-11-19), relayed back, and committed as binaries so the test suite
does not depend on a local PowerPoint-for-Windows installation. Only
regenerate them if you deliberately change what `generate_originals.py`
produces, or want to re-validate against a newer PowerPoint release.
The approach used (via a sibling session with real Windows access):

```powershell
$pp = New-Object -ComObject PowerPoint.Application
$pres = $pp.Presentations.Open("$PWD\single_figure.pptx")
$pres.SaveCopyAs("$PWD\single_figure_powerpoint_resaved.pptx", 11)  # ppSaveAsOpenXMLPresentation
$pres.Close()
```

`SaveCopyAs` is used here deliberately instead of `Save`/`SaveAs`: per
the macOS bridge's finding that AppleScript's generic `save` command
rebinds the *live* document window to the new file, this fixture
collection avoids ever doing that to a document a real user might have
had open for another reason -- `SaveCopyAs` writes a copy without
rebinding the open `Presentation` object. This was confirmed not to
rebind anything when actually run.

## What was empirically confirmed against PowerPoint for Windows 16.0

- The embedded `ppt/embeddings/oleObjectN.bin` bytes are preserved
  **byte-for-byte** by PowerPoint's resave -- verified in this session
  for every slide of both fixtures (`resolve_ole_part()`'s resolved
  bytes match the corresponding original exactly), not just the
  single-figure case the main session separately reported.
- PowerPoint for Windows wraps the plain `p:oleObj` this project's
  `save_pptx()` writes in `mc:AlternateContent`, but **asymmetrically**
  -- unlike PowerPoint for Mac's two structurally identical copies:
  `mc:Choice` (`Requires="v"`) holds a *minimal* `p:oleObj` with only
  `<p:embed/>` (no `<p:pic>` fallback image); `mc:Fallback` holds the
  *full* one with both `<p:embed/>` and `<p:pic>`. Both agree on
  `name`, `r:id`, and `progId`.
- The slide's relationship IDs appear out of numeric order in
  `slideN.xml.rels` (e.g. `rId3` listed before `rId2` before `rId1`),
  confirming the resolver is right to match by `Id` value rather than
  assume any positional/sequential order.
- `[Content_Types].xml`'s one `Default Extension="bin"` entry (content
  type `application/vnd.openxmlformats-officedocument.oleObject`) is
  preserved unchanged, same as the original and same as PowerPoint for
  Mac's own resave.

## Not yet confirmed

- Only tested against PowerPoint for Windows 16.0 (Microsoft 365,
  current as of 2026-11-19). Not tested against older perpetual-license
  PowerPoint for Windows versions.
