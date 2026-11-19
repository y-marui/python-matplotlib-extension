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
