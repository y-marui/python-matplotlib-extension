# Editable Figure Format

## Status

This document defines format version 1 and figure schema version 2. Both versions are integers and are validated independently. Readers reject unknown versions; they do not guess or fall back to object deserialization.

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

Schema version 2 supports:

- exact `Figure` and `Axes` classes;
- exact `Line2D` and `Text` classes;
- exact `PathCollection` instances created by `Axes.scatter()`, and exact `AxesImage` instances created by `Axes.imshow()` (see [Scatter and Image Restore](#scatter-and-image-restore));
- basic legends and figure/axes labels;
- linear, log, symlog, logit, and asinh scale names using Matplotlib's built-in scale selection;
- explicit allowlists for common built-in locators and formatters.

Subclasses and unsupported transforms are skipped while saving and recorded as `UnsupportedFigureWarning` plus manifest warnings. They are never restored by importing their class name. A `PathCollection` or `AxesImage` that does not fit the exact, allowlisted shape described below falls back to the schema version 1 behavior: the artist is skipped with a warning, and a numeric recovery record is stored so `recover_data()` can still return its raw arrays without constructing the artist. Future schemas may add more explicit recovery records.

### Scatter and Image Restore

In addition to numeric recovery records, schema version 2 can reconstruct the visible artist itself for two common plot types, each gated by explicit, exact allowlists — never a denylist, dynamic registry lookup, or construction from a file-selected name:

- **`PathCollection` (`Axes.scatter()`):** restored when the collection uses exactly one marker path that matches one of Matplotlib's standard marker symbols (the keys of `matplotlib.markers.MarkerStyle.markers`, the same allowlist already used for `Line2D` markers — identified by comparing the collection's transformed `Path` against each candidate symbol's generated path, since a `PathCollection` does not otherwise retain the marker symbol it was built from). Offsets, per-point or uniform sizes, linewidths, and resolved edge colors are stored as `.npy` arrays. Face color is stored as either an explicit RGBA array (`"mode": "explicit"`), or, when the collection has a mapped scalar array, as that array plus a colormap name and a linear `Normalize` range (`"mode": "colormap"`). A collection that uses more than one path, an unrecognized marker, a non-allowlisted colormap name, or a normalization that is not exactly `matplotlib.colors.Normalize` falls back to a numeric recovery record instead.
- **`AxesImage` (`Axes.imshow()`):** restored when its interpolation name and origin are allowlisted. The data array is stored as a `.npy` entry together with `extent`. For 2D data, a colormap name and linear `Normalize` range are stored (`"mode": "colormap"`); for RGB(A) data (a trailing dimension of 3 or 4), no colormap is needed (`"mode": "rgb"`). A non-allowlisted colormap name, a normalization that is not exactly `Normalize`, or data that is neither 2D nor RGB(A) falls back to a numeric recovery record instead.

Both restore paths call the normal `Axes.scatter()` / `Axes.imshow()` Matplotlib APIs with the recovered, validated arguments — the same approach `Line2D` restore uses with its constructor — rather than manipulating a collection's or image's private attributes directly.

Colormap names are checked against an explicit allowlist of Matplotlib's own built-in colormaps (`_COLORMAP_NAMES` in `matplotlib_extension/package.py`, captured from Matplotlib 3.11.2's colormap registry before any third-party registration), not against the live, mutable `matplotlib.colormaps` registry's current membership — a third-party package could register additional names into that registry at runtime, and this project never trusts dynamic registry contents as a discriminator. A name that passes this allowlist is then looked up once via `matplotlib.colormaps[name]` to construct the actual `Colormap` object. Interpolation names are checked against an explicit allowlist of Matplotlib's own built-in `AxesImage` interpolation names (`_INTERPOLATION_NAMES`).

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

On macOS, where a Windows OLE verb cannot be the extraction contract, a presentation bridge may use the explicitly selected OLE Shape plus a temporary compressed copy of the current PPTX to resolve that Shape's OOXML relationship, read its internal CFB object, and save only the native `figure.mpl.png`. Shape-to-OOXML identifier mapping is an interoperability boundary and requires fixtures from supported PowerPoint versions; it must never fall back to guessing among multiple OLE objects. The bridge is not part of canonical parsing and does not inspect or restore the Figure package.

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

A macOS extraction bridge may request the selected PowerPoint Shape and a temporary OOXML copy of the current presentation solely to resolve that Shape's OLE relationship and unwrap its native editable PNG. Parsing and extraction must happen locally by default. The bridge must not upload the presentation, enumerate unrelated embedded payload contents, deserialize the canonical package, or construct a Figure. It writes only `figure.mpl.png` for subsequent validation by Python.

Presentation bridges are also allowlist-first. They accept only an explicitly supported selected OLE Shape, OOXML relationship and content type, normalized package-local embedded-object target, the expected CFB Package layout with exactly one `\x01Ole10Native` stream, the native filename `figure.mpl.png`, and a validated editable PNG. Missing, unknown, additional, or ambiguous structure is rejected rather than guessed or generically exported.

### Legacy Files

Older `.plt.pdf` files can contain a live Python object stream. This project does not load that stream, even as a compatibility fallback. Opening such a file with `loadfig()` fails safely.

Any future legacy converter is a separately distributed, deprecated migration tool, not a loader or a dependency of the main package. The main package and `loadfig()` do not import dill, pickle, or cloudpickle. Recognized legacy input is rejected before object deserialization and may only direct the user to migration documentation.

The migration process may deserialize only after displaying an arbitrary-code-execution warning immediately before its first deserialization and receiving one exact confirmation phrase. That confirmation applies once to the declared inputs in that process. Non-interactive execution is denied by default; automation requires a deliberately explicit flag such as `--allow-arbitrary-code-execution`, not a generic `--yes`.

Confirmation and process separation provide informed consent, not safety. Conversion must be limited to trusted files and should run in a disposable environment with networking disabled, inputs mounted read-only, and write access limited to a dedicated output directory. The converter writes an allowlisted canonical `.mpl.png`; a separate normal process then validates it through `loadfig()`. The converter must not become a supported legacy editing path or weaken the canonical reader. Implementation is tracked in [issue #35](https://github.com/y-marui/python-matplotlib-extension/issues/35).

## Compatibility

Adding optional semantics requires a new figure schema version when an old reader could misinterpret them. Changing package layout, integrity rules, or canonical encoding requires a new package version. Readers must reject rather than partially interpret unknown versions.

Figure schema version 2 ([Scatter and Image Restore](#scatter-and-image-restore)) is such a case, even though it only adds new optional `figure.json` fields (`collections` and `images` on each axes entry) and does not change the shape of any existing field. Schema version 1's documented contract is that every exact `PathCollection` and `AxesImage` instance is recorded as a numeric recovery record, and that a `PathCollection`/`AxesImage` not restorable as a real artist is always accompanied by an `UnsupportedFigureWarning` and a manifest warning. Under version 2, a writer that can exactly restore a scatter or image no longer emits that warning or writes a recovery record for it — the artist is written to the new `collections`/`images` fields instead. A version 1 reader ignores those new, unknown fields (its `_restore_axes`/`_axes_spec`-equivalent code never looks at them), so it would silently reconstruct a `Figure` missing the scatter/image, with no warning in the manifest to explain why and no recovery record for `recover_data()` to fall back on — exactly the "old reader could misinterpret" case this rule exists for: a consumer of the documented version 1 contract (for example, code that treats "no warning" as "nothing was skipped") would draw the wrong conclusion. Bumping to schema version 2 makes a version 1 reader fail closed with `PackageError` on these newer files instead, per [Restore Model](#restore-model)'s "readers reject unknown versions; they do not guess or fall back" rule, rather than degrading silently.

Legacy files containing live Python object streams are outside this format. The library never restores them automatically, after a prompt, or as a compatibility fallback. A separately distributed deprecated migration tool may convert trusted legacy files to `.mpl.png`, but it remains outside the canonical reader and must follow the isolation and confirmation requirements in [Legacy Files](#legacy-files). The resulting file is accepted only after normal signature, package, and allowlist validation.
