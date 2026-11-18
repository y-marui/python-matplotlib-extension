import zipfile
from pathlib import Path
from xml.etree import ElementTree

import matplotlib.pyplot as plt
import pytest
from matplotlib.figure import Figure

from matplotlib_extension import pyplot
from matplotlib_extension.container import extract_ole_native_png, extract_payload
from matplotlib_extension.package import PackageError

_OLE_RELATIONSHIP_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject"
)
_EXPECTED_PARTS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "docProps/core.xml",
    "docProps/app.xml",
    "ppt/presentation.xml",
    "ppt/_rels/presentation.xml.rels",
    "ppt/slideMasters/slideMaster1.xml",
    "ppt/slideMasters/_rels/slideMaster1.xml.rels",
    "ppt/slideLayouts/slideLayout1.xml",
    "ppt/slides/slide1.xml",
    "ppt/slides/_rels/slide1.xml.rels",
    "ppt/theme/theme1.xml",
    "ppt/embeddings/oleObject1.bin",
    "ppt/media/image1.png",
}


def _figure() -> Figure:
    fig, ax = plt.subplots(figsize=(5, 3), dpi=100)
    ax.plot([0, 1, 2], [0, 1, 4])
    ax.set_title("A title")
    return fig


def test_savefig_pptx_has_exact_allowlisted_parts(tmp_path: Path) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"

    pyplot.savefig(fig, destination)

    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == _EXPECTED_PARTS
    plt.close(fig)


def test_savefig_pptx_parts_are_well_formed_xml(tmp_path: Path) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"

    pyplot.savefig(fig, destination)

    with zipfile.ZipFile(destination) as archive:
        for name in archive.namelist():
            if name.endswith(".xml") or name.endswith(".rels"):
                ElementTree.fromstring(archive.read(name))
    plt.close(fig)


def test_savefig_pptx_has_exactly_one_ole_relationship_and_content_type(
    tmp_path: Path,
) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"

    pyplot.savefig(fig, destination)

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


def test_savefig_pptx_embedded_ole_roundtrips_byte_for_byte(tmp_path: Path) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"
    plain_ole = tmp_path / "figure.ole"

    pyplot.savefig(fig, destination)
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


def test_savefig_pptx_destination_has_no_mpl_suffix_requirement(
    tmp_path: Path,
) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"

    pyplot.savefig(fig, destination)

    assert destination.read_bytes().startswith(b"PK\x03\x04")
    plt.close(fig)


def test_savefig_pptx_requires_editable(tmp_path: Path) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"

    with pytest.raises(ValueError, match="editable-only"):
        pyplot.savefig(fig, destination, editable=False)
    plt.close(fig)


def test_loadfig_rejects_pptx_container(tmp_path: Path) -> None:
    fig = _figure()
    destination = tmp_path / "figure.pptx"
    pyplot.savefig(fig, destination)

    with pytest.raises(PackageError):
        pyplot.loadfig(destination)
    plt.close(fig)
