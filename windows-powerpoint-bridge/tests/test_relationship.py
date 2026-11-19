"""Tests for :mod:`windows_powerpoint_bridge.relationship`.

``single_figure_powerpoint_resaved.pptx``/``multi_figure_powerpoint_resaved.pptx``
are real binaries captured from a real PowerPoint-for-Windows resave,
relayed via the main session (see the handoff notes and
``tests/fixtures/powerpoint_windows/README.md``) -- the same role the
macOS bridge's own ``*_powerpoint_resaved.pptx`` fixtures play (issue
#77). Unlike the macOS bridge, PowerPoint for Windows wraps ``p:oleObj``
in `mc:AlternateContent` *asymmetrically*: ``mc:Choice`` holds a minimal
copy (``<p:embed/>`` only), ``mc:Fallback`` holds the full one (also
``<p:pic>``). Both agree on ``name``/``r:id``/``progId`` -- the only
three attributes :mod:`windows_powerpoint_bridge.relationship` actually
compares -- which the tests below exercise directly against the real
fixture, not a hand-built approximation.
"""

import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from matplotlib_extension.container import extract_ole_native_png, extract_payload
from matplotlib_extension.package import load_package
from matplotlib_extension.pyplot import extract_editable_png

from windows_powerpoint_bridge.errors import BridgeError
from windows_powerpoint_bridge.relationship import (
    MAX_PRESENTATION_BYTES,
    resolve_ole_part,
)

FIXTURES = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "powerpoint_windows"
)


def _rewrite_zip(data: bytes, replacements: dict[str, bytes]) -> bytes:
    """Return *data* with the given members' bytes replaced, all else kept."""
    output = BytesIO()
    with (
        zipfile.ZipFile(BytesIO(data)) as source,
        zipfile.ZipFile(output, "w") as destination,
    ):
        for info in source.infolist():
            content = replacements.get(info.filename, source.read(info.filename))
            destination.writestr(info.filename, content)
    return output.getvalue()


@pytest.mark.parametrize(
    "filename,shape_names",
    [
        ("single_figure.pptx", ["Figure 1"]),
        ("multi_figure.pptx", ["Figure 1", "Figure 2", "Figure 3"]),
        ("single_figure_powerpoint_resaved.pptx", ["Figure 1"]),
        ("multi_figure_powerpoint_resaved.pptx", ["Figure 1", "Figure 2", "Figure 3"]),
    ],
)
def test_resolves_every_slide_to_its_own_embedding(
    filename: str, shape_names: list[str]
) -> None:
    data = (FIXTURES / filename).read_bytes()
    with zipfile.ZipFile(FIXTURES / filename) as archive:
        for index, shape_name in enumerate(shape_names, start=1):
            expected = archive.read(f"ppt/embeddings/oleObject{index}.bin")
            resolved = resolve_ole_part(data, slide_index=index, shape_name=shape_name)
            assert resolved == expected


@pytest.mark.parametrize(
    "filename", ["single_figure.pptx", "multi_figure_powerpoint_resaved.pptx"]
)
def test_resolved_bytes_round_trip_to_the_same_restored_figure(
    filename: str, tmp_path: Path
) -> None:
    data = (FIXTURES / filename).read_bytes()
    with zipfile.ZipFile(FIXTURES / filename) as archive:
        fallback_png = archive.read("ppt/media/image1.png")

    resolved = resolve_ole_part(data, slide_index=1, shape_name="Figure 1")
    assert extract_ole_native_png(resolved) == fallback_png

    ole_path = tmp_path / "resolved.bin"
    ole_path.write_bytes(resolved)
    destination = tmp_path / "figure.mpl.png"
    extract_editable_png(ole_path, destination, mode="x")
    assert destination.read_bytes() == fallback_png

    figure = load_package(extract_payload(destination.read_bytes()))
    assert figure.axes
    import matplotlib.pyplot as plt

    plt.close(figure)


def test_rejects_shape_name_not_matching_the_slide() -> None:
    data = (FIXTURES / "multi_figure_powerpoint_resaved.pptx").read_bytes()
    with pytest.raises(BridgeError, match="does not match the selected shape"):
        resolve_ole_part(data, slide_index=1, shape_name="Figure 2")


def test_rejects_out_of_range_slide_index() -> None:
    data = (FIXTURES / "single_figure.pptx").read_bytes()
    with pytest.raises(BridgeError, match="no slide at index"):
        resolve_ole_part(data, slide_index=5, shape_name="Figure 1")


def test_rejects_invalid_zip() -> None:
    with pytest.raises(BridgeError, match="Not a valid .pptx package"):
        resolve_ole_part(b"not a zip file", slide_index=1, shape_name="Figure 1")


def test_rejects_oversized_presentation() -> None:
    oversized = b"\x00" * (MAX_PRESENTATION_BYTES + 1)
    with pytest.raises(BridgeError, match="exceeds the size limit"):
        resolve_ole_part(oversized, slide_index=1, shape_name="Figure 1")


def test_rejects_tampered_relationship_type() -> None:
    data = (FIXTURES / "single_figure.pptx").read_bytes()
    with zipfile.ZipFile(FIXTURES / "single_figure.pptx") as archive:
        rels = archive.read("ppt/slides/_rels/slide1.xml.rels").decode()
    tampered = rels.replace(
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/package",
    )
    assert tampered != rels
    tampered_data = _rewrite_zip(
        data, {"ppt/slides/_rels/slide1.xml.rels": tampered.encode()}
    )
    with pytest.raises(BridgeError, match="Unexpected OLE relationship type"):
        resolve_ole_part(tampered_data, slide_index=1, shape_name="Figure 1")


def test_rejects_tampered_embedding_target() -> None:
    data = (FIXTURES / "single_figure.pptx").read_bytes()
    with zipfile.ZipFile(FIXTURES / "single_figure.pptx") as archive:
        rels = archive.read("ppt/slides/_rels/slide1.xml.rels").decode()
    tampered = rels.replace(
        "../embeddings/oleObject1.bin", "../embeddings/../../../etc/oleObject1.bin"
    )
    assert tampered != rels
    tampered_data = _rewrite_zip(
        data, {"ppt/slides/_rels/slide1.xml.rels": tampered.encode()}
    )
    with pytest.raises(BridgeError, match="Unexpected OLE relationship target"):
        resolve_ole_part(tampered_data, slide_index=1, shape_name="Figure 1")


def test_rejects_tampered_content_type() -> None:
    data = (FIXTURES / "single_figure.pptx").read_bytes()
    with zipfile.ZipFile(FIXTURES / "single_figure.pptx") as archive:
        content_types = archive.read("[Content_Types].xml").decode()
    tampered = content_types.replace(
        'ContentType="application/vnd.openxmlformats-officedocument.oleObject"',
        'ContentType="application/octet-stream"',
    )
    assert tampered != content_types
    tampered_data = _rewrite_zip(data, {"[Content_Types].xml": tampered.encode()})
    with pytest.raises(BridgeError, match="Unexpected content type"):
        resolve_ole_part(tampered_data, slide_index=1, shape_name="Figure 1")


def test_rejects_too_many_ole_objects() -> None:
    """A third, independent p:oleObj copy (not just the real, allowlisted
    mc:Choice/mc:Fallback pair) must be rejected rather than picked from."""
    data = (FIXTURES / "single_figure_powerpoint_resaved.pptx").read_bytes()
    with zipfile.ZipFile(FIXTURES / "single_figure_powerpoint_resaved.pptx") as archive:
        slide_xml = archive.read("ppt/slides/slide1.xml").decode()
    import re

    match = re.search(r"<p:oleObj\b.*?</p:oleObj>", slide_xml, re.DOTALL)
    assert match is not None
    tripled = slide_xml.replace("</a:graphicData>", match.group(0) + "</a:graphicData>")
    assert tripled != slide_xml
    tampered_data = _rewrite_zip(data, {"ppt/slides/slide1.xml": tripled.encode()})
    with pytest.raises(BridgeError, match="Expected one or two"):
        resolve_ole_part(tampered_data, slide_index=1, shape_name="Figure 1")


def test_rejects_duplicated_disagreeing_ole_object() -> None:
    data = (FIXTURES / "single_figure_powerpoint_resaved.pptx").read_bytes()
    with zipfile.ZipFile(FIXTURES / "single_figure_powerpoint_resaved.pptx") as archive:
        slide_xml = archive.read("ppt/slides/slide1.xml").decode()
    # The real AlternateContent shape has two p:oleObj copies (one
    # minimal, one full -- see this file's module docstring); make the
    # first one (mc:Choice) disagree on name so the two no longer match.
    tampered = slide_xml.replace(
        '<p:oleObj name="Figure 1" r:id="rId2"',
        '<p:oleObj name="Figure 1 (tampered)" r:id="rId2"',
        1,
    )
    assert tampered != slide_xml
    tampered_data = _rewrite_zip(data, {"ppt/slides/slide1.xml": tampered.encode()})
    with pytest.raises(BridgeError, match="do not agree"):
        resolve_ole_part(tampered_data, slide_index=1, shape_name="Figure 1")


def test_resolves_correctly_after_slides_are_reordered() -> None:
    """The resolver must follow presentation.xml's slide list, not assume
    slide index N is the file slideN.xml."""
    data = (FIXTURES / "multi_figure_powerpoint_resaved.pptx").read_bytes()

    # Swap which relationship ids ppt/presentation.xml's sldIdLst refers to
    # for the first and third slots, simulating a user dragging slide 3 to
    # the front.
    with zipfile.ZipFile(FIXTURES / "multi_figure_powerpoint_resaved.pptx") as archive:
        presentation_xml = archive.read("ppt/presentation.xml").decode()
    reordered_presentation = presentation_xml.replace(
        '<p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId3"/>'
        '<p:sldId id="258" r:id="rId4"/>',
        '<p:sldId id="258" r:id="rId4"/><p:sldId id="257" r:id="rId3"/>'
        '<p:sldId id="256" r:id="rId2"/>',
    )
    assert reordered_presentation != presentation_xml
    reordered_data = _rewrite_zip(
        data, {"ppt/presentation.xml": reordered_presentation.encode()}
    )

    # Slide index 1 now resolves to the old slide 3 (rId4 -> slide3.xml).
    resolved_first = resolve_ole_part(
        reordered_data, slide_index=1, shape_name="Figure 3"
    )
    with zipfile.ZipFile(FIXTURES / "multi_figure_powerpoint_resaved.pptx") as archive:
        expected = archive.read("ppt/embeddings/oleObject3.bin")
    assert resolved_first == expected

    # And the stale assumption (slide index 1 == slide1.xml == "Figure 1")
    # must now be rejected, confirming the resolver is not using it.
    with pytest.raises(BridgeError, match="does not match the selected shape"):
        resolve_ole_part(reordered_data, slide_index=1, shape_name="Figure 1")
