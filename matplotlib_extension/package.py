"""Safe, data-only serialization for editable Matplotlib figures.

The package format is intentionally small and explicit.  It contains canonical
JSON plus NumPy ``.npy`` arrays and never deserializes Python objects.
"""

from __future__ import annotations

import hashlib
import json
import math
import warnings
import zipfile
from collections.abc import Collection, Mapping, Sequence
from io import BytesIO
from typing import Any, Final, cast

import matplotlib
import matplotlib.scale as mscale
import numpy as np
from matplotlib import colors
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.collections import LineCollection, PathCollection
from matplotlib.container import ErrorbarContainer
from matplotlib.figure import Figure
from matplotlib.image import AxesImage
from matplotlib.lines import Line2D
from matplotlib.markers import MarkerStyle
from matplotlib.patches import Circle, Patch, Polygon, Rectangle, Wedge
from matplotlib.scale import (
    AsinhScale,
    LinearScale,
    LogitScale,
    LogScale,
    ScaleBase,
    SymmetricalLogScale,
)
from matplotlib.text import Text
from matplotlib.ticker import (
    AutoLocator,
    AutoMinorLocator,
    FixedFormatter,
    FixedLocator,
    FormatStrFormatter,
    IndexLocator,
    LinearLocator,
    LogFormatter,
    LogFormatterExponent,
    LogFormatterMathtext,
    LogFormatterSciNotation,
    LogLocator,
    MaxNLocator,
    MultipleLocator,
    NullFormatter,
    NullLocator,
    PercentFormatter,
    ScalarFormatter,
    StrMethodFormatter,
)

PACKAGE_FORMAT: Final = "org.matplotlib-extension.figure-package"
PACKAGE_VERSION: Final = 1
FIGURE_SCHEMA_VERSION: Final = 3
MAX_PACKAGE_BYTES: Final = 256 * 1024 * 1024
MAX_JSON_BYTES: Final = 16 * 1024 * 1024
MAX_ARRAY_BYTES: Final = 128 * 1024 * 1024
MAX_ARRAY_COUNT: Final = 10_000
MAX_AXES: Final = 1_000
MAX_ARTISTS_PER_AXES: Final = 100_000
MAX_TEXT_LENGTH: Final = 1_000_000
_LEGEND_LOCATIONS: Final = {
    "best",
    "upper right",
    "upper left",
    "lower left",
    "lower right",
    "right",
    "center left",
    "center right",
    "lower center",
    "upper center",
    "center",
}
_SCALE_TYPES: Final = {
    "asinh": AsinhScale,
    "linear": LinearScale,
    "log": LogScale,
    "logit": LogitScale,
    "symlog": SymmetricalLogScale,
}
# Explicit allowlist of Matplotlib's own built-in colormap names (captured from
# matplotlib 3.11.2's registry before any third-party registration). Never looked
# up dynamically against the live, mutable registry contents for its membership.
_COLORMAP_NAMES: Final = frozenset(
    {
        "Accent",
        "Accent_r",
        "Blues",
        "Blues_r",
        "BrBG",
        "BrBG_r",
        "BuGn",
        "BuGn_r",
        "BuPu",
        "BuPu_r",
        "CMRmap",
        "CMRmap_r",
        "Dark2",
        "Dark2_r",
        "GnBu",
        "GnBu_r",
        "Grays",
        "Grays_r",
        "Greens",
        "Greens_r",
        "Greys",
        "Greys_r",
        "OrRd",
        "OrRd_r",
        "Oranges",
        "Oranges_r",
        "PRGn",
        "PRGn_r",
        "Paired",
        "Paired_r",
        "Pastel1",
        "Pastel1_r",
        "Pastel2",
        "Pastel2_r",
        "PiYG",
        "PiYG_r",
        "PuBu",
        "PuBuGn",
        "PuBuGn_r",
        "PuBu_r",
        "PuOr",
        "PuOr_r",
        "PuRd",
        "PuRd_r",
        "Purples",
        "Purples_r",
        "RdBu",
        "RdBu_r",
        "RdGy",
        "RdGy_r",
        "RdPu",
        "RdPu_r",
        "RdYlBu",
        "RdYlBu_r",
        "RdYlGn",
        "RdYlGn_r",
        "Reds",
        "Reds_r",
        "Set1",
        "Set1_r",
        "Set2",
        "Set2_r",
        "Set3",
        "Set3_r",
        "Spectral",
        "Spectral_r",
        "Wistia",
        "Wistia_r",
        "YlGn",
        "YlGnBu",
        "YlGnBu_r",
        "YlGn_r",
        "YlOrBr",
        "YlOrBr_r",
        "YlOrRd",
        "YlOrRd_r",
        "afmhot",
        "afmhot_r",
        "autumn",
        "autumn_r",
        "berlin",
        "berlin_r",
        "binary",
        "binary_r",
        "bone",
        "bone_r",
        "brg",
        "brg_r",
        "bwr",
        "bwr_r",
        "cividis",
        "cividis_r",
        "cool",
        "cool_r",
        "coolwarm",
        "coolwarm_r",
        "copper",
        "copper_r",
        "cubehelix",
        "cubehelix_r",
        "flag",
        "flag_r",
        "gist_earth",
        "gist_earth_r",
        "gist_gray",
        "gist_gray_r",
        "gist_grey",
        "gist_grey_r",
        "gist_heat",
        "gist_heat_r",
        "gist_ncar",
        "gist_ncar_r",
        "gist_rainbow",
        "gist_rainbow_r",
        "gist_stern",
        "gist_stern_r",
        "gist_yarg",
        "gist_yarg_r",
        "gist_yerg",
        "gist_yerg_r",
        "gnuplot",
        "gnuplot2",
        "gnuplot2_r",
        "gnuplot_r",
        "gray",
        "gray_r",
        "grey",
        "grey_r",
        "hot",
        "hot_r",
        "hsv",
        "hsv_r",
        "inferno",
        "inferno_r",
        "jet",
        "jet_r",
        "magma",
        "magma_r",
        "managua",
        "managua_r",
        "nipy_spectral",
        "nipy_spectral_r",
        "ocean",
        "ocean_r",
        "okabe_ito",
        "okabe_ito_r",
        "pink",
        "pink_r",
        "plasma",
        "plasma_r",
        "prism",
        "prism_r",
        "rainbow",
        "rainbow_r",
        "seismic",
        "seismic_r",
        "spring",
        "spring_r",
        "summer",
        "summer_r",
        "tab10",
        "tab10_r",
        "tab20",
        "tab20_r",
        "tab20b",
        "tab20b_r",
        "tab20c",
        "tab20c_r",
        "terrain",
        "terrain_r",
        "turbo",
        "turbo_r",
        "twilight",
        "twilight_r",
        "twilight_shifted",
        "twilight_shifted_r",
        "vanimo",
        "vanimo_r",
        "viridis",
        "viridis_r",
        "winter",
        "winter_r",
    }
)
# Explicit allowlist of Matplotlib's own built-in AxesImage interpolation names.
_INTERPOLATION_NAMES: Final = frozenset(
    {
        "antialiased",
        "auto",
        "bessel",
        "bicubic",
        "bilinear",
        "blackman",
        "catrom",
        "gaussian",
        "hamming",
        "hanning",
        "hermite",
        "kaiser",
        "lanczos",
        "mitchell",
        "nearest",
        "none",
        "quadric",
        "sinc",
        "spline16",
        "spline36",
    }
)


class PackageError(ValueError):
    """Raised when an editable figure package is invalid or unsafe."""


class UnsupportedFigureWarning(UserWarning):
    """Warning emitted when an unsupported object is skipped safely."""


def _json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise PackageError("Figure metadata is not canonical JSON") from exc
    return (text + "\n").encode("utf-8")


def _color(value: Any) -> str:
    return colors.to_hex(value, keep_alpha=True)


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value, int | float | np.integer | np.floating
    ):
        raise PackageError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise PackageError(f"{name} must be finite")
    return result


def _warn(message: str, collected: list[str] | None = None) -> None:
    if collected is not None:
        collected.append(message)
    warnings.warn(message, UnsupportedFigureWarning, stacklevel=3)


class _ArrayStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def add(self, value: object) -> str:
        if len(self.files) >= MAX_ARRAY_COUNT:
            raise PackageError("Figure contains too many numeric arrays")
        array = np.asanyarray(value)
        if (
            array.dtype.hasobject
            or array.dtype.fields is not None
            or array.dtype.kind not in "biufc"
        ):
            raise PackageError(f"Unsupported array dtype: {array.dtype}")
        if array.nbytes > MAX_ARRAY_BYTES:
            raise PackageError("An individual array exceeds the size limit")
        if array.dtype.byteorder == ">" or (
            array.dtype.byteorder == "=" and not np.little_endian
        ):
            array = array.astype(array.dtype.newbyteorder("<"), copy=False)
        array = np.ascontiguousarray(array)
        stream = BytesIO()
        np.save(stream, array, allow_pickle=False)
        name = f"arrays/{len(self.files):08d}.npy"
        self.files[name] = stream.getvalue()
        return name


def _text_spec(text: Text, *, transform: str | None = None) -> dict[str, Any]:
    content = text.get_text()
    if len(content) > MAX_TEXT_LENGTH:
        raise PackageError("Text exceeds the length limit")
    font = text.get_fontproperties()
    family = [str(item) for item in font.get_family()]
    spec: dict[str, Any] = {
        "alpha": text.get_alpha(),
        "color": _color(text.get_color()),
        "fontfamily": family,
        "fontsize": float(text.get_fontsize()),
        "fontstretch": str(font.get_stretch()),
        "fontstyle": str(font.get_style()),
        "fontvariant": str(font.get_variant()),
        "fontweight": font.get_weight(),
        "horizontalalignment": str(text.get_horizontalalignment()),
        "rotation": float(text.get_rotation()),
        "text": content,
        "usetex": False,
        "verticalalignment": str(text.get_verticalalignment()),
        "visible": bool(text.get_visible()),
        "zorder": float(text.get_zorder()),
    }
    if transform is not None:
        x, y = text.get_position()
        spec.update({"position": [float(x), float(y)], "transform": transform})
    return spec


def _apply_text_spec(text: Text, spec: Mapping[str, Any]) -> None:
    text.set_text(_string(spec, "text", max_length=MAX_TEXT_LENGTH))
    text.set_alpha(_optional_number(spec, "alpha"))
    text.set_color(_safe_color(spec, "color"))
    text.set_fontfamily(_string_list(spec, "fontfamily", max_items=100))
    text.set_fontsize(_number(spec, "fontsize", minimum=0, maximum=1_000_000))
    text.set_fontstretch(_string(spec, "fontstretch", max_length=100))
    text.set_fontstyle(_enum(spec, "fontstyle", {"normal", "italic", "oblique"}))
    text.set_fontvariant(_enum(spec, "fontvariant", {"normal", "small-caps"}))
    weight = spec.get("fontweight")
    if not isinstance(weight, str | int | float) or isinstance(weight, bool):
        raise PackageError("fontweight is invalid")
    text.set_fontweight(weight)  # type: ignore[arg-type]
    text.set_horizontalalignment(
        _enum(spec, "horizontalalignment", {"left", "center", "right"})
    )
    text.set_rotation(_number(spec, "rotation", minimum=-1_000_000, maximum=1_000_000))
    text.set_usetex(False)
    text.set_verticalalignment(
        _enum(
            spec,
            "verticalalignment",
            {"top", "bottom", "center", "baseline", "center_baseline"},
        )
    )
    text.set_visible(_boolean(spec, "visible"))
    text.set_zorder(_number(spec, "zorder", minimum=-1_000_000, maximum=1_000_000))


def _line_spec(line: Line2D, arrays: _ArrayStore) -> dict[str, Any]:
    marker = line.get_marker()
    if (
        not isinstance(marker, str | int)
        or isinstance(marker, bool)
        or marker not in MarkerStyle.markers
    ):
        raise PackageError("Custom marker paths are not supported")
    return {
        "alpha": line.get_alpha(),
        "antialiased": bool(line.get_antialiased()),
        "color": _color(line.get_color()),
        "dash_capstyle": str(line.get_dash_capstyle()),
        "dash_joinstyle": str(line.get_dash_joinstyle()),
        "drawstyle": str(line.get_drawstyle()),
        "label": str(line.get_label()),
        "linestyle": str(line.get_linestyle()),
        "linewidth": float(line.get_linewidth()),
        "marker": marker,
        "markeredgecolor": _color(line.get_markeredgecolor()),
        "markeredgewidth": float(line.get_markeredgewidth()),
        "markerfacecolor": _color(line.get_markerfacecolor()),
        "markersize": float(line.get_markersize()),
        "visible": bool(line.get_visible()),
        "xdata": arrays.add(line.get_xdata(orig=False)),
        "ydata": arrays.add(line.get_ydata(orig=False)),
        "zorder": float(line.get_zorder()),
    }


def _allowed_colormap_name(cmap: Any) -> str | None:
    # Matching by name alone would let a custom Colormap that merely claims an
    # allowlisted name (e.g. ListedColormap(..., name="viridis")) silently
    # replace itself with the real built-in on restore. Verify the live
    # object's actual color mapping (and special colors) against the
    # registered built-in before trusting its name.
    name = getattr(cmap, "name", None)
    if not isinstance(name, str) or name not in _COLORMAP_NAMES:
        return None
    try:
        registered = matplotlib.colormaps[name]
    except KeyError:
        return None
    if type(cmap) is not type(registered):
        return None
    sample = np.linspace(0.0, 1.0, 256)
    if not np.array_equal(cmap(sample), registered(sample)):
        return None
    if not np.array_equal(cmap.get_bad(), registered.get_bad()):
        return None
    if not np.array_equal(cmap.get_under(), registered.get_under()):
        return None
    if not np.array_equal(cmap.get_over(), registered.get_over()):
        return None
    return name


def _is_scalar_alpha(value: object) -> bool:
    return value is None or (
        isinstance(value, int | float | np.integer | np.floating)
        and not isinstance(value, bool)
    )


def _has_masked_values(*values: object) -> bool:
    return any(np.ma.is_masked(value) for value in values)


def _effective_norm_range(
    norm: colors.Normalize, data: np.ndarray
) -> tuple[float, float] | None:
    vmin, vmax = norm.vmin, norm.vmax
    if vmin is None or vmax is None:
        probe = colors.Normalize(vmin=vmin, vmax=vmax)
        probe.autoscale_None(data)
        vmin, vmax = probe.vmin, probe.vmax
    if vmin is None or vmax is None:
        return None
    return float(vmin), float(vmax)


def _match_marker_symbol(path: Any) -> str | int | None:
    for symbol in MarkerStyle.markers:
        candidate = MarkerStyle(symbol)
        candidate_path = candidate.get_path().transformed(candidate.get_transform())
        candidate_vertices = np.asarray(candidate_path.vertices)
        path_vertices = np.asarray(path.vertices)
        if candidate_vertices.shape != path_vertices.shape:
            continue
        if not np.allclose(candidate_vertices, path_vertices, atol=1e-9):
            continue
        candidate_codes = candidate_path.codes
        path_codes = path.codes
        if (candidate_codes is None) != (path_codes is None):
            continue
        if candidate_codes is not None and not np.array_equal(
            candidate_codes, path_codes
        ):
            continue
        return symbol
    return None


def _scatter_spec(
    collection: PathCollection, arrays: _ArrayStore, ax: matplotlib.axes.Axes
) -> dict[str, Any] | None:
    # A non-data offset transform (e.g. transform=ax.transAxes) would be
    # restored as data-space offsets, moving the points whenever the axes
    # limits aren't the unit square.
    if collection.get_offset_transform() is not ax.transData:
        return None
    alpha = collection.get_alpha()
    if not _is_scalar_alpha(alpha):
        return None
    paths = collection.get_paths()
    if len(paths) != 1:
        return None
    marker = _match_marker_symbol(paths[0])
    if marker is None:
        return None
    offsets = collection.get_offsets()
    if _has_masked_values(offsets):
        return None
    # Resolve lazily-mapped face/edge colors (e.g. a colormapped "face" edgecolor)
    # without requiring a prior canvas draw.
    collection.update_scalarmappable()
    values = collection.get_array()
    color_spec: dict[str, Any]
    if values is None:
        color_spec = {
            "facecolor": arrays.add(np.ma.getdata(collection.get_facecolor())),
            "mode": "explicit",
        }
    else:
        if _has_masked_values(values):
            return None
        cmap_name = _allowed_colormap_name(collection.get_cmap())
        norm = collection.norm
        if cmap_name is None or type(norm) is not colors.Normalize:
            return None
        norm_range = _effective_norm_range(norm, np.ma.getdata(values))
        if norm_range is None:
            return None
        color_spec = {
            "cmap": cmap_name,
            "mode": "colormap",
            "values": arrays.add(np.ma.getdata(values)),
            "vmax": norm_range[1],
            "vmin": norm_range[0],
        }
    return {
        "alpha": None if alpha is None else float(alpha),
        "color": color_spec,
        "edgecolor": arrays.add(np.ma.getdata(collection.get_edgecolor())),
        "label": str(collection.get_label()),
        "linewidths": arrays.add(np.ma.getdata(collection.get_linewidth())),
        "marker": marker,
        "offsets": arrays.add(np.ma.getdata(offsets)),
        "sizes": arrays.add(np.ma.getdata(collection.get_sizes())),
        "visible": bool(collection.get_visible()),
        "zorder": float(collection.get_zorder()),
    }


def _image_spec(
    image: AxesImage, arrays: _ArrayStore, ax: matplotlib.axes.Axes
) -> dict[str, Any] | None:
    # A transform that doesn't include the axes' data transform (e.g.
    # transform=ax.transAxes) would be restored as a data-space extent,
    # moving and resizing the image whenever the axes limits change.
    if not image.get_transform().contains_branch(ax.transData):
        return None
    alpha = image.get_alpha()
    if not _is_scalar_alpha(alpha):
        return None
    interpolation = image.get_interpolation()
    if interpolation not in _INTERPOLATION_NAMES:
        return None
    origin = getattr(image, "origin", None)
    if origin not in {"upper", "lower"}:
        return None
    data = image.get_array()
    if data is None:
        return None
    if _has_masked_values(data):
        return None
    raw = np.ma.getdata(data)
    color_spec: dict[str, Any]
    if raw.ndim == 2:
        cmap_name = _allowed_colormap_name(image.get_cmap())
        norm = image.norm
        if cmap_name is None or type(norm) is not colors.Normalize:
            return None
        norm_range = _effective_norm_range(norm, raw)
        if norm_range is None:
            return None
        color_spec = {
            "cmap": cmap_name,
            "mode": "colormap",
            "vmax": norm_range[1],
            "vmin": norm_range[0],
        }
    elif raw.ndim == 3 and raw.shape[-1] in (3, 4):
        color_spec = {"mode": "rgb"}
    else:
        return None
    return {
        "alpha": None if alpha is None else float(alpha),
        "color": color_spec,
        "data": arrays.add(raw),
        "extent": [
            _finite_number(value, "extent")
            for value in cast(Sequence[object], image.get_extent())
        ],
        "interpolation": interpolation,
        "label": str(image.get_label()),
        "origin": origin,
        "visible": bool(image.get_visible()),
        "zorder": float(image.get_zorder()),
    }


_PATCH_ROTATION_POINTS: Final = {"xy", "center"}
_ALLOWED_PATCH_TYPES: Final = (Rectangle, Circle, Polygon, Wedge)


def _patch_shape_fields(patch: Patch, arrays: _ArrayStore) -> dict[str, Any] | None:
    # Each field here is read from the patch's own class-specific accessors
    # (xy/width/height, center/radius, vertex list, or center/r/theta1/theta2),
    # which are defined in data coordinates independent of the patch's overall
    # transform, patch_transform composition. These are returned both for an
    # exact restore and for the numeric-recovery fallback below.
    if type(patch) is Rectangle:
        return {
            "angle": float(patch.get_angle()),
            "height": float(patch.get_height()),
            "type": "Rectangle",
            "width": float(patch.get_width()),
            "xy": [float(value) for value in patch.get_xy()],
        }
    if type(patch) is Circle:
        return {
            "center": [float(value) for value in patch.center],
            "radius": float(patch.radius),
            "type": "Circle",
        }
    if type(patch) is Polygon:
        vertices = np.asarray(patch.get_xy(), dtype=float)
        if vertices.ndim != 2 or vertices.shape[1] != 2:
            return None
        return {
            "closed": bool(patch.get_closed()),
            "type": "Polygon",
            "vertices": arrays.add(vertices),
        }
    if type(patch) is Wedge:
        return {
            "center": [float(value) for value in patch.center],
            "r": float(patch.r),
            "theta1": float(patch.theta1),
            "theta2": float(patch.theta2),
            "type": "Wedge",
            "width": None if patch.width is None else float(patch.width),
        }
    return None


def _patch_color_field(resolved: Any, alpha: float | None) -> str:
    # Patch._set_facecolor()/_set_edgecolor() resolve a literal "none" color
    # to alpha 0 regardless of the artist-level alpha (colors.to_rgba
    # special-cases the string "none"), while any other color's alpha
    # channel is overridden to equal that artist alpha when one is set. A
    # resolved alpha of 0 alongside a nonzero artist alpha can therefore
    # only come from that "none"/unfilled special case (an ordinary color
    # would have had its alpha overridden to the nonzero value instead), so
    # store the literal "none" marker there instead of a hex color: feeding
    # a hex color with a baked-in zero alpha back through
    # colors.to_rgba(color, alpha) on restore would get its alpha
    # overridden back to the nonzero artist alpha, turning an invisible
    # fill/edge into a visible one.
    rgba = colors.to_rgba(resolved)
    if alpha not in (None, 0.0) and rgba[3] == 0.0:
        return "none"
    return _color(resolved)


def _patch_spec(
    patch: Patch, arrays: _ArrayStore, ax: matplotlib.axes.Axes
) -> dict[str, Any] | None:
    # Patch.get_transform() always composes get_patch_transform() (the
    # shape's own local bbox/rotation transform) with whatever transform was
    # actually set on the artist, so checking the composed result with
    # contains_branch() is unreliable here: the extra local composition can
    # coincidentally structurally equal part of transData's own chain (e.g.
    # when it shares the figure's pixel bbox) even for a patch explicitly
    # given transform=ax.transAxes, falsely passing the guard. Calling the
    # base Artist.get_transform() bypasses that composition and checks
    # exactly what was set, the same non-data-transform case this guard
    # exists to catch.
    if Artist.get_transform(patch) is not ax.transData:
        return None
    alpha = patch.get_alpha()
    if not _is_scalar_alpha(alpha):
        return None
    if type(patch) is Rectangle and patch.rotation_point not in _PATCH_ROTATION_POINTS:
        return None
    linestyle = patch.get_linestyle()
    if not isinstance(linestyle, str):
        return None
    hatch = patch.get_hatch()
    if hatch is not None and not isinstance(hatch, str):
        return None
    fields = _patch_shape_fields(patch, arrays)
    if fields is None:
        return None
    fields.update(
        {
            "alpha": None if alpha is None else float(alpha),
            "edgecolor": _patch_color_field(patch.get_edgecolor(), alpha),
            "facecolor": _patch_color_field(patch.get_facecolor(), alpha),
            "fill": bool(patch.get_fill()),
            "hatch": hatch,
            "label": str(patch.get_label()),
            "linestyle": linestyle,
            "linewidth": float(patch.get_linewidth()),
            "visible": bool(patch.get_visible()),
            "zorder": float(patch.get_zorder()),
        }
    )
    if type(patch) is Rectangle:
        fields["rotation_point"] = patch.rotation_point
    return fields


def _patch_recovery(
    patch: Patch, label: str, arrays: _ArrayStore
) -> dict[str, Any] | None:
    fields = _patch_shape_fields(patch, arrays)
    if fields is None:
        return None
    fields["artist_type"] = fields.pop("type")
    fields["label"] = label
    return fields


class _ErrorbarBarInfo:
    __slots__ = ("alpha", "color", "linewidth", "segments", "visible", "zorder")

    def __init__(
        self,
        segments: np.ndarray,
        color: np.ndarray,
        linewidth: float,
        alpha: float | None,
        zorder: float,
        visible: bool,
    ) -> None:
        self.segments = segments
        self.color = color
        self.linewidth = linewidth
        self.alpha = alpha
        self.zorder = zorder
        self.visible = visible


def _errorbar_bar_info(
    bar: Any, ax: matplotlib.axes.Axes, n: int
) -> _ErrorbarBarInfo | None:
    if type(bar) is not LineCollection:
        return None
    # contains_branch() only checks whether transData is reachable within
    # the transform's composition tree, so an extra affine step chained
    # onto transData (e.g. Affine2D().translate(1, 0) + ax.transData) would
    # still pass; require the exact transform instead, like every other
    # exactly-restored artist's data-coordinate guard.
    if bar.get_transform() is not ax.transData:
        return None
    alpha = bar.get_alpha()
    if not _is_scalar_alpha(alpha):
        return None
    # The bar's dash pattern is neither saved nor restored (ax.errorbar()
    # always draws solid bars for this exact-restore path), so a bar that
    # was given a non-solid linestyle must fall back instead of silently
    # losing it. Collection.get_linestyle() always normalizes to a list of
    # (offset, dashes) tuples (its broader declared type also allows a bare
    # style string, which LineCollection never actually returns here).
    linestyles = cast(Sequence[tuple[float, Any]], bar.get_linestyle())
    if any(dashes is not None for _, dashes in linestyles):
        return None
    segments = bar.get_segments()
    if len(segments) != n:
        return None
    segments_array = np.asarray(segments, dtype=float)
    if segments_array.shape != (n, 2, 2):
        return None
    if _has_masked_values(segments_array):
        return None
    colors_resolved = np.ma.getdata(np.asarray(bar.get_color(), dtype=float))
    if colors_resolved.ndim != 2 or colors_resolved.shape[-1] != 4:
        return None
    if not np.allclose(colors_resolved, colors_resolved[0]):
        return None
    widths_resolved = np.ma.getdata(np.asarray(bar.get_linewidth(), dtype=float))
    if widths_resolved.size == 0 or not np.allclose(
        widths_resolved, widths_resolved[0]
    ):
        return None
    return _ErrorbarBarInfo(
        segments=segments_array,
        color=colors_resolved[0],
        linewidth=float(widths_resolved[0]),
        alpha=None if alpha is None else float(alpha),
        zorder=float(bar.get_zorder()),
        visible=bool(bar.get_visible()),
    )


class _ErrorbarCapInfo:
    __slots__ = (
        "alpha",
        "color",
        "markeredgewidth",
        "markersize",
        "visible",
        "xdata",
        "ydata",
        "zorder",
    )

    def __init__(
        self,
        color: Any,
        markersize: float,
        markeredgewidth: float,
        alpha: float | None,
        zorder: float,
        visible: bool,
        xdata: np.ndarray,
        ydata: np.ndarray,
    ) -> None:
        self.color = color
        self.markersize = markersize
        self.markeredgewidth = markeredgewidth
        self.alpha = alpha
        self.zorder = zorder
        self.visible = visible
        self.xdata = xdata
        self.ydata = ydata


def _errorbar_cap_info(
    cap: Any, expected_marker: str, ax: matplotlib.axes.Axes, n: int
) -> _ErrorbarCapInfo | None:
    if type(cap) is not Line2D:
        return None
    if cap.get_transform() is not ax.transData:
        return None
    if cap.get_marker() != expected_marker:
        return None
    if str(cap.get_linestyle()) not in {"None", "none"}:
        return None
    alpha = cap.get_alpha()
    if not _is_scalar_alpha(alpha):
        return None
    xdata = np.asarray(cap.get_xdata(orig=False), dtype=float)
    ydata = np.asarray(cap.get_ydata(orig=False), dtype=float)
    if xdata.shape != (n,) or ydata.shape != (n,) or _has_masked_values(xdata, ydata):
        return None
    return _ErrorbarCapInfo(
        # Caps are markers: their visible color is the marker edge color,
        # not Line2D.get_color() (the marker face is unfilled for "|"/"_").
        color=colors.to_rgba(cap.get_markeredgecolor()),
        markersize=float(cap.get_markersize()),
        markeredgewidth=float(cap.get_markeredgewidth()),
        alpha=None if alpha is None else float(alpha),
        zorder=float(cap.get_zorder()),
        visible=bool(cap.get_visible()),
        xdata=xdata,
        ydata=ydata,
    )


def _errorbar_bar_offsets(
    segments: np.ndarray, dep: np.ndarray, indep: np.ndarray, *, is_x: bool
) -> np.ndarray | None:
    # A bar's two segment endpoints must share the independent coordinate
    # (axis-aligned) and bracket the data point on the dependent axis with
    # non-negative extents on both sides. Anything else means the bar (or
    # the data line) was hand-edited independently -- e.g. moved
    # perpendicular to the bars, or given a negative derived error -- which
    # ax.errorbar() cannot reconstruct (it rejects negative error values
    # outright), so reject it here instead of failing later on restore.
    indep_index = 1 if is_x else 0
    dep_index = 0 if is_x else 1
    if not np.allclose(segments[:, 0, indep_index], indep) or not np.allclose(
        segments[:, 1, indep_index], indep
    ):
        return None
    low = dep - segments[:, 0, dep_index]
    high = segments[:, 1, dep_index] - dep
    if np.any(low < 0) or np.any(high < 0):
        return None
    return np.stack([low, high])


def _errorbar_spec(
    container: Any, arrays: _ArrayStore, ax: matplotlib.axes.Axes
) -> dict[str, Any] | None:
    if type(container) is not ErrorbarContainer:
        return None
    dataline, caps, bars = container.lines
    if dataline is None or type(dataline) is not Line2D:
        return None
    if dataline.get_transform() is not ax.transData:
        return None
    has_xerr = bool(getattr(container, "has_xerr", False))
    has_yerr = bool(getattr(container, "has_yerr", False))
    if not has_xerr and not has_yerr:
        return None
    x = np.asarray(dataline.get_xdata(orig=False), dtype=float)
    y = np.asarray(dataline.get_ydata(orig=False), dtype=float)
    if x.ndim != 1 or y.shape != x.shape or _has_masked_values(x, y):
        return None
    n = x.shape[0]
    expected_bars = (1 if has_xerr else 0) + (1 if has_yerr else 0)
    if len(bars) != expected_bars:
        return None

    bar_infos: list[_ErrorbarBarInfo] = []
    for bar in bars:
        info = _errorbar_bar_info(bar, ax, n)
        if info is None:
            return None
        bar_infos.append(info)
    first_bar = bar_infos[0]
    for info in bar_infos[1:]:
        if (
            not np.allclose(info.color, first_bar.color)
            or info.linewidth != first_bar.linewidth
            or info.alpha != first_bar.alpha
            or info.zorder != first_bar.zorder
            or info.visible != first_bar.visible
        ):
            return None

    bar_index = 0
    xerr_ref: str | None = None
    yerr_ref: str | None = None
    xerr_segments: np.ndarray | None = None
    yerr_segments: np.ndarray | None = None
    if has_xerr:
        xerr_segments = bar_infos[bar_index].segments
        bar_index += 1
        xerr_offsets = _errorbar_bar_offsets(xerr_segments, x, y, is_x=True)
        if xerr_offsets is None:
            return None
        xerr_ref = arrays.add(xerr_offsets)
    if has_yerr:
        yerr_segments = bar_infos[bar_index].segments
        bar_index += 1
        yerr_offsets = _errorbar_bar_offsets(yerr_segments, y, x, is_x=False)
        if yerr_offsets is None:
            return None
        yerr_ref = arrays.add(yerr_offsets)

    expected_caps = 0
    if has_xerr:
        expected_caps += 2
    if has_yerr:
        expected_caps += 2
    capsize = 0.0
    capthick = 0.0
    if len(caps) == expected_caps and expected_caps > 0:
        cap_infos: list[_ErrorbarCapInfo] = []
        cap_segment_pairs: list[np.ndarray] = []
        cap_index = 0
        if has_xerr:
            assert xerr_segments is not None
            for cap in caps[cap_index : cap_index + 2]:
                cap_info = _errorbar_cap_info(cap, "|", ax, n)
                if cap_info is None:
                    return None
                cap_infos.append(cap_info)
            cap_segment_pairs.append(xerr_segments)
            cap_index += 2
        if has_yerr:
            assert yerr_segments is not None
            for cap in caps[cap_index : cap_index + 2]:
                cap_info = _errorbar_cap_info(cap, "_", ax, n)
                if cap_info is None:
                    return None
                cap_infos.append(cap_info)
            cap_segment_pairs.append(yerr_segments)
            cap_index += 2
        # Each pair of caps must sit exactly at its bar's two endpoints --
        # ax.errorbar() positions caps there itself, so any mismatch means a
        # cap (or the bar) was hand-edited independently of the other.
        for pair_index, segments in enumerate(cap_segment_pairs):
            low_cap = cap_infos[pair_index * 2]
            high_cap = cap_infos[pair_index * 2 + 1]
            if not np.allclose(
                [low_cap.xdata, low_cap.ydata], segments[:, 0, :].T
            ) or not np.allclose([high_cap.xdata, high_cap.ydata], segments[:, 1, :].T):
                return None
        first_cap = cap_infos[0]
        if (
            first_cap.alpha != first_bar.alpha
            or first_cap.zorder != first_bar.zorder
            or first_cap.visible != first_bar.visible
        ):
            return None
        for cap_info in cap_infos[1:]:
            if (
                not np.allclose(
                    colors.to_rgba(cap_info.color), colors.to_rgba(first_cap.color)
                )
                or cap_info.markersize != first_cap.markersize
                or cap_info.markeredgewidth != first_cap.markeredgewidth
                or cap_info.alpha != first_bar.alpha
                or cap_info.zorder != first_bar.zorder
                or cap_info.visible != first_bar.visible
            ):
                return None
        # Which color caps default to (the main "color", or ecolor) differs
        # across Matplotlib versions, so the cap color actually used is
        # stored and passed explicitly on restore rather than relying on
        # whichever default the installed Matplotlib currently applies.
        capcolor = _color(first_cap.color)
        capsize = first_cap.markersize / 2.0
        capthick = first_cap.markeredgewidth
    elif len(caps) != 0:
        return None
    else:
        capcolor = None

    # The data line's own xdata/ydata (already stored by _line_spec) double as
    # the errorbar's x/y: no separate array entries are needed for them.
    line_spec = _line_spec(dataline, arrays)
    return {
        "alpha": first_bar.alpha,
        "capcolor": capcolor,
        "capsize": capsize,
        "capthick": capthick,
        "ecolor": _color(first_bar.color),
        "elinewidth": first_bar.linewidth,
        "label": str(container.get_label()),
        "line": line_spec,
        "visible": first_bar.visible,
        "xerr": xerr_ref,
        "yerr": yerr_ref,
        "zorder": first_bar.zorder,
    }


def _locator_spec(
    locator: Any, arrays: _ArrayStore, collected: list[str]
) -> dict[str, Any] | None:
    locator_type = type(locator)
    if locator_type is NullLocator:
        return {"type": "NullLocator"}
    if locator_type is AutoLocator:
        return {"type": "AutoLocator"}
    if locator_type is AutoMinorLocator:
        ndivs = getattr(locator, "ndivs", getattr(locator, "n", None))
        return {
            "ndivs": ndivs if isinstance(ndivs, int) else None,
            "type": "AutoMinorLocator",
        }
    if locator_type is FixedLocator:
        return {
            "locs": arrays.add(locator.locs),
            "nbins": locator.nbins,
            "type": "FixedLocator",
        }
    if locator_type is MultipleLocator:
        return {
            "base": float(locator._edge.step),
            "offset": float(getattr(locator, "_offset", 0.0)),
            "type": "MultipleLocator",
        }
    if locator_type is LinearLocator:
        return {"numticks": locator.numticks, "type": "LinearLocator"}
    if locator_type is IndexLocator:
        return {
            "base": float(locator._base),
            "offset": float(locator.offset),
            "type": "IndexLocator",
        }
    if locator_type is MaxNLocator:
        return {
            "integer": bool(locator._integer),
            "min_n_ticks": int(locator._min_n_ticks),
            "nbins": locator._nbins,
            "prune": locator._prune,
            "steps": arrays.add(locator._steps),
            "symmetric": bool(locator._symmetric),
            "type": "MaxNLocator",
        }
    if locator_type is LogLocator:
        return {
            "base": float(locator._base),
            "numticks": locator.numticks,
            "subs": None if locator._subs is None else arrays.add(locator._subs),
            "type": "LogLocator",
        }
    _warn(f"Skipped unsupported locator {locator_type.__name__}", collected)
    return None


def _formatter_spec(formatter: Any, collected: list[str]) -> dict[str, Any] | None:
    formatter_type = type(formatter)
    if formatter_type is NullFormatter:
        return {"type": "NullFormatter"}
    if formatter_type is ScalarFormatter:
        use_offset = formatter.get_useOffset()
        return {
            "powerlimits": list(formatter._powerlimits),
            "scientific": bool(formatter._scientific),
            "type": "ScalarFormatter",
            "use_math_text": bool(formatter.get_useMathText()),
            "use_offset": use_offset,
        }
    if formatter_type is FixedFormatter:
        return {
            "seq": [str(value) for value in formatter.seq],
            "type": "FixedFormatter",
        }
    if formatter_type is FormatStrFormatter:
        return {"fmt": formatter.fmt, "type": "FormatStrFormatter"}
    if formatter_type is StrMethodFormatter:
        return {"fmt": formatter.fmt, "type": "StrMethodFormatter"}
    if formatter_type is PercentFormatter:
        return {
            "decimals": formatter.decimals,
            "is_latex": bool(formatter._is_latex),
            "symbol": formatter.symbol,
            "type": "PercentFormatter",
            "xmax": float(formatter.xmax),
        }
    if formatter_type in {
        LogFormatter,
        LogFormatterExponent,
        LogFormatterMathtext,
        LogFormatterSciNotation,
    }:
        return {
            "base": float(formatter._base),
            "label_only_base": bool(formatter.labelOnlyBase),
            "minor_thresholds": list(formatter.minor_thresholds),
            "type": formatter_type.__name__,
        }
    _warn(f"Skipped unsupported formatter {formatter_type.__name__}", collected)
    return None


def _axis_spec(
    axis: matplotlib.axis.Axis, arrays: _ArrayStore, collected: list[str]
) -> dict[str, Any]:
    return {
        "major_formatter": _formatter_spec(axis.get_major_formatter(), collected),
        "major_locator": _locator_spec(axis.get_major_locator(), arrays, collected),
        "minor_formatter": _formatter_spec(axis.get_minor_formatter(), collected),
        "minor_locator": _locator_spec(axis.get_minor_locator(), arrays, collected),
        "visible": bool(axis.get_visible()),
    }


def _scale_name(axis: matplotlib.axis.Axis, collected: list[str]) -> str:
    scale = getattr(axis, "_scale", None)
    for name, scale_type in _SCALE_TYPES.items():
        if type(scale) is scale_type:
            return name
    _warn(
        f"Replaced unsupported scale class {type(scale).__name__} with LinearScale",
        collected,
    )
    return "linear"


def _axes_spec(
    ax: matplotlib.axes.Axes, arrays: _ArrayStore, collected: list[str]
) -> dict[str, Any]:
    # ErrorbarContainers are resolved first so their data line, cap Line2Ds,
    # and bar LineCollections can be excluded from the generic lines/
    # collections loops below instead of being saved (and restored) twice.
    errorbars: list[dict[str, Any]] = []
    errorbar_identity_to_index: dict[int, int] = {}
    consumed_line_ids: set[int] = set()
    consumed_collection_ids: set[int] = set()
    for container in ax.containers:
        if type(container) is not ErrorbarContainer:
            continue
        try:
            errorbar_spec = _errorbar_spec(container, arrays, ax)
        except (PackageError, TypeError, ValueError) as exc:
            _warn(f"Skipped ErrorbarContainer: {exc}", collected)
            continue
        if errorbar_spec is None:
            _warn(
                "Skipped ErrorbarContainer that does not match the exact "
                "restorable shape; its line and collection sub-artists are "
                "recorded individually",
                collected,
            )
            continue
        errorbars.append(errorbar_spec)
        errorbar_identity_to_index[id(container)] = len(errorbars) - 1
        dataline, caps, bars = container.lines
        if dataline is not None:
            consumed_line_ids.add(id(dataline))
        consumed_line_ids.update(id(cap) for cap in caps)
        consumed_collection_ids.update(id(bar) for bar in bars)

    lines: list[dict[str, Any]] = []
    line_identity_to_index: dict[int, int] = {}
    for line in ax.lines:
        if id(line) in consumed_line_ids:
            continue
        if type(line) is not Line2D:
            _warn(f"Skipped unsupported line class {type(line).__name__}", collected)
            continue
        try:
            lines.append(_line_spec(line, arrays))
        except (PackageError, TypeError, ValueError) as exc:
            _warn(f"Skipped Line2D: {exc}", collected)
            continue
        line_identity_to_index[id(line)] = len(lines) - 1

    texts: list[dict[str, Any]] = []
    for text in ax.texts:
        if type(text) is not Text:
            _warn(f"Skipped unsupported text class {type(text).__name__}", collected)
            continue
        transform = text.get_transform()
        if transform is ax.transData:
            transform_name = "data"
        elif transform is ax.transAxes:
            transform_name = "axes"
        elif transform is ax.figure.transFigure:
            transform_name = "figure"
        else:
            _warn("Skipped Text with an unsupported transform", collected)
            continue
        texts.append(_text_spec(text, transform=transform_name))

    recovery: list[dict[str, Any]] = []
    collections: list[dict[str, Any]] = []
    collection_identity_to_index: dict[int, int] = {}
    for collection in ax.collections:
        if id(collection) in consumed_collection_ids:
            continue
        if type(collection) is not PathCollection:
            _warn(
                f"Skipped unsupported collection class {type(collection).__name__}",
                collected,
            )
            continue
        try:
            scatter_spec = _scatter_spec(collection, arrays, ax)
        except (PackageError, TypeError, ValueError) as exc:
            _warn(f"Skipped PathCollection: {exc}", collected)
            continue
        if scatter_spec is not None:
            collections.append(scatter_spec)
            collection_identity_to_index[id(collection)] = len(collections) - 1
            continue
        try:
            values = collection.get_array()
            recovery.append(
                {
                    "artist_type": "PathCollection",
                    "label": str(collection.get_label()),
                    "offsets": arrays.add(np.ma.getdata(collection.get_offsets())),
                    "sizes": arrays.add(collection.get_sizes()),
                    "values": None
                    if values is None
                    else arrays.add(np.ma.getdata(values)),
                }
            )
            _warn(
                "Stored raw numeric data for unsupported PathCollection; "
                "artist skipped",
                collected,
            )
        except (PackageError, TypeError, ValueError) as exc:
            _warn(f"Skipped PathCollection recovery data: {exc}", collected)
    images: list[dict[str, Any]] = []
    for image in ax.images:
        if type(image) is not AxesImage:
            _warn(f"Skipped unsupported image class {type(image).__name__}", collected)
            continue
        try:
            image_spec = _image_spec(image, arrays, ax)
        except (PackageError, TypeError, ValueError) as exc:
            _warn(f"Skipped AxesImage: {exc}", collected)
            continue
        if image_spec is not None:
            images.append(image_spec)
            continue
        try:
            image_data = image.get_array()
            if image_data is None:
                raise PackageError("AxesImage has no numeric data")
            recovery.append(
                {
                    "artist_type": "AxesImage",
                    "data": arrays.add(np.ma.getdata(image_data)),
                    "extent": [
                        _finite_number(value, "extent")
                        for value in cast(Sequence[object], image.get_extent())
                    ],
                    "label": str(image.get_label()),
                }
            )
            _warn(
                "Stored raw numeric data for unsupported AxesImage; artist skipped",
                collected,
            )
        except (PackageError, TypeError, ValueError) as exc:
            _warn(f"Skipped AxesImage recovery data: {exc}", collected)
    patches: list[dict[str, Any]] = []
    patch_identity_to_index: dict[int, int] = {}
    for patch in ax.patches:
        if type(patch) not in _ALLOWED_PATCH_TYPES:
            _warn(f"Skipped unsupported patch class {type(patch).__name__}", collected)
            continue
        try:
            patch_spec = _patch_spec(patch, arrays, ax)
        except (PackageError, TypeError, ValueError) as exc:
            _warn(f"Skipped {type(patch).__name__}: {exc}", collected)
            continue
        if patch_spec is not None:
            patches.append(patch_spec)
            patch_identity_to_index[id(patch)] = len(patches) - 1
            continue
        try:
            recovery_record = _patch_recovery(patch, str(patch.get_label()), arrays)
            if recovery_record is None:
                raise PackageError(f"{type(patch).__name__} has no recoverable data")
            recovery.append(recovery_record)
            _warn(
                f"Stored raw numeric data for unsupported {type(patch).__name__}; "
                "artist skipped",
                collected,
            )
        except (PackageError, TypeError, ValueError) as exc:
            _warn(f"Skipped {type(patch).__name__} recovery data: {exc}", collected)

    unsupported_groups: dict[str, Sequence[Any]] = {
        "artist": cast(Sequence[Any], ax.artists),
        "table": cast(Sequence[Any], ax.tables),
    }
    for group_name, artists in unsupported_groups.items():
        for artist in artists:
            _warn(
                f"Skipped unsupported {group_name} class {type(artist).__name__}",
                collected,
            )

    legend_spec: dict[str, Any] | None = None
    legend = ax.get_legend()
    if legend is not None:
        loc = getattr(legend, "_loc", None)
        if (
            not isinstance(loc, str | int)
            or isinstance(loc, bool)
            or (isinstance(loc, str) and loc not in _LEGEND_LOCATIONS)
            or (isinstance(loc, int) and not 0 <= loc <= 10)
        ):
            _warn("Skipped legend with an unsupported location", collected)
        else:
            legend_texts = legend.get_texts()
            handles, _ = ax.get_legend_handles_labels()
            entries: list[dict[str, Any]] = []
            for handle in handles:
                if type(handle) is Line2D and id(handle) in line_identity_to_index:
                    entries.append(
                        {"index": line_identity_to_index[id(handle)], "type": "line"}
                    )
                elif (
                    type(handle) is PathCollection
                    and id(handle) in collection_identity_to_index
                ):
                    entries.append(
                        {
                            "index": collection_identity_to_index[id(handle)],
                            "type": "collection",
                        }
                    )
                elif (
                    type(handle) in _ALLOWED_PATCH_TYPES
                    and id(handle) in patch_identity_to_index
                ):
                    entries.append(
                        {"index": patch_identity_to_index[id(handle)], "type": "patch"}
                    )
                elif (
                    type(cast(Any, handle)) is ErrorbarContainer
                    and id(handle) in errorbar_identity_to_index
                ):
                    entries.append(
                        {
                            "index": errorbar_identity_to_index[id(handle)],
                            "type": "errorbar",
                        }
                    )
                else:
                    break
            if len(entries) != len(legend_texts):
                _warn(
                    "Skipped legend referencing an artist that could not be "
                    "exactly restored",
                    collected,
                )
            else:
                legend_spec = {
                    "entries": entries,
                    "frameon": bool(legend.get_frame_on()),
                    "labels": [item.get_text() for item in legend_texts],
                    "loc": loc,
                    "title": legend.get_title().get_text(),
                    "visible": bool(legend.get_visible()),
                }

    aspect = ax.get_aspect()
    if not isinstance(aspect, str | int | float) or isinstance(aspect, bool):
        aspect = "auto"
    return {
        "aspect": aspect,
        "axis_on": bool(ax.axison),
        "collections": collections,
        "errorbars": errorbars,
        "facecolor": _color(ax.get_facecolor()),
        "images": images,
        "legend": legend_spec,
        "lines": lines,
        "patches": patches,
        "position": [float(value) for value in ax.get_position(original=True).bounds],
        "recovery": recovery,
        "texts": texts,
        "title": _text_spec(ax.title),
        "xaxis": _axis_spec(ax.xaxis, arrays, collected),
        "xlabel": _text_spec(ax.xaxis.label),
        "xlim": [float(value) for value in ax.get_xlim()],
        "xscale": _scale_name(ax.xaxis, collected),
        "yaxis": _axis_spec(ax.yaxis, arrays, collected),
        "ylabel": _text_spec(ax.yaxis.label),
        "ylim": [float(value) for value in ax.get_ylim()],
        "yscale": _scale_name(ax.yaxis, collected),
    }


def figure_to_spec(
    figure: Figure,
) -> tuple[dict[str, Any], dict[str, bytes], list[str]]:
    """Convert a Figure to a data-only specification and NumPy array files."""
    if type(figure) is not Figure:
        raise PackageError(
            "Only the allowlisted matplotlib.figure.Figure class is supported"
        )
    if len(figure.axes) > MAX_AXES:
        raise PackageError("Figure contains too many axes")
    arrays = _ArrayStore()
    collected: list[str] = []
    axes_specs = []
    for ax in figure.axes:
        if type(ax) is not Axes:
            _warn(f"Skipped unsupported axes class {type(ax).__name__}", collected)
            continue
        axes_specs.append(_axes_spec(ax, arrays, collected))
    suptitle = getattr(figure, "_suptitle", None)
    spec = {
        "axes": axes_specs,
        "figure": {
            "dpi": float(figure.dpi),
            "edgecolor": _color(figure.get_edgecolor()),
            "facecolor": _color(figure.get_facecolor()),
            "frameon": bool(figure.get_frameon()),
            "size_inches": [float(value) for value in figure.get_size_inches()],
            "suptitle": _text_spec(suptitle) if type(suptitle) is Text else None,
        },
        "schema_version": FIGURE_SCHEMA_VERSION,
    }
    return spec, arrays.files, collected


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def dump_package(figure: Figure) -> bytes:
    """Serialize *figure* into a deterministic, data-only package."""
    spec, arrays, collected = figure_to_spec(figure)
    figure_data = _json_bytes(spec)
    if len(figure_data) > MAX_JSON_BYTES:
        raise PackageError("figure.json exceeds the JSON size limit")
    files: dict[str, bytes] = {"figure.json": figure_data, **arrays}
    file_records = [
        {
            "media_type": "application/json"
            if name.endswith(".json")
            else "application/x-npy",
            "path": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        for name, data in sorted(files.items())
    ]
    manifest = {
        "figure_schema_version": FIGURE_SCHEMA_VERSION,
        "files": file_records,
        "format": PACKAGE_FORMAT,
        "format_version": PACKAGE_VERSION,
        "warnings": collected,
    }
    manifest_data = _json_bytes(manifest)
    if len(manifest_data) > MAX_JSON_BYTES:
        raise PackageError("manifest.json exceeds the JSON size limit")
    output = BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=True) as archive:
        archive.writestr(_zip_info("manifest.json"), manifest_data)
        for name in ["figure.json", *sorted(arrays)]:
            archive.writestr(_zip_info(name), files[name])
    payload = output.getvalue()
    if len(payload) > MAX_PACKAGE_BYTES:
        raise PackageError("Figure package exceeds the size limit")
    return payload


def _read_json(data: bytes, name: str) -> Mapping[str, Any]:
    if len(data) > MAX_JSON_BYTES:
        raise PackageError(f"{name} exceeds the JSON size limit")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PackageError(f"{name} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PackageError(f"{name} must contain a JSON object")
    return value


def _validated_files(payload: bytes) -> tuple[Mapping[str, Any], dict[str, bytes]]:
    if len(payload) > MAX_PACKAGE_BYTES:
        raise PackageError("Figure package exceeds the size limit")
    try:
        archive = zipfile.ZipFile(BytesIO(payload), "r")
    except zipfile.BadZipFile as exc:
        raise PackageError("Invalid figure package ZIP") from exc
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise PackageError("Duplicate package entries are forbidden")
        if len(names) > MAX_ARRAY_COUNT + 2:
            raise PackageError("Figure package contains too many files")
        for info in infos:
            name = info.filename
            if (
                name.startswith("/")
                or "\\" in name
                or any(part in {"", ".", ".."} for part in name.split("/"))
            ):
                raise PackageError("Unsafe package path")
            if info.file_size > MAX_ARRAY_BYTES:
                raise PackageError("Package entry exceeds the size limit")
            if (
                info.compress_size != info.file_size
                or info.compress_type != zipfile.ZIP_STORED
            ):
                raise PackageError("Compressed package entries are forbidden")
        if "manifest.json" not in names or "figure.json" not in names:
            raise PackageError("Required package files are missing")
        manifest = _read_json(archive.read("manifest.json"), "manifest.json")
        if (
            manifest.get("format") != PACKAGE_FORMAT
            or manifest.get("format_version") != PACKAGE_VERSION
        ):
            raise PackageError("Unsupported package format or version")
        if manifest.get("figure_schema_version") != FIGURE_SCHEMA_VERSION:
            raise PackageError("Unsupported figure schema version")
        records = manifest.get("files")
        if not isinstance(records, list):
            raise PackageError("Manifest files must be a list")
        expected_names = {"manifest.json"}
        files: dict[str, bytes] = {}
        for record in records:
            if not isinstance(record, dict):
                raise PackageError("Invalid manifest file record")
            path = record.get("path")
            digest = record.get("sha256")
            size = record.get("size")
            if (
                not isinstance(path, str)
                or path == "manifest.json"
                or path in expected_names
            ):
                raise PackageError("Invalid or duplicate manifest path")
            if not isinstance(digest, str) or len(digest) != 64:
                raise PackageError("Invalid manifest digest")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise PackageError("Invalid manifest size")
            if path not in names:
                raise PackageError("Manifest references a missing file")
            data = archive.read(path)
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise PackageError(f"Integrity check failed for {path}")
            expected_names.add(path)
            files[path] = data
        if expected_names != set(names):
            raise PackageError("Package contains unlisted files")
        return manifest, files


def inspect_package(payload: bytes) -> Mapping[str, Any]:
    """Validate *payload* and return its manifest without restoring a Figure."""
    manifest, _ = _validated_files(payload)
    return manifest


def recover_numeric_data(payload: bytes) -> list[dict[str, Any]]:
    """Return numeric recovery records without constructing Matplotlib artists."""
    _manifest, files = _validated_files(payload)
    spec = _read_json(files["figure.json"], "figure.json")
    if spec.get("schema_version") != FIGURE_SCHEMA_VERSION:
        raise PackageError("Unsupported figure schema version")
    recovered: list[dict[str, Any]] = []
    axes_specs = _sequence(spec.get("axes"), "axes", max_items=MAX_AXES)
    for axes_index, axes_value in enumerate(axes_specs):
        axes_spec = _mapping(axes_value, "axes")
        records = _sequence(
            axes_spec.get("recovery", []), "recovery", max_items=MAX_ARTISTS_PER_AXES
        )
        for record_value in records:
            record = _mapping(record_value, "recovery record")
            artist_type = _enum(
                record,
                "artist_type",
                {
                    "PathCollection",
                    "AxesImage",
                    "Rectangle",
                    "Circle",
                    "Polygon",
                    "Wedge",
                },
            )
            result: dict[str, Any] = {
                "artist_type": artist_type,
                "axes_index": axes_index,
                "label": _string(record, "label", max_length=MAX_TEXT_LENGTH),
            }
            if artist_type == "PathCollection":
                result["offsets"] = _load_array(files, record.get("offsets"))
                result["sizes"] = _load_array(files, record.get("sizes"))
                result["values"] = (
                    None
                    if record.get("values") is None
                    else _load_array(files, record.get("values"))
                )
            elif artist_type == "AxesImage":
                result["data"] = _load_array(files, record.get("data"))
                result["extent"] = _number_list(record.get("extent"), "extent", 4)
            elif artist_type == "Rectangle":
                result["xy"] = _number_list(record.get("xy"), "xy", 2)
                result["width"] = _finite_number(record.get("width"), "width")
                result["height"] = _finite_number(record.get("height"), "height")
                result["angle"] = _finite_number(record.get("angle"), "angle")
            elif artist_type == "Circle":
                result["center"] = _number_list(record.get("center"), "center", 2)
                result["radius"] = _finite_number(record.get("radius"), "radius")
            elif artist_type == "Polygon":
                result["vertices"] = _load_array(files, record.get("vertices"))
                result["closed"] = _boolean(record, "closed")
            else:
                result["center"] = _number_list(record.get("center"), "center", 2)
                result["r"] = _finite_number(record.get("r"), "r")
                result["theta1"] = _finite_number(record.get("theta1"), "theta1")
                result["theta2"] = _finite_number(record.get("theta2"), "theta2")
                width = record.get("width")
                result["width"] = (
                    None if width is None else _finite_number(width, "width")
                )
            recovered.append(result)
    return recovered


def _load_array(files: Mapping[str, bytes], path: object) -> np.ndarray:
    if not isinstance(path, str) or not path.startswith("arrays/") or path not in files:
        raise PackageError("Invalid array reference")
    try:
        array = np.load(BytesIO(files[path]), allow_pickle=False)
    except (OSError, ValueError, EOFError) as exc:
        raise PackageError(f"Invalid NumPy array {path}") from exc
    if (
        not isinstance(array, np.ndarray)
        or array.dtype.hasobject
        or array.dtype.fields is not None
    ):
        raise PackageError("Object or structured NumPy arrays are forbidden")
    if array.dtype.kind not in "biufc" or array.nbytes > MAX_ARRAY_BYTES:
        raise PackageError("Unsupported or oversized NumPy array")
    return array


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PackageError(f"{name} must be an object")
    return value


def _sequence(
    value: object, name: str, *, length: int | None = None, max_items: int | None = None
) -> Sequence[Any]:
    if not isinstance(value, list):
        raise PackageError(f"{name} must be a list")
    if length is not None and len(value) != length:
        raise PackageError(f"{name} must contain {length} items")
    if max_items is not None and len(value) > max_items:
        raise PackageError(f"{name} contains too many items")
    return value


def _string(spec: Mapping[str, Any], key: str, *, max_length: int = 10_000) -> str:
    value = spec.get(key)
    if not isinstance(value, str) or len(value) > max_length:
        raise PackageError(f"{key} must be a bounded string")
    return value


def _string_list(spec: Mapping[str, Any], key: str, *, max_items: int) -> list[str]:
    values = _sequence(spec.get(key), key, max_items=max_items)
    if any(not isinstance(item, str) or len(item) > 1_000 for item in values):
        raise PackageError(f"{key} must contain bounded strings")
    return list(values)


def _boolean(spec: Mapping[str, Any], key: str) -> bool:
    value = spec.get(key)
    if not isinstance(value, bool):
        raise PackageError(f"{key} must be a boolean")
    return value


def _number(
    spec: Mapping[str, Any],
    key: str,
    *,
    minimum: float = -1e300,
    maximum: float = 1e300,
) -> float:
    value = _finite_number(spec.get(key), key)
    if not minimum <= value <= maximum:
        raise PackageError(f"{key} is outside the allowed range")
    return value


def _optional_number(spec: Mapping[str, Any], key: str) -> float | None:
    if spec.get(key) is None:
        return None
    return _number(spec, key)


def _optional_string(
    spec: Mapping[str, Any], key: str, *, max_length: int
) -> str | None:
    if spec.get(key) is None:
        return None
    return _string(spec, key, max_length=max_length)


def _enum(spec: Mapping[str, Any], key: str, allowed: Collection[str]) -> Any:
    value = _string(spec, key, max_length=100)
    if value not in allowed:
        raise PackageError(f"Unsupported {key}: {value}")
    return value


def _safe_color(spec: Mapping[str, Any], key: str) -> str:
    value = _string(spec, key, max_length=64)
    if not colors.is_color_like(value):
        raise PackageError(f"Invalid {key}")
    return value


def _number_list(value: object, name: str, length: int) -> list[float]:
    items = _sequence(value, name, length=length)
    return [_finite_number(item, name) for item in items]


def _restore_locator(
    spec: object, files: Mapping[str, bytes]
) -> matplotlib.ticker.Locator | None:
    if spec is None:
        return None
    item = _mapping(spec, "locator")
    locator_type = _string(item, "type", max_length=100)
    if locator_type == "NullLocator":
        return NullLocator()
    if locator_type == "AutoLocator":
        return AutoLocator()
    if locator_type == "AutoMinorLocator":
        ndivs = item.get("ndivs")
        if ndivs is not None and (
            not isinstance(ndivs, int)
            or isinstance(ndivs, bool)
            or not 1 <= ndivs <= 1000
        ):
            raise PackageError("Invalid AutoMinorLocator ndivs")
        return AutoMinorLocator(ndivs)
    if locator_type == "FixedLocator":
        nbins = item.get("nbins")
        if nbins is not None and (
            not isinstance(nbins, int) or isinstance(nbins, bool) or nbins < 1
        ):
            raise PackageError("Invalid FixedLocator nbins")
        return FixedLocator(_load_array(files, item.get("locs")).tolist(), nbins=nbins)
    if locator_type == "MultipleLocator":
        return MultipleLocator(
            base=_number(item, "base", minimum=1e-300), offset=_number(item, "offset")
        )
    if locator_type == "LinearLocator":
        numticks = item.get("numticks")
        if numticks is not None and (
            not isinstance(numticks, int)
            or isinstance(numticks, bool)
            or not 0 <= numticks <= 1_000_000
        ):
            raise PackageError("Invalid LinearLocator numticks")
        return LinearLocator(numticks=numticks)
    if locator_type == "IndexLocator":
        return IndexLocator(
            base=_number(item, "base", minimum=1e-300), offset=_number(item, "offset")
        )
    if locator_type == "MaxNLocator":
        nbins = item.get("nbins")
        if not (nbins == "auto" or isinstance(nbins, int)) or isinstance(nbins, bool):
            raise PackageError("Invalid MaxNLocator nbins")
        prune = item.get("prune")
        if prune not in {None, "lower", "upper", "both"}:
            raise PackageError("Invalid MaxNLocator prune")
        return MaxNLocator(
            nbins=nbins,
            steps=_load_array(files, item.get("steps")),
            integer=_boolean(item, "integer"),
            symmetric=_boolean(item, "symmetric"),
            prune=prune,
            min_n_ticks=int(_number(item, "min_n_ticks", minimum=1, maximum=1000)),
        )
    if locator_type == "LogLocator":
        subs_ref = item.get("subs")
        subs = None if subs_ref is None else _load_array(files, subs_ref).tolist()
        numticks = item.get("numticks")
        if not (
            numticks is None or numticks == "auto" or isinstance(numticks, int)
        ) or isinstance(numticks, bool):
            raise PackageError("Invalid LogLocator numticks")
        return LogLocator(
            base=_number(item, "base", minimum=1e-300), subs=subs, numticks=numticks
        )
    raise PackageError(f"Locator is not allowlisted: {locator_type}")


def _restore_formatter(spec: object) -> matplotlib.ticker.Formatter | None:
    if spec is None:
        return None
    item = _mapping(spec, "formatter")
    formatter_type = _string(item, "type", max_length=100)
    if formatter_type == "NullFormatter":
        return NullFormatter()
    if formatter_type == "ScalarFormatter":
        formatter = ScalarFormatter(
            useOffset=item.get("use_offset", True),
            useMathText=_boolean(item, "use_math_text"),
        )
        formatter.set_scientific(_boolean(item, "scientific"))
        limits = _number_list(item.get("powerlimits"), "powerlimits", 2)
        formatter.set_powerlimits((int(limits[0]), int(limits[1])))
        return formatter
    if formatter_type == "FixedFormatter":
        return FixedFormatter(_string_list(item, "seq", max_items=1_000_000))
    if formatter_type == "FormatStrFormatter":
        return FormatStrFormatter(_string(item, "fmt", max_length=1_000))
    if formatter_type == "StrMethodFormatter":
        return StrMethodFormatter(_string(item, "fmt", max_length=1_000))
    if formatter_type == "PercentFormatter":
        decimals = item.get("decimals")
        if decimals is not None and (
            not isinstance(decimals, int)
            or isinstance(decimals, bool)
            or not 0 <= decimals <= 100
        ):
            raise PackageError("Invalid PercentFormatter decimals")
        return PercentFormatter(
            xmax=_number(item, "xmax", minimum=1e-300),
            decimals=decimals,
            symbol=_string(item, "symbol", max_length=100),
            is_latex=_boolean(item, "is_latex"),
        )
    log_types = {
        "LogFormatter": LogFormatter,
        "LogFormatterExponent": LogFormatterExponent,
        "LogFormatterMathtext": LogFormatterMathtext,
        "LogFormatterSciNotation": LogFormatterSciNotation,
    }
    if formatter_type in log_types:
        thresholds = _number_list(item.get("minor_thresholds"), "minor_thresholds", 2)
        return log_types[formatter_type](
            base=_number(item, "base", minimum=1e-300),
            labelOnlyBase=_boolean(item, "label_only_base"),
            minor_thresholds=(thresholds[0], thresholds[1]),
        )
    raise PackageError(f"Formatter is not allowlisted: {formatter_type}")


def _restore_axis(
    axis: matplotlib.axis.Axis, spec: object, files: Mapping[str, bytes]
) -> None:
    item = _mapping(spec, "axis")
    major_locator = _restore_locator(item.get("major_locator"), files)
    minor_locator = _restore_locator(item.get("minor_locator"), files)
    major_formatter = _restore_formatter(item.get("major_formatter"))
    minor_formatter = _restore_formatter(item.get("minor_formatter"))
    if major_locator is not None:
        axis.set_major_locator(major_locator)
    if minor_locator is not None:
        axis.set_minor_locator(minor_locator)
    if major_formatter is not None:
        axis.set_major_formatter(major_formatter)
    if minor_formatter is not None:
        axis.set_minor_formatter(minor_formatter)
    axis.set_visible(_boolean(item, "visible"))


def _restore_line(
    ax: matplotlib.axes.Axes, spec: object, files: Mapping[str, bytes]
) -> Line2D:
    item = _mapping(spec, "line")
    marker = item.get("marker")
    if (
        not isinstance(marker, str | int)
        or isinstance(marker, bool)
        or marker not in MarkerStyle.markers
    ):
        raise PackageError("Invalid line marker")
    line = Line2D(
        _load_array(files, item.get("xdata")),
        _load_array(files, item.get("ydata")),
        alpha=_optional_number(item, "alpha"),
        antialiased=_boolean(item, "antialiased"),
        color=_safe_color(item, "color"),
        dash_capstyle=_enum(item, "dash_capstyle", {"butt", "projecting", "round"}),
        dash_joinstyle=_enum(item, "dash_joinstyle", {"miter", "round", "bevel"}),
        drawstyle=_enum(
            item,
            "drawstyle",
            {"default", "steps", "steps-pre", "steps-mid", "steps-post"},
        ),
        label=_string(item, "label", max_length=MAX_TEXT_LENGTH),
        linestyle=_string(item, "linestyle", max_length=100),  # type: ignore[arg-type]
        linewidth=_number(item, "linewidth", minimum=0, maximum=1_000_000),
        marker=marker,  # type: ignore[arg-type]
        markeredgecolor=_safe_color(item, "markeredgecolor"),
        markeredgewidth=_number(item, "markeredgewidth", minimum=0, maximum=1_000_000),
        markerfacecolor=_safe_color(item, "markerfacecolor"),
        markersize=_number(item, "markersize", minimum=0, maximum=1_000_000),
        visible=_boolean(item, "visible"),
        zorder=_number(item, "zorder", minimum=-1_000_000, maximum=1_000_000),
    )
    ax.add_line(line)
    return line


def _restore_colormap(spec: Mapping[str, Any], key: str) -> Any:
    name = _enum(spec, key, _COLORMAP_NAMES)
    try:
        return matplotlib.colormaps[name]
    except KeyError as exc:
        raise PackageError(f"Unsupported {key}: {name}") from exc


def _restore_scatter(
    ax: matplotlib.axes.Axes, spec: object, files: Mapping[str, bytes]
) -> None:
    item = _mapping(spec, "collection")
    marker = item.get("marker")
    if (
        not isinstance(marker, str | int)
        or isinstance(marker, bool)
        or marker not in MarkerStyle.markers
    ):
        raise PackageError("Invalid scatter marker")
    offsets = _load_array(files, item.get("offsets"))
    if offsets.ndim != 2 or offsets.shape[1] != 2:
        raise PackageError("Invalid scatter offsets")
    color_item = _mapping(item.get("color"), "color")
    mode = _enum(color_item, "mode", {"explicit", "colormap"})
    color_kwargs: dict[str, Any] = {}
    if mode == "explicit":
        color_kwargs["c"] = _load_array(files, color_item.get("facecolor"))
    else:
        vmin = _number(color_item, "vmin")
        vmax = _number(color_item, "vmax")
        color_kwargs["c"] = _load_array(files, color_item.get("values"))
        color_kwargs["cmap"] = _restore_colormap(color_item, "cmap")
        color_kwargs["norm"] = colors.Normalize(vmin=vmin, vmax=vmax)
    collection = ax.scatter(
        offsets[:, 0],
        offsets[:, 1],
        s=_load_array(files, item.get("sizes")),
        marker=marker,  # type: ignore[arg-type]
        linewidths=cast(Any, _load_array(files, item.get("linewidths"))),
        edgecolors=cast(Any, _load_array(files, item.get("edgecolor"))),
        alpha=_optional_number(item, "alpha"),
        label=_string(item, "label", max_length=MAX_TEXT_LENGTH),
        **color_kwargs,
    )
    collection.set_visible(_boolean(item, "visible"))
    collection.set_zorder(
        _number(item, "zorder", minimum=-1_000_000, maximum=1_000_000)
    )


def _restore_image(
    ax: matplotlib.axes.Axes, spec: object, files: Mapping[str, bytes]
) -> None:
    item = _mapping(spec, "image")
    data = _load_array(files, item.get("data"))
    extent = _number_list(item.get("extent"), "extent", 4)
    origin = _enum(item, "origin", {"upper", "lower"})
    interpolation = _enum(item, "interpolation", _INTERPOLATION_NAMES)
    color_item = _mapping(item.get("color"), "color")
    mode = _enum(color_item, "mode", {"colormap", "rgb"})
    color_kwargs: dict[str, Any] = {}
    if mode == "colormap":
        color_kwargs["cmap"] = _restore_colormap(color_item, "cmap")
        color_kwargs["norm"] = colors.Normalize(
            vmin=_number(color_item, "vmin"), vmax=_number(color_item, "vmax")
        )
    image = ax.imshow(
        data,
        extent=(extent[0], extent[1], extent[2], extent[3]),
        origin=origin,
        interpolation=interpolation,
        alpha=_optional_number(item, "alpha"),
        label=_string(item, "label", max_length=MAX_TEXT_LENGTH),
        **color_kwargs,
    )
    image.set_visible(_boolean(item, "visible"))
    image.set_zorder(_number(item, "zorder", minimum=-1_000_000, maximum=1_000_000))


def _restore_patch(
    ax: matplotlib.axes.Axes, spec: object, files: Mapping[str, bytes]
) -> Patch:
    item = _mapping(spec, "patch")
    patch_type = _enum(item, "type", {"Rectangle", "Circle", "Polygon", "Wedge"})
    style: dict[str, Any] = {
        "alpha": _optional_number(item, "alpha"),
        "edgecolor": _safe_color(item, "edgecolor"),
        "facecolor": _safe_color(item, "facecolor"),
        "fill": _boolean(item, "fill"),
        "hatch": _optional_string(item, "hatch", max_length=100),
        "label": _string(item, "label", max_length=MAX_TEXT_LENGTH),
        "linestyle": _string(item, "linestyle", max_length=100),
        "linewidth": _number(item, "linewidth", minimum=0, maximum=1_000_000),
    }
    patch: Patch
    if patch_type == "Rectangle":
        xy = _number_list(item.get("xy"), "xy", 2)
        rotation_point = _enum(item, "rotation_point", _PATCH_ROTATION_POINTS)
        patch = Rectangle(
            (xy[0], xy[1]),
            _number(item, "width", minimum=-1e300, maximum=1e300),
            _number(item, "height", minimum=-1e300, maximum=1e300),
            angle=_number(item, "angle", minimum=-1_000_000, maximum=1_000_000),
            rotation_point=rotation_point,
            **style,
        )
    elif patch_type == "Circle":
        center = _number_list(item.get("center"), "center", 2)
        patch = Circle(
            (center[0], center[1]),
            radius=_number(item, "radius", minimum=0, maximum=1e300),
            **style,
        )
    elif patch_type == "Polygon":
        vertices = _load_array(files, item.get("vertices"))
        if vertices.ndim != 2 or vertices.shape[1] != 2:
            raise PackageError("Invalid polygon vertices")
        patch = Polygon(vertices, closed=_boolean(item, "closed"), **style)
    else:
        center = _number_list(item.get("center"), "center", 2)
        width = item.get("width")
        patch = Wedge(
            (center[0], center[1]),
            _number(item, "r", minimum=0, maximum=1e300),
            _number(item, "theta1", minimum=-1_000_000, maximum=1_000_000),
            _number(item, "theta2", minimum=-1_000_000, maximum=1_000_000),
            width=None
            if width is None
            else _number(item, "width", minimum=0, maximum=1e300),
            **style,
        )
    ax.add_patch(patch)
    patch.set_visible(_boolean(item, "visible"))
    patch.set_zorder(_number(item, "zorder", minimum=-1_000_000, maximum=1_000_000))
    return patch


def _restore_errorbar(
    ax: matplotlib.axes.Axes, spec: object, files: Mapping[str, bytes]
) -> ErrorbarContainer:
    item = _mapping(spec, "errorbar")
    line = _restore_line(ax, _mapping(item.get("line"), "errorbar line"), files)
    x = np.asarray(line.get_xdata(orig=False))
    y = np.asarray(line.get_ydata(orig=False))
    n = x.shape[0]
    xerr_ref = item.get("xerr")
    yerr_ref = item.get("yerr")
    xerr = None if xerr_ref is None else _load_array(files, xerr_ref)
    yerr = None if yerr_ref is None else _load_array(files, yerr_ref)
    for err in (xerr, yerr):
        if err is not None and err.shape != (2, n):
            raise PackageError("Invalid errorbar xerr/yerr shape")
    capcolor = item.get("capcolor")
    container = ax.errorbar(
        x,
        y,
        xerr=xerr,
        yerr=yerr,
        fmt="none",
        ecolor=_safe_color(item, "ecolor"),
        elinewidth=_number(item, "elinewidth", minimum=0, maximum=1_000_000),
        capsize=_number(item, "capsize", minimum=0, maximum=1_000_000),
        capthick=_number(item, "capthick", minimum=0, maximum=1_000_000),
        alpha=_optional_number(item, "alpha"),
        zorder=_number(item, "zorder", minimum=-1_000_000, maximum=1_000_000),
        visible=_boolean(item, "visible"),
        label=_string(item, "label", max_length=MAX_TEXT_LENGTH),
    )
    _, caps, bars = container.lines
    if capcolor is not None:
        # Matplotlib sets a cap's visible marker-edge color from its own
        # `eb_cap_style` (derived from `ecolor`) at creation time, not from
        # a `color=` kwarg passed to errorbar(); apply the saved resolved
        # color directly so it survives regardless of that internal default.
        capcolor_value = _safe_color(item, "capcolor")
        for cap in caps:
            cap.set_markeredgecolor(capcolor_value)
    # Assigning to `.lines` does not update the (immutable-by-convention)
    # tuple Container.__getitem__ exposes -- container[0] would stay None --
    # and Matplotlib's legend handler unpacks that tuple directly. Build a
    # fresh container around the restored data line instead, and register it
    # in the Axes' containers list in place of the one errorbar() added.
    new_container = ErrorbarContainer(
        (line, caps, bars),
        has_xerr=container.has_xerr,
        has_yerr=container.has_yerr,
        label=container.get_label(),
    )
    new_container._remove_method = ax.containers.remove  # type: ignore[attr-defined]
    ax.containers[ax.containers.index(container)] = new_container
    return new_container


def _restore_scale(name: str, axis: matplotlib.axis.Axis) -> ScaleBase:
    scale_type = _SCALE_TYPES.get(name)
    if scale_type is None:
        raise PackageError(f"Scale is not allowlisted: {name}")
    return cast(ScaleBase, scale_type(axis))


def _restore_axes(figure: Figure, spec: object, files: Mapping[str, bytes]) -> None:
    item = _mapping(spec, "axes")
    position = _number_list(item.get("position"), "position", 4)
    if any(value < -1000 or value > 1000 for value in position):
        raise PackageError("Axes position is outside the allowed range")
    rect = (position[0], position[1], position[2], position[3])
    scale_mapping = getattr(mscale, "_scale_mapping", {})
    if scale_mapping.get("linear") is not LinearScale:
        raise PackageError(
            "Matplotlib's built-in linear scale registry has been replaced"
        )
    ax = Axes(
        figure,
        rect,
        facecolor=_safe_color(item, "facecolor"),
    )
    figure.add_axes(ax)
    xscale = _enum(item, "xscale", {"linear", "log", "symlog", "logit", "asinh"})
    yscale = _enum(item, "yscale", {"linear", "log", "symlog", "logit", "asinh"})
    ax.set_xscale(_restore_scale(xscale, ax.xaxis))
    ax.set_yscale(_restore_scale(yscale, ax.yaxis))
    lines = _sequence(item.get("lines"), "lines", max_items=MAX_ARTISTS_PER_AXES)
    for line_spec in lines:
        _restore_line(ax, line_spec, files)
    collections = _sequence(
        item.get("collections", []), "collections", max_items=MAX_ARTISTS_PER_AXES
    )
    for collection_spec in collections:
        _restore_scatter(ax, collection_spec, files)
    images = _sequence(item.get("images", []), "images", max_items=MAX_ARTISTS_PER_AXES)
    for image_spec in images:
        _restore_image(ax, image_spec, files)
    patches = _sequence(
        item.get("patches", []), "patches", max_items=MAX_ARTISTS_PER_AXES
    )
    restored_patches = [_restore_patch(ax, patch_spec, files) for patch_spec in patches]
    errorbars = _sequence(
        item.get("errorbars", []), "errorbars", max_items=MAX_ARTISTS_PER_AXES
    )
    restored_errorbars = [
        _restore_errorbar(ax, errorbar_spec, files) for errorbar_spec in errorbars
    ]
    texts = _sequence(item.get("texts"), "texts", max_items=MAX_ARTISTS_PER_AXES)
    for text_value in texts:
        text_spec = _mapping(text_value, "text")
        transform_name = _enum(text_spec, "transform", {"data", "axes", "figure"})
        transform = {
            "data": ax.transData,
            "axes": ax.transAxes,
            "figure": figure.transFigure,
        }[transform_name]
        position_value = _number_list(text_spec.get("position"), "text position", 2)
        text = ax.text(
            position_value[0], position_value[1], "", transform=transform, usetex=False
        )
        _apply_text_spec(text, text_spec)
    _apply_text_spec(ax.title, _mapping(item.get("title"), "title"))
    _apply_text_spec(ax.xaxis.label, _mapping(item.get("xlabel"), "xlabel"))
    _apply_text_spec(ax.yaxis.label, _mapping(item.get("ylabel"), "ylabel"))
    aspect = item.get("aspect")
    if isinstance(aspect, str):
        if aspect not in {"auto", "equal"}:
            raise PackageError("Unsupported axes aspect")
    elif isinstance(aspect, int | float) and not isinstance(aspect, bool):
        aspect = _finite_number(aspect, "aspect")
    else:
        raise PackageError("Invalid axes aspect")
    ax.set_aspect(cast(Any, aspect))
    xlim = _number_list(item.get("xlim"), "xlim", 2)
    ylim = _number_list(item.get("ylim"), "ylim", 2)
    ax.set_xlim((xlim[0], xlim[1]))
    ax.set_ylim((ylim[0], ylim[1]))
    _restore_axis(ax.xaxis, item.get("xaxis"), files)
    _restore_axis(ax.yaxis, item.get("yaxis"), files)
    if _boolean(item, "axis_on"):
        ax.set_axis_on()
    else:
        ax.set_axis_off()
    legend_value = item.get("legend")
    if legend_value is not None:
        legend_spec = _mapping(legend_value, "legend")
        labels = _string_list(legend_spec, "labels", max_items=MAX_ARTISTS_PER_AXES)
        entries = _sequence(legend_spec.get("entries"), "entries", length=len(labels))
        handles: list[Any] = []
        for entry_value in entries:
            entry = _mapping(entry_value, "legend entry")
            kind = _enum(entry, "type", {"line", "collection", "patch", "errorbar"})
            index = entry.get("index")
            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                raise PackageError("Invalid legend entry index")
            source = cast(
                Sequence[Any],
                {
                    "line": ax.lines,
                    "collection": ax.collections,
                    "patch": restored_patches,
                    "errorbar": restored_errorbars,
                }[kind],
            )
            if index >= len(source):
                raise PackageError("Legend entry index is out of range")
            handles.append(source[index])
        loc = legend_spec.get("loc")
        if (
            not isinstance(loc, str | int)
            or isinstance(loc, bool)
            or (isinstance(loc, str) and loc not in _LEGEND_LOCATIONS)
            or (isinstance(loc, int) and not 0 <= loc <= 10)
        ):
            raise PackageError("Invalid legend location")
        legend = ax.legend(
            handles,
            labels,
            frameon=_boolean(legend_spec, "frameon"),
            loc=cast(Any, loc),
            title=_string(legend_spec, "title", max_length=MAX_TEXT_LENGTH),
        )
        legend.set_visible(_boolean(legend_spec, "visible"))


def load_package(payload: bytes) -> Figure:
    """Restore a Figure from a validated data-only package."""
    _manifest, files = _validated_files(payload)
    spec = _read_json(files["figure.json"], "figure.json")
    if spec.get("schema_version") != FIGURE_SCHEMA_VERSION:
        raise PackageError("Unsupported figure schema version")
    figure_spec = _mapping(spec.get("figure"), "figure")
    size = _number_list(figure_spec.get("size_inches"), "size_inches", 2)
    if any(value <= 0 or value > 100_000 for value in size):
        raise PackageError("Invalid figure size")
    figure = Figure(
        figsize=(size[0], size[1]),
        dpi=_number(figure_spec, "dpi", minimum=1e-6, maximum=1_000_000),
        facecolor=_safe_color(figure_spec, "facecolor"),
        edgecolor=_safe_color(figure_spec, "edgecolor"),
        frameon=_boolean(figure_spec, "frameon"),
    )
    axes_specs = _sequence(spec.get("axes"), "axes", max_items=MAX_AXES)
    for axes_spec in axes_specs:
        _restore_axes(figure, axes_spec, files)
    suptitle_spec = figure_spec.get("suptitle")
    if suptitle_spec is not None:
        suptitle = figure.suptitle("", usetex=False)
        _apply_text_spec(suptitle, _mapping(suptitle_spec, "suptitle"))
    return figure
