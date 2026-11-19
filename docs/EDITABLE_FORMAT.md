# Editable Figure Format

## Status

This document defines format version 1 and figure schema version 3. Both versions are integers and are validated independently. Readers reject unknown versions; they do not guess or fall back to object deserialization.

## Canonical Package

The canonical payload is a ZIP file with stored, uncompressed entries in this order:

1. `manifest.json`
2. `figure.json`
3. zero or more `arrays/NNNNNNNN.npy` entries in lexical order

ZIP metadata is deterministic: the timestamp is `1980-01-01T00:00:00`, entries use fixed regular-file permissions, and no extra fields or comments are written. JSON is UTF-8 with sorted keys, compact separators, no non-finite JSON numbers, and one trailing line feed.

`manifest.json` contains:

- `format`: `org.matplotlib-extension.figure-package`
- `format_version`: canonical package version
- `figure_schema_version`: figure specification version
- `files`: path, media type, byte size, and SHA-256 for every other entry
- `warnings`: stable descriptions of objects skipped while saving

`figure.json` is a data-only tree. It describes the figure, axes, allowlisted artists, text styling, scales, limits, legends, tick locators, and tick formatters. Large numeric values are references to `.npy` entries rather than inline JSON arrays.

NumPy entries have these requirements:

- Writers call `numpy.save(..., allow_pickle=False)`.
- Readers call `numpy.load(..., allow_pickle=False)`.
- Only plain boolean, signed integer, unsigned integer, floating-point, and complex dtypes are accepted.
- Object, structured, string, Unicode, datetime, and timedelta dtypes are rejected.
- Arrays are C-contiguous and canonicalized to little-endian byte order before writing.

## Restore Model

The reader constructs a new exact `matplotlib.figure.Figure`. The file cannot select a module, Python class, callable, backend, or constructor. Restore handlers are compiled into the library and map schema tags to explicit Matplotlib constructors.

The restore model is allowlist-first at every discriminator. There is no denylist fallback, dynamic registry lookup, arbitrary import, or best-effort construction for an unknown container, schema tag, enum, object kind, class, dtype, locator, or formatter. Unsupported live objects can be skipped with stable warnings while saving; unknown serialized values are rejected while loading.

Restoration and editing always occur in a Python process. "Editable" means that a plot saved in one process can be passed to another Python process or console, restored with `loadfig()`, and modified using normal Matplotlib APIs. A container is never an editing runtime and cannot request execution of code.

Schema version 3 supports:

- exact `Figure` and `Axes` classes;
- exact `Line2D` and `Text` classes;
- exact `PathCollection` instances created by `Axes.scatter()`, and exact `AxesImage` instances created by `Axes.imshow()` (see [Scatter and Image Restore](#scatter-and-image-restore));
- exact `Rectangle`, `Circle`, `Polygon`, and `Wedge` patch instances, and exact `ErrorbarContainer` instances created by `Axes.errorbar()` (see [Patch and Errorbar Restore](#patch-and-errorbar-restore));
- basic legends (whose handles may be `Line2D`, exactly-restored `PathCollection`, exactly-restored `Rectangle`/`Circle`/`Polygon`/`Wedge`, and/or exactly-restored `ErrorbarContainer` instances) and figure/axes labels;
- linear, log, symlog, logit, and asinh scale names using Matplotlib's built-in scale selection;
- explicit allowlists for common built-in locators and formatters.

Subclasses and unsupported transforms are skipped while saving and recorded as `UnsupportedFigureWarning` plus manifest warnings. They are never restored by importing their class name. A `PathCollection` or `AxesImage` that does not fit the exact, allowlisted shape described below falls back to the schema version 1 behavior: the artist is skipped with a warning, and a numeric recovery record is stored so `recover_data()` can still return its raw arrays without constructing the artist. A `Rectangle`/`Circle`/`Polygon`/`Wedge` that fails only its own exact-restore guard (a non-data transform, non-scalar alpha, a non-string `linestyle` such as a custom dash tuple, a non-string `hatch`, or, for `Rectangle`, an unsupported `rotation_point`) falls back the same way, with a numeric recovery record built from the same class-specific shape accessors (`get_xy()`/`get_width()`/`get_height()`/`get_angle()`, `.center`/`.radius`, `get_xy()`/`get_closed()`, or `.center`/`.r`/`.theta1`/`.theta2`/`.width`) used for the exact restore path, since those are defined independently of the artist's overall transform. A `Patch` subclass outside this allowlist (for example `Ellipse` or `FancyBboxPatch`) is skipped with a warning and no recovery record, as before. An `ErrorbarContainer` that does not fit the exact, allowlisted shape falls back to leaving its data line, cap `Line2D`s, and bar `LineCollection`s to the ordinary per-artist handling: the data line and caps (plain `Line2D` instances) are saved and restored individually like any other line, while the bar `LineCollection`s are skipped with the same "unsupported collection class" warning as any other unsupported collection type. Future schemas may add more explicit recovery records.

### Scatter and Image Restore

In addition to numeric recovery records, schema version 2 can reconstruct the visible artist itself for two common plot types, each gated by explicit, exact allowlists — never a denylist, dynamic registry lookup, or construction from a file-selected name:

- **`PathCollection` (`Axes.scatter()`):** restored when the collection's offsets use the axes' own `transData` (not a custom offset transform such as `ax.transAxes`), its alpha is a single scalar or `None` (not scatter's optional per-point alpha array), it uses exactly one marker path that matches one of Matplotlib's standard marker symbols (the keys of `matplotlib.markers.MarkerStyle.markers`, the same allowlist already used for `Line2D` markers — identified by comparing the collection's transformed `Path` against each candidate symbol's generated path, since a `PathCollection` does not otherwise retain the marker symbol it was built from), and neither its offsets nor its mapped scalar array (when present) are masked. Offsets, per-point or uniform sizes, linewidths, and resolved edge colors are stored as `.npy` arrays. Face color is stored as either an explicit RGBA array (`"mode": "explicit"`), or, when the collection has a mapped scalar array, as that array plus a colormap name and a linear `Normalize` range (`"mode": "colormap"`). Anything outside this — more than one path, an unrecognized marker, a non-allowlisted colormap, a normalization that is not exactly `matplotlib.colors.Normalize`, a non-`transData` offset transform, a masked value, or an array-valued alpha — falls back to a numeric recovery record instead.
- **`AxesImage` (`Axes.imshow()`):** restored when its transform's branch contains the axes' `transData` (checked with `Transform.contains_branch()`, the same test Matplotlib's own `imshow()` uses to decide whether to autoscale the data limits — rejects a custom transform such as `ax.transAxes`), its alpha is a single scalar or `None` (not `imshow()`'s optional per-pixel 2D alpha array), its interpolation name and origin are allowlisted, and its data is not masked. The data array is stored as a `.npy` entry together with `extent`. For 2D data, a colormap name and linear `Normalize` range are stored (`"mode": "colormap"`); for RGB(A) data (a trailing dimension of 3 or 4), no colormap is needed (`"mode": "rgb"`). Anything outside this — a non-allowlisted colormap, a normalization that is not exactly `Normalize`, data that is neither 2D nor RGB(A), a non-`transData` transform, masked data, or an array-valued alpha — falls back to a numeric recovery record instead.

Both restore paths call the normal `Axes.scatter()` / `Axes.imshow()` Matplotlib APIs with the recovered, validated arguments — the same approach `Line2D` restore uses with its constructor — rather than manipulating a collection's or image's private attributes directly.

Colormap names are checked against an explicit allowlist of Matplotlib's own built-in colormaps (`_COLORMAP_NAMES` in `matplotlib_extension/package.py`, captured from Matplotlib 3.11.2's colormap registry before any third-party registration), not against the live, mutable `matplotlib.colormaps` registry's current membership — a third-party package could register additional names into that registry at runtime, and this project never trusts dynamic registry contents as a discriminator. A name passing this allowlist is not enough by itself: a custom `Colormap` can claim an allowlisted name (for example `ListedColormap(["red", "blue"], name="viridis")`), so the live colormap's sampled color mapping and its bad/under/over colors are also compared against the registered built-in of the same name and exact type, and only an exact match is trusted. A name and object that pass this check are then looked up once more via `matplotlib.colormaps[name]` to construct the `Colormap` instance actually passed to the restore call. Interpolation names are checked against an explicit allowlist of Matplotlib's own built-in `AxesImage` interpolation names (`_INTERPOLATION_NAMES`).

A legend (see below) that includes a `PathCollection` handle references it by position in the `collections` list; masks are never partially preserved by discarding mask information silently — a masked `PathCollection`/`AxesImage` always falls back to numeric recovery rather than restoring with the mask dropped.

### Patch and Errorbar Restore

Schema version 3 adds two more exact, allowlisted restore paths, each gated the same way as scatter and image restore: an exact class, a data-coordinate transform, and scalar-only alpha.

- **`Rectangle`/`Circle`/`Polygon`/`Wedge` (`ax.patches`):** restored by calling the class's normal constructor (`Axes.add_patch(Rectangle(...))`, etc.), the same approach used for `Line2D`/`PathCollection`/`AxesImage`. The transform guard checks the artist's *base* `Artist.get_transform()` for exact identity with `ax.transData` — not the `Patch.get_transform()` the artist exposes, which always composes the patch's own local `get_patch_transform()` (its bbox/rotation shape transform) with whatever transform was actually set. Checking the composed result with `Transform.contains_branch()` (the approach used for `AxesImage`) would be unreliable here: that extra local composition can make it structurally equal part of `ax.transData`'s own chain (for example when both happen to route through the same figure pixel bbox) even when the patch was explicitly given a non-data transform such as `transform=ax.transAxes`, producing a false positive. Checking the base, uncomposed transform for exact identity avoids that, consistent with how `Line2D` restore does not need a transform guard at all. Face color, edge color, fill, line style, hatch, line width, alpha, visibility, z-order, and label are read with the same accessors and guards used elsewhere (`_color()`, `_is_scalar_alpha()`), plus two patch-specific points:
  - `linestyle`/`hatch` are stored verbatim as the strings `get_linestyle()`/`get_hatch()` return, and restored via the same constructor kwargs; a custom on/off dash sequence (`set_linestyle((0, (3, 1)))`) makes `get_linestyle()` return a tuple rather than one of Matplotlib's named/short-code strings, which this restore path cannot feed back into the constructor, so that case falls back to numeric recovery instead of being silently flattened to a solid outline.
  - `facecolor`/`edgecolor` are not always stored as the plain resolved RGBA hex: `Patch._set_facecolor()`/`_set_edgecolor()` resolve the literal color `"none"` (or an unfilled `fill=False` face) to alpha 0 regardless of the artist-level alpha, while any other color's alpha channel is overridden to equal that artist alpha when one is set. A resolved alpha of 0 together with a nonzero artist alpha can therefore only come from that `"none"`/unfilled special case — an ordinary color's alpha would have been overridden to the nonzero value instead — so that case is detected and stored as the literal string `"none"` rather than a hex color. Storing the resolved hex unconditionally would round-trip incorrectly: feeding a hex color with a baked-in zero alpha back through `colors.to_rgba(color, alpha)` on restore gets its alpha overridden back to the nonzero artist alpha, turning what was an invisible fill/edge (`facecolor="none", alpha=0.5`) into a visible, half-opaque black one.
- **`ErrorbarContainer` (`Axes.errorbar()`):** `errorbar()` does not add one simple artist — it registers an `ErrorbarContainer` grouping a data `Line2D` (absent when `fmt="none"`), a tuple of cap `Line2D`s, and a tuple of bar `LineCollection`s, some of which also independently appear in `ax.lines`/`ax.collections`. Restoring the container's own data (not its sub-artists piecemeal) requires correlating these back into one call. Saving requires, in addition to the shared alpha guard:
  - an exact `ErrorbarContainer` with a data line present (`fmt="none"`, which omits the data line entirely, is not restorable this way and falls back — see [Compatibility](#compatibility) for why this is an accepted, documented gap rather than a bug);
  - the exact data-coordinate transform (`transform is ax.transData`, not `Transform.contains_branch()`) on the data line, every cap, and every bar independently — `contains_branch()` only checks whether `transData` is reachable within a transform's composition tree, so it would still accept an extra affine step chained onto it (for example `Affine2D().translate(1, 0) + ax.transData` on one bar), silently losing that offset on restore;
  - exactly the `LineCollection` bar(s) and `Line2D` cap(s) that `container.has_xerr`/`has_yerr` and a plain two-sided error bar (no `errorevery` subsampling, no one-sided `lolims`/`uplims`/`xlolims`/`xuplims` limit markers) would produce: bar segment counts matching the data length, solid (non-dashed) bar line style, cap markers exactly `"|"` (x) or `"_"` (y) — a one-sided limit's arrow-shaped cap marker fails this check and falls back, leaving its data line and caps to restore individually as ordinary `Line2D`s (still exact `Line2D` instances) and its bar `LineCollection`(s) to the ordinary "unsupported collection" fallback, consistent with the general `ErrorbarContainer` fallback above;
  - each bar's two segment endpoints sharing the independent coordinate (axis-aligned: an x-error bar's two points share the same y, and vice versa) and bracketing the data point with non-negative extents on both sides — a bar segment edited by hand (moved sideways, or given a negative derived error) fails this check, since `Axes.errorbar()` would otherwise either misplace it or reject the negative error outright and crash the restore;
  - each cap sitting exactly at its bar's corresponding endpoint;
  - uniform color, line width, alpha, z-order, and visibility across every bar, and uniform marker-edge color, size, width, alpha, z-order, and visibility across every cap (a single `errorbar()` call cannot reproduce per-sub-artist overrides).

  `xerr`/`yerr` are stored as `(2, N)` arrays of `[lower_offset, upper_offset]` relative to the data line's own `x`/`y` (which double as the errorbar's `x`/`y` — no separate array entry is needed for them), covering symmetric and asymmetric errors uniformly. `capsize`/`capthick` are read back from the caps' resolved `markersize`/`markeredgewidth`. A cap is a marker, so its visible color is its resolved *marker edge* color (`get_markeredgecolor()`), not `Line2D.get_color()` (the marker face is left unfilled for the `"|"`/`"_"` cap markers) — the two can differ, since `Axes.errorbar()` sets a cap's marker edge color from `ecolor` internally, independently of the generic line `color` it also assigns. That resolved marker-edge color is stored explicitly (`capcolor`) and, on restore, applied with `set_markeredgecolor()` directly on each created cap, rather than passed as a `color=` kwarg to `Axes.errorbar()` — Matplotlib sets a cap's marker edge color from its own internal cap style (derived from `ecolor`) at creation time, not from a `color=` kwarg, so passing it that way would silently fail to apply a cap color that was customized independently of `ecolor`. Restore calls `Axes.errorbar(x, y, xerr=..., yerr=..., fmt="none", ecolor=..., elinewidth=..., capsize=..., capthick=..., alpha=..., zorder=..., visible=..., label=...)` to construct the caps and bars, applies `capcolor` to the caps as above, then separately restores the data line through the same path `Line2D` restore already uses. Assigning that line into the returned container's `.lines` tuple would not be enough: `Container` subclasses `tuple`, so its indexable contents (`container[0]`, which Matplotlib's legend handler reads directly) are fixed at construction and an attribute assignment to `.lines` does not change them. Restore instead constructs a fresh `ErrorbarContainer` around the restored line, the caps, and the bars, and registers it into `ax.containers` in place of the one `errorbar()` added.

## Container Bindings

Every binding stores the exact canonical package bytes:

- PDF: an embedded file named `matplotlib-extension.mplpkg` in a normal Matplotlib PDF.
- PNG: a private ancillary, safe-to-copy `mpFg` chunk immediately before `IEND`.
- SVG: base64 in `mplex:package` metadata under the namespace `https://github.com/y-marui/python-matplotlib-extension`.
- OLE: a generic Package CFB object with one `\x01Ole10Native` stream whose native file is a normal PNG named `figure.mpl.png`; that PNG contains the exact canonical package bytes in its `mpFg` chunk.
- MPLPKG: the canonical ZIP bytes without an outer container.
- PPTX: not a direct binding of the canonical bytes; a minimal, portable OOXML presentation that carries the OLE binding above as an embedded object. See [Portable PPTX Generation](#portable-pptx-generation).

`loadfig()` detects the binding from file signatures and extracts the package before running the same validation and restore path. PPTX is excluded from this detection; see [Portable PPTX Generation](#portable-pptx-generation).

Editable graphics use `.mpl.png`, `.mpl.pdf`, and `.mpl.svg` compound suffixes so users can distinguish them from ordinary graphics by filename. `extract_editable_png(source, destination)` validates and copies an editable PNG source, or unwraps and validates the native editable PNG from an OLE/CFB source. Its destination must end in `.mpl.png`; it accepts no other output format, and its default exclusive-create mode prevents an accidentally selected object from overwriting an existing PNG.

The OLE binding is a portable, passive storage object, not an editing runtime. It does not provide an Office editing UI or run embedded code. To edit it, the user selects the intended object in the presentation application, exports it to a file, and passes that file to a Python process, which extracts the canonical package and calls the same safe restore path as every other binding.

Presentation software may display the rendered PDF, PNG, or SVG and may carry the corresponding OLE object, but presentation software is not the editor. A platform adapter may expose extraction/export for the selected OLE object; it remains outside the canonical format and must only copy bytes to a file. In-place Figure editing remains outside this project's editing model.

For Windows presentation workflows, the OLE Package native file is `figure.mpl.png`. A standard OLE export or extraction-only adapter writes that PNG directly. Locating the intended object is the presentation application's responsibility, not a Python-side scan of the PPTX package.

On macOS, where a Windows OLE verb cannot be the extraction contract, a separately distributed presentation bridge ([`macos-powerpoint-bridge/`](../macos-powerpoint-bridge/)) uses the explicitly selected OLE Shape, read via read-only AppleScript, to resolve that Shape's OOXML relationship in the current presentation's own package, read its internal CFB object, and save only the native `figure.mpl.png`. Shape-to-OOXML identifier mapping is an interoperability boundary and is pinned against fixtures collected from real PowerPoint for Mac (`tests/fixtures/powerpoint_mac/`); it never falls back to guessing among multiple OLE objects. Slides are resolved through the package's own slide-ID list and relationships, not by assuming a slide's AppleScript index matches its slide part's filename suffix, so resolution stays correct after the user reorders slides. The bridge is not part of canonical parsing and does not inspect or restore the Figure package.

The bridge never asks PowerPoint to export or "Save a Copy" of the live, open presentation: an empirical pass against real PowerPoint for Mac found that the generic AppleScript `save` command behaves like interactive File > Save As and rebinds the open document window to the new file, which an extraction-only bridge must never risk doing to the user's live document. It instead requires the presentation to already be fully saved and takes its own read-only filesystem copy of that file.

PPTX package generation and embedding of the OLE bytes are portable OOXML operations and must not require Windows COM, PowerPoint, or OLE activation. Generated packages may be created on macOS, Linux, or Windows. Activation and user-selected export behavior remain platform-specific interoperability surfaces. Extraction bridges positively allowlist the selected Shape type, OOXML relationship/content type and normalized target, CFB stream layout, native filename, and editable PNG binding; all unknown or ambiguous structures fail closed.

### Portable PPTX Generation

`save_pptx(figs, "deck.pptx")` builds a minimal, valid `.pptx` package using only the standard library's `zipfile` and `xml`-compatible string templates; it never requires Windows COM, PowerPoint, or OLE activation, so it runs the same way on macOS, Linux, and Windows. `figs` is a sequence of one or more Matplotlib `Figure` objects (`save_pptx([fig], ...)` for a single figure); each one becomes exactly one slide, in order, so a whole analysis script's figures can be collected into one presentation. PPTX generation is editable-only — there is no non-editable variant — and does not use the `.mpl.*` compound suffix, because, like the OLE binding, it is a passive presentation container rather than one of the directly editable graphics.

Every slide positively allowlists its own structure to exactly:

- one shape: a `p:graphicFrame` whose `a:graphicData` uses the `.../presentationml/2006/ole` URI and holds exactly one `p:oleObj` element with `progId="Package"`;
- exactly one OLE relationship (`.../relationships/oleObject`) and its target, pointing at that slide's own embeddings part `ppt/embeddings/oleObjectN.bin`, which holds the exact CFB bytes produced by `embed_ole()`;
- one rendered fallback image (`ppt/media/imageN.png`), referenced by the shape's `p:pic`/`a:blip`, so PowerPoint displays the figure before the OLE object is activated. This fallback is the same editable PNG bytes passed to `embed_ole()` (the normal PNG rendering with its `mpFg` chunk), not a separately rendered copy, since an editable PNG is already a normal, displayable PNG.

Across the whole package there is exactly one `Default Extension="bin"` content type (`application/vnd.openxmlformats-officedocument.oleObject`), shared by every slide's embeddings part — the allowlist is per-slide-shape, not a cap of one slide per presentation. Slides are numbered `slide1.xml`, `slide2.xml`, ... in the order `figs` was given, each with its own embeddings/media pair at the matching index (`oleObject1.bin`/`image1.png` for slide 1, and so on).

The remaining parts (`[Content_Types].xml`, `_rels/.rels`, `docProps/core.xml`, `docProps/app.xml`, `ppt/presentation.xml` and its relationships, one shared slide master, one shared slide layout, one shared theme) are the fixed, schema-required OOXML scaffolding and carry no figure-specific content; all slides reuse the same master/layout/theme. Each slide's graphic frame is sized independently from its own embedded PNG's pixel dimensions, scaled to fit the slide with a fixed margin and centered; it carries no other layout logic.

This generation path is one-directional: `loadfig()` and `extract_payload()` do not parse `.pptx` packages. Locating and exporting an embedded OLE object from a real presentation is the responsibility of the platform-specific extraction bridges (the Windows export path and the macOS PowerPoint bridge), consistent with [OLE Boundary](#ole-boundary) — Python never scans a PPTX package to guess at an object. A `.pptx` file passed to `loadfig()` is a plain ZIP without the required `manifest.json` entry and so fails safely with `PackageError`, the same as any other invalid container.

Opening the generated file in real PowerPoint for Windows and macOS should be verified manually; this project's test suite validates the package by parsing the generated ZIP/XML structure and round-tripping each slide's embedded OLE bytes through `extract_ole_native_png()`, not by driving PowerPoint itself.

## Resource Limits

Version 1 enforces limits before or during parsing:

- canonical package: 256 MiB;
- JSON entry: 16 MiB;
- individual NumPy entry: 128 MiB;
- array count: 10,000;
- axes count: 1,000;
- artists per supported axes list: 100,000;
- text value: 1,000,000 Unicode code points.

ZIP compression and unlisted, duplicate, absolute, parent-relative, empty, or backslash-separated paths are rejected. Each listed file must match its declared byte size and SHA-256 digest.

## Security Boundary

### Editable File Trust Boundary

Treat every editable figure as untrusted input. Loading a file validates and parses data; it must not execute behavior selected by that file.

The implementation has these non-negotiable rules:

- no live Python object serialization or deserialization;
- no source evaluation, dynamic execution, or file-selected import;
- no file-selected class lookup or arbitrary class construction;
- no automatic restore path for the legacy object-bearing format;
- NumPy loads always use `allow_pickle=False`, and object or structured dtypes are rejected;
- Matplotlib objects are restored only through explicit built-in allowlists;
- container and package paths, counts, sizes, versions, duplicate entries, checksums, and dtypes are validated before restore;
- TeX execution is disabled on restored text objects.

All untrusted discriminators are handled with positive, exact allowlists rather than denylists or fallback discovery. Unknown container bindings, schema tags, enum values, object kinds, classes, dtypes, locators, formatters, and presentation relationship types are rejected. Unsupported live Matplotlib objects may be skipped with a warning during saving, but a file never expands the restore allowlist. Adding a supported type requires an explicit implementation and, where interpretation changes, a schema version change.

### Unsupported Objects

Saving an unsupported exact class, transform, locator, or formatter emits `UnsupportedFigureWarning` and records a warning in the manifest. The object is skipped. A class name in a file is never used to import or construct that class.

This means restore is intentionally lossy outside the documented allowlist. Preserving the security boundary takes precedence over reproducing arbitrary extension objects.

### OLE Boundary

The `.ole` writer creates a generic CFB Package with one `\x01Ole10Native` stream. Loading accepts only that expected stream shape and then validates the same canonical package used by PDF, PNG, and SVG.

The generic container is passive data storage and cannot itself provide an editing UI in PowerPoint. The represented Figure is edited only after exporting the OLE object to a file, passing that file to a separate Python process, and restoring a new `Figure` through the same validated, allowlisted path as the other bindings.

A future Windows extraction/export verb or adapter may copy the selected object's native editable PNG to a user-selected destination. That component must not deserialize Python objects, construct a Figure, invoke a file-selected program, or provide in-place editing. It is an extraction boundary only.

The macOS extraction bridge requests the selected PowerPoint Shape, via read-only AppleScript, and a read-only filesystem copy of the current presentation's own already-saved file, solely to resolve that Shape's OLE relationship and unwrap its native editable PNG. Parsing and extraction happen locally by default. The bridge never uploads the presentation, enumerates unrelated embedded payload contents, deserializes the canonical package, or constructs a Figure. It writes only `figure.mpl.png`, through `matplotlib_extension.pyplot.extract_editable_png()`, for subsequent validation by Python.

Presentation bridges are also allowlist-first. They accept only an explicitly supported selected OLE Shape, OOXML relationship and content type, normalized package-local embedded-object target, the expected CFB Package layout with exactly one `\x01Ole10Native` stream, the native filename `figure.mpl.png`, and a validated editable PNG. Missing, unknown, additional, or ambiguous structure is rejected rather than guessed or generically exported.

### Legacy Files

Older `.plt.pdf` files can contain a live Python object stream. This project does not load that stream, even as a compatibility fallback. Opening such a file with `loadfig()` fails safely.

Any future legacy converter is a separately distributed, deprecated migration tool, not a loader or a dependency of the main package. The main package and `loadfig()` do not import dill, pickle, or cloudpickle. Recognized legacy input is rejected before object deserialization and may only direct the user to migration documentation.

The migration process may deserialize only after displaying an arbitrary-code-execution warning immediately before its first deserialization and receiving one exact confirmation phrase. That confirmation applies once to the declared inputs in that process. Non-interactive execution is denied by default; automation requires a deliberately explicit flag such as `--allow-arbitrary-code-execution`, not a generic `--yes`.

Confirmation and process separation provide informed consent, not safety. Conversion must be limited to trusted files and should run in a disposable environment with networking disabled, inputs mounted read-only, and write access limited to a dedicated output directory. The converter writes an allowlisted canonical `.mpl.png`; a separate normal process then validates it through `loadfig()`. The converter must not become a supported legacy editing path or weaken the canonical reader. Implementation is tracked in [issue #35](https://github.com/y-marui/python-matplotlib-extension/issues/35).

## Compatibility

Adding optional semantics requires a new figure schema version when an old reader could misinterpret them. Changing package layout, integrity rules, or canonical encoding requires a new package version. Readers must reject rather than partially interpret unknown versions.

`format_version` and `figure_schema_version` are each compared with `!=` against the current constant: there is no range check, no "older version accepted" branch, and no type coercion. A manifest whose version field is anything other than the exact current integer — including the right value under the wrong JSON type, such as the string `"1"` or the float `1.0` — is rejected with `PackageError`, not partially interpreted. The two fields are validated independently, and a mismatch on either one rejects the whole file. There is no cross-version upgrade path inside `load_package`/`recover_numeric_data`; the only sanctioned path from an older format is the isolated migration tool described in [Legacy Files](#legacy-files), whose output is validated from scratch by the current reader like any other file.

Figure schema version 2 ([Scatter and Image Restore](#scatter-and-image-restore)) is such a case, even though it only adds new optional `figure.json` fields (`collections` and `images` on each axes entry) and does not change the shape of any existing field. Schema version 1's documented contract is that every exact `PathCollection` and `AxesImage` instance is recorded as a numeric recovery record, and that a `PathCollection`/`AxesImage` not restorable as a real artist is always accompanied by an `UnsupportedFigureWarning` and a manifest warning. Under version 2, a writer that can exactly restore a scatter or image no longer emits that warning or writes a recovery record for it — the artist is written to the new `collections`/`images` fields instead. A version 1 reader ignores those new, unknown fields (its `_restore_axes`/`_axes_spec`-equivalent code never looks at them), so it would silently reconstruct a `Figure` missing the scatter/image, with no warning in the manifest to explain why and no recovery record for `recover_data()` to fall back on — exactly the "old reader could misinterpret" case this rule exists for: a consumer of the documented version 1 contract (for example, code that treats "no warning" as "nothing was skipped") would draw the wrong conclusion. Bumping to schema version 2 makes a version 1 reader fail closed with `PackageError` on these newer files instead, per [Restore Model](#restore-model)'s "readers reject unknown versions; they do not guess or fall back" rule, rather than degrading silently.

Figure schema version 3 ([Patch and Errorbar Restore](#patch-and-errorbar-restore)) bumps for exactly the same reason, for exactly the same shape of change: two more new, optional `figure.json` fields per axes entry (`patches` and `errorbars`), with every existing field's shape unchanged. Before version 3, every `Patch` in `ax.patches` was unconditionally skipped with an `UnsupportedFigureWarning` and no recovery record (`ax.patches` was one of the always-unsupported `unsupported_groups`, alongside `ax.artists`/`ax.tables`, which still apply unchanged); every `LineCollection` created by `Axes.errorbar()`'s bars was skipped the same way as any other unsupported collection class, and its cap/data `Line2D`s were recorded as ordinary, independent lines. A version 2 reader ignores the new `patches`/`errorbars` fields, so it would silently reconstruct a `Figure` missing every exactly-restored `Rectangle`/`Circle`/`Polygon`/`Wedge` and `ErrorbarContainer` (while still restoring an `ErrorbarContainer`'s data line and caps as plain, disconnected `Line2D`s, since those still live in the unchanged `lines` field) — again with no warning and no recovery record for `recover_data()` to explain the gap. Bumping to schema version 3 makes a version 2 reader fail closed on these files instead of silently dropping the patches and disconnecting the errorbar's bars from its data line.

Legacy files containing live Python object streams are outside this format. The library never restores them automatically, after a prompt, or as a compatibility fallback. A separately distributed deprecated migration tool may convert trusted legacy files to `.mpl.png`, but it remains outside the canonical reader and must follow the isolation and confirmation requirements in [Legacy Files](#legacy-files). The resulting file is accepted only after normal signature, package, and allowlist validation.
