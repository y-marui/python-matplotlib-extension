import hashlib
import json
import warnings
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import matplotlib.pyplot as plt
import matplotlib.scale as mscale
import numpy as np
import olefile
import pytest
from matplotlib.axes import Axes
from matplotlib.collections import PathCollection
from matplotlib.colors import ListedColormap, to_rgba
from matplotlib.container import ErrorbarContainer
from matplotlib.image import AxesImage
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Ellipse, Polygon, Rectangle, Wedge
from matplotlib.projections import register_projection
from matplotlib.scale import LinearScale, register_scale
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from matplotlib_extension.container import extract_ole_native_png, extract_payload
from matplotlib_extension.package import (
    PackageError,
    UnsupportedFigureWarning,
    dump_package,
    inspect_package,
    load_package,
    recover_numeric_data,
)
from matplotlib_extension.pyplot import loadfig, recover_data, savefig


def _simple_figure():
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [2.0, 3.0])
    return fig


def _package_files(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _write_package(
    files: dict[str, bytes], *, compression: int = zipfile.ZIP_STORED
) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


def test_package_is_deterministic_and_data_only() -> None:
    fig = _simple_figure()

    first = dump_package(fig)
    second = dump_package(fig)

    assert first == second
    with zipfile.ZipFile(BytesIO(first)) as archive:
        assert archive.namelist() == [
            "manifest.json",
            "figure.json",
            "arrays/00000000.npy",
            "arrays/00000001.npy",
        ]
        assert all(
            info.compress_type == zipfile.ZIP_STORED for info in archive.infolist()
        )
        figure_spec = json.loads(archive.read("figure.json"))
        assert figure_spec["schema_version"] == 3
    assert inspect_package(first)["format_version"] == 1
    plt.close(fig)


def test_every_container_embeds_identical_payload(tmp_path: Path) -> None:
    fig = _simple_figure()
    payloads = []
    for filename in (
        "figure.mpl.pdf",
        "figure.mpl.png",
        "figure.mpl.svg",
        "figure.ole",
        "figure.mplpkg",
    ):
        path = tmp_path / filename
        savefig(fig, path)
        payloads.append(extract_payload(path.read_bytes()))

    assert all(payload == payloads[0] for payload in payloads)
    plt.close(fig)


def test_graphic_containers_remain_normally_readable(tmp_path: Path) -> None:
    fig = _simple_figure()
    png = tmp_path / "figure.mpl.png"
    pdf = tmp_path / "figure.mpl.pdf"
    svg = tmp_path / "figure.mpl.svg"
    ole = tmp_path / "figure.ole"
    for path in (png, pdf, svg, ole):
        savefig(fig, path)

    with Image.open(png) as image:
        image.verify()
    assert len(PdfReader(pdf).pages) == 1
    ElementTree.parse(svg)
    assert olefile.isOleFile(ole)
    with olefile.OleFileIO(ole) as container:
        assert container.exists("\x01Ole10Native")
    native_png = extract_ole_native_png(ole.read_bytes())
    with Image.open(BytesIO(native_png)) as image:
        image.verify()
    assert extract_payload(native_png) == extract_payload(ole.read_bytes())
    plt.close(fig)


def test_compressed_pdf_attachment_is_rejected_before_decoding(tmp_path: Path) -> None:
    fig = _simple_figure()
    path = tmp_path / "figure.mpl.pdf"
    savefig(fig, path)
    reader = PdfReader(path)
    entries = reader.root_object["/Names"]["/EmbeddedFiles"]["/Names"]
    file_spec = entries[1].get_object()
    embedded = file_spec["/EF"]["/F"].get_object()
    file_spec[NameObject("/EF")][NameObject("/F")] = embedded.flate_encode()
    output = BytesIO()
    PdfWriter(clone_from=reader).write(output)

    with pytest.raises(
        PackageError, match="Compressed or invalid PDF attachments are forbidden"
    ):
        extract_payload(output.getvalue())
    plt.close(fig)


def test_manifest_integrity_failure_is_rejected() -> None:
    fig = _simple_figure()
    files = _package_files(dump_package(fig))
    figure_data = bytearray(files["figure.json"])
    figure_data[-2] ^= 1
    files["figure.json"] = bytes(figure_data)
    with pytest.raises(PackageError, match="Integrity check failed"):
        load_package(_write_package(files))
    plt.close(fig)


def test_object_dtype_npy_is_rejected_without_loading_objects() -> None:
    fig = _simple_figure()
    files = _package_files(dump_package(fig))
    object_array = BytesIO()
    np.lib.format.write_array_header_1_0(
        object_array,
        {"descr": "|O", "fortran_order": False, "shape": (1,)},
    )
    object_array.write(b"\x00")
    files["arrays/00000000.npy"] = object_array.getvalue()
    manifest = json.loads(files["manifest.json"])
    for record in manifest["files"]:
        if record["path"] == "arrays/00000000.npy":
            data = files[record["path"]]
            record["size"] = len(data)
            record["sha256"] = hashlib.sha256(data).hexdigest()
    files["manifest.json"] = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    with pytest.raises(PackageError, match="Invalid NumPy array"):
        load_package(_write_package(files))
    plt.close(fig)


def test_compressed_package_entries_are_rejected() -> None:
    fig = _simple_figure()
    files = _package_files(dump_package(fig))

    with pytest.raises(PackageError, match="Compressed package entries are forbidden"):
        load_package(_write_package(files, compression=zipfile.ZIP_DEFLATED))
    plt.close(fig)


def test_unsafe_package_path_is_rejected() -> None:
    fig = _simple_figure()
    files = _package_files(dump_package(fig))
    files["../escape"] = b"data"

    with pytest.raises(PackageError, match="Unsafe package path"):
        load_package(_write_package(files))
    plt.close(fig)


def test_unknown_package_version_is_rejected() -> None:
    fig = _simple_figure()
    files = _package_files(dump_package(fig))
    manifest = json.loads(files["manifest.json"])
    manifest["format_version"] = 999
    files["manifest.json"] = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )

    with pytest.raises(PackageError, match="Unsupported package format or version"):
        load_package(_write_package(files))
    plt.close(fig)


def test_code_like_text_is_restored_only_as_text() -> None:
    fig, ax = plt.subplots()
    content = "__import__('os').system('never run')"
    ax.set_title(content)

    restored = load_package(dump_package(fig))

    assert restored.axes[0].get_title() == content
    plt.close(fig)
    plt.close(restored)


def test_unsupported_subclass_is_warned_and_skipped() -> None:
    class CustomLine(Line2D):
        pass

    fig, ax = plt.subplots()
    ax.add_line(CustomLine([0, 1], [2, 3]))

    with pytest.warns(UnsupportedFigureWarning, match="CustomLine"):
        payload = dump_package(fig)

    restored = load_package(payload)
    assert len(restored.axes[0].lines) == 0
    assert inspect_package(payload)["warnings"] == [
        "Skipped unsupported line class CustomLine"
    ]
    plt.close(fig)
    plt.close(restored)


def test_scatter_with_unrecognized_colormap_remains_recoverable(
    tmp_path: Path,
) -> None:
    fig, ax = plt.subplots()
    custom_cmap = ListedColormap(["red", "green", "blue"])
    ax.scatter(
        [1.0, 2.0],
        [3.0, 4.0],
        s=[5.0, 6.0],
        c=[7.0, 8.0],
        cmap=custom_cmap,
        label="samples",
    )
    path = tmp_path / "scatter.mpl.png"

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        savefig(fig, path)

    records = recover_data(path)
    assert len(records) == 1
    assert records[0]["artist_type"] == "PathCollection"
    assert records[0]["label"] == "samples"
    np.testing.assert_allclose(records[0]["offsets"], [[1.0, 3.0], [2.0, 4.0]])
    np.testing.assert_allclose(records[0]["sizes"], [5.0, 6.0])
    np.testing.assert_allclose(records[0]["values"], [7.0, 8.0])
    restored = load_package(dump_package(fig))
    assert len(restored.axes[0].collections) == 0
    assert inspect_package(dump_package(fig))["warnings"] == [
        "Stored raw numeric data for unsupported PathCollection; artist skipped"
    ]
    plt.close(fig)
    plt.close(restored)


def test_scatter_with_nonstandard_marker_remains_recoverable(tmp_path: Path) -> None:
    fig, ax = plt.subplots()
    ax.scatter(
        [1.0, 2.0], [3.0, 4.0], s=[5.0, 6.0], c="red", marker=(5, 1, 20), label="poly"
    )
    path = tmp_path / "scatter.mpl.png"

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        savefig(fig, path)

    records = recover_data(path)
    assert len(records) == 1
    assert records[0]["artist_type"] == "PathCollection"
    assert records[0]["label"] == "poly"
    plt.close(fig)


def test_scatter_with_explicit_colors_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.scatter(
        [1.0, 2.0, 3.0],
        [4.0, 5.0, 6.0],
        s=[10.0, 20.0, 30.0],
        c="red",
        marker="^",
        edgecolors="blue",
        linewidths=2.0,
        alpha=0.5,
        label="triangles",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    assert inspect_package(payload)["warnings"] == []
    restored = load_package(payload)
    collections = restored.axes[0].collections
    assert len(collections) == 1
    collection = collections[0]
    assert type(collection) is PathCollection
    assert collection.get_label() == "triangles"
    np.testing.assert_allclose(
        collection.get_offsets(), [[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]]
    )
    np.testing.assert_allclose(collection.get_sizes(), [10.0, 20.0, 30.0])
    np.testing.assert_allclose(collection.get_linewidth(), [2.0])
    np.testing.assert_allclose(collection.get_facecolor(), [[1.0, 0.0, 0.0, 0.5]])
    np.testing.assert_allclose(collection.get_edgecolor(), [[0.0, 0.0, 1.0, 0.5]])
    assert collection.get_alpha() == 0.5
    plt.close(fig)
    plt.close(restored)


def test_scatter_with_colormap_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.scatter(
        [1.0, 2.0, 3.0],
        [4.0, 5.0, 6.0],
        s=25.0,
        c=[7.0, 8.0, 9.0],
        cmap="plasma",
        marker="o",
        label="mapped",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    assert inspect_package(payload)["warnings"] == []
    assert recover_numeric_data(payload) == []
    restored = load_package(payload)
    collection = restored.axes[0].collections[0]
    assert type(collection) is PathCollection
    np.testing.assert_allclose(collection.get_sizes(), [25.0])
    np.testing.assert_allclose(collection.get_array(), [7.0, 8.0, 9.0])
    assert collection.get_cmap().name == "plasma"
    assert collection.norm.vmin == 7.0
    assert collection.norm.vmax == 9.0
    collection.update_scalarmappable()
    expected_facecolor = plt.get_cmap("plasma")(np.array([0.0, 0.5, 1.0]))
    np.testing.assert_allclose(
        collection.get_facecolor(), expected_facecolor, atol=1e-6
    )
    plt.close(fig)
    plt.close(restored)


def test_imshow_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    data = np.array([[1.0, 2.0], [3.0, 4.0]])
    ax.imshow(
        data,
        cmap="viridis",
        origin="lower",
        interpolation="nearest",
        extent=(0.0, 2.0, 0.0, 2.0),
        alpha=0.75,
        label="grid",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    assert inspect_package(payload)["warnings"] == []
    restored = load_package(payload)
    images = restored.axes[0].images
    assert len(images) == 1
    image = images[0]
    assert type(image) is AxesImage
    np.testing.assert_allclose(image.get_array(), data)
    assert image.get_interpolation() == "nearest"
    assert image.origin == "lower"
    assert image.get_extent() == [0.0, 2.0, 0.0, 2.0]
    assert image.get_alpha() == 0.75
    assert image.get_cmap().name == "viridis"
    plt.close(fig)
    plt.close(restored)


def test_imshow_rgb_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    data = np.zeros((2, 2, 3))
    data[0, 0] = [1.0, 0.0, 0.0]
    ax.imshow(data)

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    restored = load_package(payload)
    image = restored.axes[0].images[0]
    np.testing.assert_allclose(image.get_array(), data)
    plt.close(fig)
    plt.close(restored)


def test_legacy_object_attachment_is_never_restored(tmp_path: Path) -> None:
    fig = _simple_figure()
    rendered = BytesIO()
    fig.savefig(rendered, format="pdf")
    reader = PdfReader(BytesIO(rendered.getvalue()))
    writer = PdfWriter(clone_from=reader)
    writer.add_attachment("fig.dill", b"malicious object stream")
    legacy = tmp_path / "legacy.plt.pdf"
    with legacy.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(PackageError, match="exactly one editable payload"):
        loadfig(legacy)
    plt.close(fig)


def test_restore_does_not_use_mutable_class_registries() -> None:
    fig = _simple_figure()
    payload = dump_package(fig)

    class RegistryAxes(Axes):
        name = "rectilinear"

        def __init__(self, *args, **kwargs):
            raise AssertionError("projection registry was used")

    class RegistryScale(LinearScale):
        name = "linear"

        def __init__(self, *args, **kwargs):
            raise AssertionError("scale registry was used")

    register_projection(RegistryAxes)
    try:
        restored = load_package(payload)
    finally:
        register_projection(Axes)

    assert type(restored.axes[0]) is Axes
    assert type(restored.axes[0].xaxis._scale) is LinearScale

    original_scale = mscale._scale_mapping["linear"]
    original_has_axis = mscale._scale_has_axis_parameter["linear"]
    register_scale(RegistryScale)
    try:
        with pytest.raises(
            PackageError, match="linear scale registry has been replaced"
        ):
            load_package(payload)
    finally:
        mscale._scale_mapping["linear"] = original_scale
        mscale._scale_has_axis_parameter["linear"] = original_has_axis

    plt.close(fig)
    plt.close(restored)


_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "scatter_imshow_matplotlib-3.10.0.mplpkg",
        "scatter_imshow_matplotlib-3.11.2.mplpkg",
    ],
)
def test_cross_version_scatter_imshow_fixture_restores_exactly(
    fixture_name: str,
) -> None:
    payload = (_FIXTURES_DIR / fixture_name).read_bytes()

    restored = load_package(payload)

    collection = restored.axes[0].collections[0]
    assert type(collection) is PathCollection
    np.testing.assert_allclose(
        collection.get_offsets(), [[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]]
    )
    np.testing.assert_allclose(collection.get_array(), [7.0, 8.0, 9.0])
    assert collection.get_cmap().name == "plasma"

    image = restored.axes[0].images[0]
    assert type(image) is AxesImage
    np.testing.assert_allclose(image.get_array(), [[1.0, 2.0], [3.0, 4.0]])
    assert image.get_cmap().name == "viridis"
    assert image.origin == "lower"
    assert image.get_interpolation() == "nearest"
    plt.close(restored)


def test_scatter_with_impersonating_colormap_remains_recoverable(
    tmp_path: Path,
) -> None:
    fig, ax = plt.subplots()
    fake_viridis = ListedColormap(["red", "blue"], name="viridis")
    ax.scatter([1.0, 2.0], [3.0, 4.0], c=[7.0, 8.0], cmap=fake_viridis, label="fake")
    path = tmp_path / "scatter.mpl.png"

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        savefig(fig, path)

    records = recover_data(path)
    assert len(records) == 1
    plt.close(fig)


def test_scatter_with_non_data_transform_remains_recoverable(tmp_path: Path) -> None:
    fig, ax = plt.subplots()
    ax.scatter([0.1, 0.2], [0.3, 0.4], transform=ax.transAxes, label="axes-space")
    path = tmp_path / "scatter.mpl.png"

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        savefig(fig, path)

    records = recover_data(path)
    assert len(records) == 1
    plt.close(fig)


def test_imshow_with_non_data_transform_remains_recoverable(tmp_path: Path) -> None:
    fig, ax = plt.subplots()
    ax.imshow([[1.0, 2.0], [3.0, 4.0]], transform=ax.transAxes, label="axes-space")
    path = tmp_path / "image.mpl.png"

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        savefig(fig, path)

    records = recover_data(path)
    assert len(records) == 1
    plt.close(fig)


def test_scatter_with_masked_offsets_remains_recoverable(tmp_path: Path) -> None:
    fig, ax = plt.subplots()
    x = np.ma.array([1.0, 2.0, 3.0], mask=[False, True, False])
    ax.scatter(x, [4.0, 5.0, 6.0], label="masked")
    path = tmp_path / "scatter.mpl.png"

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        savefig(fig, path)

    records = recover_data(path)
    assert len(records) == 1
    plt.close(fig)


def test_imshow_with_masked_data_remains_recoverable(tmp_path: Path) -> None:
    fig, ax = plt.subplots()
    data = np.ma.array([[1.0, 2.0], [3.0, 4.0]], mask=[[False, True], [False, False]])
    ax.imshow(data, label="masked")
    path = tmp_path / "image.mpl.png"

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        savefig(fig, path)

    records = recover_data(path)
    assert len(records) == 1
    plt.close(fig)


def test_scatter_with_array_alpha_remains_recoverable(tmp_path: Path) -> None:
    fig, ax = plt.subplots()
    ax.scatter([1.0, 2.0], [3.0, 4.0], alpha=[0.2, 0.8], label="varied-alpha")
    path = tmp_path / "scatter.mpl.png"

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        savefig(fig, path)

    records = recover_data(path)
    assert len(records) == 1
    plt.close(fig)


def test_imshow_with_array_alpha_remains_recoverable(tmp_path: Path) -> None:
    fig, ax = plt.subplots()
    data = np.array([[1.0, 2.0], [3.0, 4.0]])
    ax.imshow(data, alpha=np.array([[0.1, 0.2], [0.3, 0.4]]), label="varied-alpha")
    path = tmp_path / "image.mpl.png"

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        savefig(fig, path)

    records = recover_data(path)
    assert len(records) == 1
    plt.close(fig)


def test_legend_with_scatter_handle_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0], label="line")
    ax.scatter([0.0, 1.0], [1.0, 0.0], label="points")
    ax.legend()

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    assert inspect_package(payload)["warnings"] == []
    restored = load_package(payload)
    legend = restored.axes[0].get_legend()
    assert legend is not None
    assert [text.get_text() for text in legend.get_texts()] == ["line", "points"]
    plt.close(fig)
    plt.close(restored)


def test_legend_referencing_unrestorable_scatter_is_skipped() -> None:
    fig, ax = plt.subplots()
    ax.scatter([0.0, 1.0], [1.0, 0.0], marker=(5, 1, 20), label="poly")
    ax.legend()

    with pytest.warns(
        UnsupportedFigureWarning,
        match="Skipped legend referencing an artist",
    ):
        payload = dump_package(fig)

    restored = load_package(payload)
    assert restored.axes[0].get_legend() is None
    plt.close(fig)
    plt.close(restored)


def test_rectangle_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.add_patch(
        Rectangle(
            (1.0, 2.0),
            3.0,
            4.0,
            angle=15.0,
            facecolor="red",
            edgecolor="blue",
            linewidth=2.0,
            alpha=0.5,
            label="rect",
        )
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    assert inspect_package(payload)["warnings"] == []
    restored = load_package(payload)
    patches = restored.axes[0].patches
    assert len(patches) == 1
    patch = patches[0]
    assert type(patch) is Rectangle
    assert patch.get_label() == "rect"
    assert patch.get_xy() == (1.0, 2.0)
    assert patch.get_width() == 3.0
    assert patch.get_height() == 4.0
    assert patch.get_angle() == 15.0
    np.testing.assert_allclose(patch.get_facecolor(), [1.0, 0.0, 0.0, 0.5])
    np.testing.assert_allclose(patch.get_edgecolor(), [0.0, 0.0, 1.0, 0.5])
    assert patch.get_alpha() == 0.5
    plt.close(fig)
    plt.close(restored)


def test_circle_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.add_patch(Circle((5.0, 5.0), radius=2.5, facecolor="green", label="circ"))

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    restored = load_package(payload)
    patch = restored.axes[0].patches[0]
    assert type(patch) is Circle
    assert patch.center == (5.0, 5.0)
    assert patch.radius == 2.5
    plt.close(fig)
    plt.close(restored)


def test_polygon_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.add_patch(
        Polygon(
            [[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]],
            closed=True,
            facecolor="yellow",
            label="poly",
        )
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    restored = load_package(payload)
    patch = restored.axes[0].patches[0]
    assert type(patch) is Polygon
    assert patch.get_closed() is True
    np.testing.assert_allclose(
        patch.get_xy(), [[0.0, 0.0], [1.0, 0.0], [0.5, 1.0], [0.0, 0.0]]
    )
    plt.close(fig)
    plt.close(restored)


def test_wedge_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.add_patch(Wedge((2.0, 2.0), 3.0, 10.0, 80.0, width=1.0, label="wedge"))

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    restored = load_package(payload)
    patch = restored.axes[0].patches[0]
    assert type(patch) is Wedge
    assert patch.center == (2.0, 2.0)
    assert patch.r == 3.0
    assert patch.theta1 == 10.0
    assert patch.theta2 == 80.0
    assert patch.width == 1.0
    plt.close(fig)
    plt.close(restored)


def test_patch_with_non_data_transform_remains_recoverable(tmp_path: Path) -> None:
    fig, ax = plt.subplots()
    ax.add_patch(
        Rectangle((0.1, 0.1), 0.2, 0.2, transform=ax.transAxes, label="axes-space")
    )
    path = tmp_path / "patch.mpl.png"

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        savefig(fig, path)

    records = recover_data(path)
    assert len(records) == 1
    assert records[0]["artist_type"] == "Rectangle"
    assert records[0]["label"] == "axes-space"
    restored = load_package(dump_package(fig))
    assert len(restored.axes[0].patches) == 0
    plt.close(fig)
    plt.close(restored)


def test_rectangle_with_custom_rotation_point_remains_recoverable(
    tmp_path: Path,
) -> None:
    fig, ax = plt.subplots()
    ax.add_patch(
        Rectangle(
            (0.0, 0.0), 1.0, 1.0, angle=30.0, rotation_point=(0.5, 0.5), label="custom"
        )
    )
    path = tmp_path / "patch.mpl.png"

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        savefig(fig, path)

    records = recover_data(path)
    assert len(records) == 1
    assert records[0]["artist_type"] == "Rectangle"
    plt.close(fig)


def test_patch_with_array_alpha_remains_recoverable() -> None:
    # Patch.set_alpha() rejects an array outright through the public API
    # (and the Agg renderer cannot draw such a patch either), so the
    # private attribute is set directly, without rendering, to exercise the
    # same scalar-only alpha guard used for scatter/image, defensively kept
    # for this type too.
    fig, ax = plt.subplots()
    patch = Rectangle((0.0, 0.0), 1.0, 1.0, label="varied-alpha")
    ax.add_patch(patch)
    patch._alpha = np.array([0.2, 0.8])

    with pytest.warns(UnsupportedFigureWarning, match="Stored raw numeric data"):
        payload = dump_package(fig)

    records = recover_numeric_data(payload)
    assert len(records) == 1
    assert records[0]["artist_type"] == "Rectangle"
    plt.close(fig)


def test_patch_with_unsupported_subclass_is_skipped() -> None:
    fig, ax = plt.subplots()
    ax.add_patch(Ellipse((0.0, 0.0), 1.0, 2.0, label="ellipse"))

    with pytest.warns(
        UnsupportedFigureWarning, match="Skipped unsupported patch class Ellipse"
    ):
        payload = dump_package(fig)

    assert recover_numeric_data(payload) == []
    restored = load_package(payload)
    assert len(restored.axes[0].patches) == 0
    plt.close(fig)
    plt.close(restored)


def test_legend_with_patch_handle_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0], label="line")
    ax.add_patch(Circle((0.0, 0.0), radius=1.0, label="circ"))
    ax.legend()

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    assert inspect_package(payload)["warnings"] == []
    restored = load_package(payload)
    legend = restored.axes[0].get_legend()
    assert legend is not None
    assert [text.get_text() for text in legend.get_texts()] == ["line", "circ"]
    plt.close(fig)
    plt.close(restored)


def test_legend_referencing_unrestorable_patch_is_skipped() -> None:
    fig, ax = plt.subplots()
    ax.add_patch(Ellipse((0.0, 0.0), 1.0, 2.0, label="ellipse"))
    ax.legend()

    with pytest.warns(
        UnsupportedFigureWarning,
        match="Skipped legend referencing an artist",
    ):
        payload = dump_package(fig)

    restored = load_package(payload)
    assert restored.axes[0].get_legend() is None
    plt.close(fig)
    plt.close(restored)


def test_errorbar_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.errorbar(
        [1.0, 2.0, 3.0],
        [4.0, 5.0, 6.0],
        yerr=[[0.1, 0.2, 0.3], [0.3, 0.2, 0.1]],
        xerr=0.05,
        fmt="s--",
        color="purple",
        ecolor="orange",
        elinewidth=1.5,
        capsize=5,
        capthick=2.0,
        alpha=0.8,
        label="errbar",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    assert inspect_package(payload)["warnings"] == []
    restored = load_package(payload)
    ax2 = restored.axes[0]
    assert len(ax2.containers) == 1
    container = ax2.containers[0]
    assert type(container) is ErrorbarContainer
    assert container.get_label() == "errbar"
    dataline, caps, bars = container.lines
    assert type(dataline) is Line2D
    np.testing.assert_allclose(dataline.get_xdata(orig=False), [1.0, 2.0, 3.0])
    np.testing.assert_allclose(dataline.get_ydata(orig=False), [4.0, 5.0, 6.0])
    np.testing.assert_allclose(to_rgba(dataline.get_color()), to_rgba("purple"))
    assert dataline.get_linestyle() == "--"
    assert len(caps) == 4
    assert len(bars) == 2
    for bar in bars:
        np.testing.assert_allclose(bar.get_alpha(), 0.8)
    np.testing.assert_allclose(bars[1].get_segments()[0], [[1.0, 3.9], [1.0, 4.3]])
    np.testing.assert_allclose(bars[0].get_segments()[0], [[0.95, 4.0], [1.05, 4.0]])
    # The data line plus the 4 cap Line2Ds (ax.lines), with the 2 bar
    # LineCollections living in ax.collections.
    assert len(ax2.lines) == 5
    assert len(ax2.collections) == 2
    plt.close(fig)
    plt.close(restored)


def test_errorbar_without_caps_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.errorbar(
        [1.0, 2.0], [3.0, 4.0], yerr=0.5, xerr=0.25, fmt="o", capsize=0, label="nocap"
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    restored = load_package(payload)
    container = restored.axes[0].containers[0]
    _, caps, bars = container.lines
    assert caps == ()
    assert len(bars) == 2
    plt.close(fig)
    plt.close(restored)


def test_errorbar_yerr_only_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.errorbar([1.0, 2.0], [3.0, 4.0], yerr=0.5, fmt="o", capsize=3, label="yonly")

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    restored = load_package(payload)
    container = restored.axes[0].containers[0]
    assert container.has_xerr is False
    assert container.has_yerr is True
    _, caps, bars = container.lines
    assert len(caps) == 2
    assert all(cap.get_marker() == "_" for cap in caps)
    assert len(bars) == 1
    plt.close(fig)
    plt.close(restored)


def test_errorbar_with_fmt_none_remains_recoverable() -> None:
    fig, ax = plt.subplots()
    ax.errorbar([1.0, 2.0], [3.0, 4.0], yerr=0.5, fmt="none", label="none-fmt")

    with pytest.warns(
        UnsupportedFigureWarning, match="Skipped unsupported collection class"
    ):
        payload = dump_package(fig)

    restored = load_package(payload)
    assert len(restored.axes[0].containers) == 0
    assert len(restored.axes[0].collections) == 0
    plt.close(fig)
    plt.close(restored)


def test_errorbar_with_onesided_limits_remains_recoverable() -> None:
    fig, ax = plt.subplots()
    ax.errorbar(
        [1.0, 2.0], [3.0, 4.0], yerr=0.5, fmt="o", capsize=4, uplims=True, label="lims"
    )

    with pytest.warns(
        UnsupportedFigureWarning, match="does not match the exact restorable shape"
    ):
        payload = dump_package(fig)

    restored = load_package(payload)
    assert len(restored.axes[0].containers) == 0
    # The data line and the two cap Line2Ds (still exactly Line2D, just with
    # a non-"_"/"|" marker for the one-sided limit) round-trip individually.
    assert len(restored.axes[0].lines) == 3
    plt.close(fig)
    plt.close(restored)


def test_legend_with_errorbar_handle_round_trips_exactly() -> None:
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0], label="line")
    ax.errorbar([1.0, 2.0], [3.0, 4.0], yerr=0.5, fmt="o", capsize=3, label="errbar")
    ax.legend()

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFigureWarning)
        payload = dump_package(fig)

    assert inspect_package(payload)["warnings"] == []
    restored = load_package(payload)
    legend = restored.axes[0].get_legend()
    assert legend is not None
    assert [text.get_text() for text in legend.get_texts()] == ["line", "errbar"]
    plt.close(fig)
    plt.close(restored)


def test_legend_referencing_unrestorable_errorbar_is_skipped() -> None:
    fig, ax = plt.subplots()
    ax.errorbar(
        [1.0, 2.0], [3.0, 4.0], yerr=0.5, fmt="o", capsize=4, uplims=True, label="lims"
    )
    ax.legend()

    with pytest.warns(
        UnsupportedFigureWarning,
        match="does not match the exact restorable shape",
    ):
        payload = dump_package(fig)

    restored = load_package(payload)
    assert restored.axes[0].get_legend() is None
    plt.close(fig)
    plt.close(restored)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "patch_errorbar_matplotlib-3.10.0.mplpkg",
        "patch_errorbar_matplotlib-3.11.2.mplpkg",
    ],
)
def test_cross_version_patch_errorbar_fixture_restores_exactly(
    fixture_name: str,
) -> None:
    payload = (_FIXTURES_DIR / fixture_name).read_bytes()

    restored = load_package(payload)
    ax = restored.axes[0]

    patch_types = {type(patch).__name__: patch for patch in ax.patches}
    assert set(patch_types) == {"Rectangle", "Circle", "Polygon", "Wedge"}
    assert patch_types["Rectangle"].get_label() == "rect"
    assert patch_types["Circle"].center == (1.5, 1.5)
    assert patch_types["Wedge"].theta1 == 10.0

    assert len(ax.containers) == 1
    container = ax.containers[0]
    assert type(container) is ErrorbarContainer
    assert container.get_label() == "errbar"
    dataline, caps, bars = container.lines
    np.testing.assert_allclose(dataline.get_xdata(orig=False), [0.5, 1.5, 2.5])
    assert len(caps) == 4
    assert len(bars) == 2
    plt.close(restored)
