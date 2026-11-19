# macOS PowerPoint bridge fixtures

Used by `macos-powerpoint-bridge/tests/test_relationship.py` to pin the
exact Shape-to-OOXML-relationship mapping the bridge relies on, against
both this project's own generator output and real PowerPoint for Mac's
own resave of it.

| File | Produced by |
| --- | --- |
| `single_figure.pptx` | `generate_originals.py` (reproducible; never opened in PowerPoint) |
| `multi_figure.pptx` | `generate_originals.py` (reproducible; never opened in PowerPoint) |
| `single_figure_powerpoint_resaved.pptx` | `single_figure.pptx`, opened and resaved by hand in real PowerPoint for Mac (see below) |
| `multi_figure_powerpoint_resaved.pptx` | `multi_figure.pptx`, opened and resaved by hand in real PowerPoint for Mac (see below) |
| `multi_figure_powerpoint_reordered.pptx` | `multi_figure.pptx`, opened in real PowerPoint for Mac 16.112 (build 16.112.26081010, Microsoft 365), slide 3 moved to the front with AppleScript's generic `move` command, then saved as a copy (issue #91); slide order is Figure 3, Figure 1, Figure 2 |

## Regenerating the originals

```bash
uv run python tests/fixtures/powerpoint_mac/generate_originals.py
```

This is deterministic (fixed figure content, fixed PPTX part
timestamps from `embed_pptx()`) and produces byte-identical output
every time, so it is safe to re-run.

## Regenerating the `*_powerpoint_resaved.pptx` fixtures

These are **not** produced by any script — there is no supported way to
drive a real, licensed copy of PowerPoint for Mac from CI. They were
captured once, by hand, against PowerPoint for Mac **16.112.4**, and
are committed as binaries so the test suite does not depend on a local
PowerPoint installation. Only regenerate them if you deliberately
change what `generate_originals.py` produces, or want to re-validate
against a newer PowerPoint release. Steps:

1. Run `generate_originals.py` (above) to produce fresh originals.
2. Open each original in PowerPoint for Mac, e.g.:
   ```bash
   osascript -e 'tell application "Microsoft PowerPoint" to open (POSIX file "'"$PWD"'/tests/fixtures/powerpoint_mac/single_figure.pptx")'
   ```
3. Resave a copy via AppleScript's generic `save` command, giving it an
   explicit `POSIX file` specifier (a plain string path is silently
   ignored) and the `save as Open XML presentation` format constant:
   ```bash
   osascript -e 'tell application "Microsoft PowerPoint" to save presentation "single_figure.pptx" in (POSIX file "'"$PWD"'/tests/fixtures/powerpoint_mac/single_figure_powerpoint_resaved.pptx") as (save as Open XML presentation)'
   ```
   This is the **only** place in this project that calls PowerPoint's
   `save` command on a document — fixture collection, never the bridge
   itself. It is safe here only because the "live document" being
   mutated is a disposable one this script just opened for exactly
   this purpose; see `macos-powerpoint-bridge/README.md`'s
   "Design decisions" for why the bridge itself never does this to the
   user's actual live presentation.
4. Close the presentation (`close presentation "..." saving no`) and
   delete any `~$*.pptx` PowerPoint lock file left in this directory.
5. Repeat for `multi_figure.pptx`.

## Regenerating `multi_figure_powerpoint_reordered.pptx`

Also captured by hand, against PowerPoint for Mac **16.112.26081010**
(same 16.112 line as the fixtures above). There is no `move slide`
command in PowerPoint's AppleScript Suite — `slide index` is read-only
— but the generic `move <element> to <location>` command from the
Standard Suite works for a real reorder:

1. Open `multi_figure.pptx` as in step 2 above.
2. Move slide 3 to the front:
   ```bash
   osascript -e 'tell application "Microsoft PowerPoint" to move (slide 3 of active presentation) to before (slide 1 of active presentation)'
   ```
3. Save a copy the same way as step 3 above, as
   `multi_figure_powerpoint_reordered.pptx`. This resave rebinds the
   live window to the new file (see the "save" caveat above), so the
   *next* command targets the new file's name, not `multi_figure.pptx`.
4. Close (`close presentation "multi_figure_powerpoint_reordered.pptx" saving no`)
   and delete the lock file, as in step 4 above.

As with the `*_powerpoint_resaved.pptx` fixtures, `move` is only ever
used here for fixture collection; the bridge itself never reorders,
edits, or saves the user's live presentation.

**Caveat for any future ad hoc AppleScript against this app:**
`repeat with x in <collection>` (e.g. `slides of thePres`) can hang
indefinitely in PowerPoint for Mac's AppleScript implementation — it
was observed to exceed a 120-second timeout even for a 3-slide
presentation. Use `repeat with i from 1 to (count of <collection>)`
with `item i of <collection>` instead, which returns instantly.

## What was empirically confirmed against PowerPoint 16.112.4

- The embedded `ppt/embeddings/oleObjectN.bin` bytes, and the fallback
  `ppt/media/imageN.png` bytes, are preserved **byte-for-byte** by
  PowerPoint's resave — verified by comparing every slide's pair across
  all four fixtures.
- PowerPoint wraps the plain `p:oleObj` this project's `save_pptx()`
  writes in `mc:AlternateContent`, with two identical copies (one under
  `mc:Choice`, one under `mc:Fallback`), each carrying the same `name`,
  `r:id`, and `progId` attributes as the original.
- The embedded part's relationship id (e.g. `rId2`) is not guaranteed
  stable; only its relationship `Type` is. `macos_powerpoint_bridge`
  resolves by `Type`, never by a hardcoded id.
- `[Content_Types].xml`'s `Default Extension="bin"` entry (content
  type `application/vnd.openxmlformats-officedocument.oleObject`) is
  preserved unchanged.

## What was empirically confirmed against PowerPoint 16.112.26081010 (issue #91)

- Slide reordering: after a real `move slide 3 to before slide 1` and a
  save (`multi_figure_powerpoint_reordered.pptx`), the relationship
  resolver still extracts the right figure for every slide —
  `test_resolves_the_real_powerpoint_reordered_fixture` in
  `macos-powerpoint-bridge/tests/test_relationship.py` pins it, against
  a real reorder rather than only the pre-existing synthetic edit of
  `multi_figure_powerpoint_resaved.pptx`'s own `sldIdLst`.
- Multi-select and zero-select rejection: run against a real,
  live PowerPoint for Mac window (not a mocked `osascript` response),
  `macos_powerpoint_bridge.applescript.read_selection()` raised
  `BridgeError` for both a real two-shape selection (shape duplicated
  via Edit > Duplicate, then selected with AppleScript's `select
  {shape 1, shape 2}`) and a real empty selection
  (`selection type none` after clicking empty canvas).
