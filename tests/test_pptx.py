import zipfile
from pathlib import Path
from xml.etree import ElementTree

import matplotlib.pyplot as plt
import pytest
from matplotlib.figure import Figure

from matplotlib_extension import pyplot
from matplotlib_extension.container import extract_ole_native_png, extract_payload
from matplotlib_extension.package import PackageError, load_package

_OLE_RELATIONSHIP_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject"
)


def _expected_parts(slide_count: int) -> set[str]:
    parts = {
        "[Content_Types].xml",
        "_rels/.rels",
        "docProps/core.xml",
        "docProps/app.xml",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
        "ppt/slideMasters/slideMaster1.xml",
        "ppt/slideMasters/_rels/slideMaster1.xml.rels",
        "ppt/slideLayouts/slideLayout1.xml",
        "ppt/theme/theme1.xml",
    }
    for index in range(1, slide_count + 1):
        parts.add(f"ppt/slides/slide{index}.xml")
        parts.add(f"ppt/slides/_rels/slide{index}.xml.rels")
        parts.add(f"ppt/embeddings/oleObject{index}.bin")
        parts.add(f"ppt/media/image{index}.png")
    return parts


def _figure(title: str = "A title") -> Figure:
    fig, ax = plt.subplots(figsize=(5, 3), dpi=100)
    ax.plot([0, 1, 2], [0, 1, 4])
    ax.set_title(title)
    return fig


def test_save_pptx_has_exact_allowlisted_parts(tmp_path: Path) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"

    pyplot.save_pptx([fig], destination)

    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == _expected_parts(1)
    plt.close(fig)


def test_save_pptx_parts_are_well_formed_xml(tmp_path: Path) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"

    pyplot.save_pptx([fig], destination)

    with zipfile.ZipFile(destination) as archive:
        for name in archive.namelist():
            if name.endswith(".xml") or name.endswith(".rels"):
                ElementTree.fromstring(archive.read(name))
    plt.close(fig)


def test_save_pptx_has_exactly_one_ole_relationship_and_content_type(
    tmp_path: Path,
) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"

    pyplot.save_pptx([fig], destination)

    with zipfile.ZipFile(destination) as archive:
        content_types = ElementTree.fromstring(archive.read("[Content_Types].xml"))
        bin_defaults = [
            element
            for element in content_types
            if element.tag.endswith("Default")
            and element.attrib.get("Extension") == "bin"
        ]
        assert len(bin_defaults) == 1
        assert (
            bin_defaults[0].attrib["ContentType"]
            == "application/vnd.openxmlformats-officedocument.oleObject"
        )

        slide_rels_bytes = archive.read("ppt/slides/_rels/slide1.xml.rels")
        slide_rels = ElementTree.fromstring(slide_rels_bytes)
        ole_relationships = [
            element
            for element in slide_rels
            if element.attrib.get("Type") == _OLE_RELATIONSHIP_TYPE
        ]
        assert len(ole_relationships) == 1
        assert ole_relationships[0].attrib["Target"] == "../embeddings/oleObject1.bin"

        embedding_parts = [
            name for name in archive.namelist() if name.startswith("ppt/embeddings/")
        ]
        assert embedding_parts == ["ppt/embeddings/oleObject1.bin"]

        slide_xml = ElementTree.fromstring(archive.read("ppt/slides/slide1.xml"))
        ole_object_elements = [
            element for element in slide_xml.iter() if element.tag.endswith("oleObj")
        ]
        assert len(ole_object_elements) == 1
    plt.close(fig)


def test_save_pptx_embedded_ole_roundtrips_byte_for_byte(tmp_path: Path) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"
    plain_ole = tmp_path / "figure.ole"

    pyplot.save_pptx([fig], destination)
    pyplot.savefig(fig, plain_ole, format="ole")

    with zipfile.ZipFile(destination) as archive:
        embedded_ole_bytes = archive.read("ppt/embeddings/oleObject1.bin")
        fallback_image_bytes = archive.read("ppt/media/image1.png")

    assert embedded_ole_bytes == plain_ole.read_bytes()

    editable_png = extract_ole_native_png(embedded_ole_bytes)
    assert editable_png == fallback_image_bytes
    assert editable_png.startswith(b"\x89PNG\r\n\x1a\n")
    assert extract_payload(editable_png) == extract_payload(plain_ole.read_bytes())
    plt.close(fig)


def test_save_pptx_multiple_figures_one_slide_each(tmp_path: Path) -> None:
    figs = [_figure("First"), _figure("Second"), _figure("Third")]
    destination = tmp_path / "deck.pptx"

    pyplot.save_pptx(figs, destination)

    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == _expected_parts(3)

        presentation = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
        slide_id_elements = [
            element for element in presentation.iter() if element.tag.endswith("sldId")
        ]
        assert len(slide_id_elements) == 3

        app_properties = ElementTree.fromstring(archive.read("docProps/app.xml"))
        slides_element = next(
            element for element in app_properties if element.tag.endswith("Slides")
        )
        assert slides_element.text == "3"

        editable_pngs = [
            archive.read(f"ppt/media/image{index}.png") for index in (1, 2, 3)
        ]
        ole_bytes_list = [
            archive.read(f"ppt/embeddings/oleObject{index}.bin") for index in (1, 2, 3)
        ]

    assert len({extract_payload(png) for png in editable_pngs}) == 3
    for editable_png, ole_bytes in zip(editable_pngs, ole_bytes_list, strict=True):
        assert extract_ole_native_png(ole_bytes) == editable_png
    for fig in figs:
        plt.close(fig)


def test_save_pptx_restores_each_figure_in_order(tmp_path: Path) -> None:
    figs = [_figure("First"), _figure("Second")]
    destination = tmp_path / "deck.pptx"

    pyplot.save_pptx(figs, destination)

    with zipfile.ZipFile(destination) as archive:
        restored_titles = []
        for index in (1, 2):
            editable_png = archive.read(f"ppt/media/image{index}.png")
            restored = load_package(extract_payload(editable_png))
            restored_titles.append(restored.axes[0].get_title())
            plt.close(restored)

    assert restored_titles == ["First", "Second"]
    for fig in figs:
        plt.close(fig)


def test_save_pptx_requires_at_least_one_figure(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one Figure"):
        pyplot.save_pptx([], tmp_path / "empty.pptx")


def test_save_pptx_exclusive_mode(tmp_path: Path) -> None:
    fig = _figure()
    destination = tmp_path / "exclusive.pptx"
    pyplot.save_pptx([fig], destination, mode="x")

    with pytest.raises(FileExistsError):
        pyplot.save_pptx([fig], destination, mode="x")
    plt.close(fig)


def test_save_pptx_append_is_explicitly_unsupported(tmp_path: Path) -> None:
    fig = _figure()

    with pytest.raises(ValueError, match="append is not supported"):
        pyplot.save_pptx([fig], tmp_path / "figure.pptx", mode="a")
    plt.close(fig)


def test_loadfig_rejects_pptx_container(tmp_path: Path) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"
    pyplot.save_pptx([fig], destination)

    with pytest.raises(PackageError):
        pyplot.loadfig(destination)
    plt.close(fig)
