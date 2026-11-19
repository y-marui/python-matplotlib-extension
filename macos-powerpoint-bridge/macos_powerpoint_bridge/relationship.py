"""Resolve one selected PowerPoint shape to its embedded OLE part's bytes.

This module is pure Python with no AppleScript or PowerPoint dependency:
given the already-identified ``slide_index``/``shape_name`` from a real
selection (see :mod:`macos_powerpoint_bridge.applescript`) and the raw
bytes of a ``.pptx`` package, it walks the package's own OOXML
relationships -- never a scan that guesses which embedded object is
"probably" the right one -- to find exactly one embedded OLE Package part
and returns its bytes unchanged. It never inspects, validates, or
extracts the canonical figure package inside that part; that is
``matplotlib_extension.container.extract_ole_native_png()``'s job, run
by the caller on the bytes this module returns.

Every discriminator here is a positive, exact allowlist, per
docs/EDITABLE_FORMAT.md's "OLE Boundary": an unknown, missing,
duplicated, or structurally unexpected relationship, content type,
shape, or target rejects the whole package rather than falling back to
a best guess.

Slides are resolved through ``ppt/presentation.xml``'s slide ID list and
``ppt/_rels/presentation.xml.rels``, not by assuming ``slide_index`` N is
the file ``ppt/slides/slideN.xml``. PowerPoint's slide numbering ("slide
3") reflects the presentation's own slide order, which only matches that
file's XML suffix before the user ever reorders slides; a package whose
file naming happens to collide with a later XML suffix after a reorder
must still resolve to the slide the user actually selected.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree

from macos_powerpoint_bridge.errors import BridgeError

_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"

_SLIDE_RELATIONSHIP_TYPE = f"{_R_NS}/slide"
_OLE_RELATIONSHIP_TYPE = f"{_R_NS}/oleObject"
_OLE_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.oleObject"
_OLE_GRAPHIC_DATA_URI = "http://schemas.openxmlformats.org/presentationml/2006/ole"
_OLE_PROG_ID = "Package"

_EMBEDDED_OLE_TARGET_RE = re.compile(r"^\.\./embeddings/oleObject[1-9][0-9]*\.bin$")

MAX_PRESENTATION_BYTES = 256 * 1024 * 1024


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        return archive.read(name)
    except KeyError as exc:
        raise BridgeError(f"Presentation package is missing {name}") from exc
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise BridgeError(f"Presentation package entry {name} is corrupt") from exc


def _read_xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    data = _read_member(archive, name)
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise BridgeError(f"Presentation package has invalid XML in {name}") from exc


def _resolve_slide_part(archive: zipfile.ZipFile, slide_index: int) -> str:
    """Map a 1-based presentation slide index to its slide part's path."""
    presentation = _read_xml(archive, "ppt/presentation.xml")
    slide_ids = presentation.findall(f"{{{_P_NS}}}sldIdLst/{{{_P_NS}}}sldId")
    if slide_index < 1 or slide_index > len(slide_ids):
        raise BridgeError(
            f"Presentation has no slide at index {slide_index} "
            f"(only {len(slide_ids)} slide(s) listed)"
        )
    slide_rel_id = slide_ids[slide_index - 1].get(f"{{{_R_NS}}}id")
    if not slide_rel_id:
        raise BridgeError(
            f"Slide {slide_index}'s entry in the slide list has no relationship id"
        )

    presentation_rels = _read_xml(archive, "ppt/_rels/presentation.xml.rels")
    matches = [
        relationship
        for relationship in presentation_rels.findall(f"{{{_REL_NS}}}Relationship")
        if relationship.get("Id") == slide_rel_id
    ]
    if len(matches) != 1:
        raise BridgeError(
            f"Expected exactly one relationship for slide {slide_index}, "
            f"found {len(matches)}"
        )
    relationship = matches[0]
    if relationship.get("Type") != _SLIDE_RELATIONSHIP_TYPE:
        raise BridgeError(
            f"Slide {slide_index}'s relationship has an unexpected type: "
            f"{relationship.get('Type')!r}"
        )
    target = relationship.get("Target")
    if not target:
        raise BridgeError(f"Slide {slide_index}'s relationship has no target")
    slide_part = posixpath.normpath(posixpath.join("ppt", target))
    if not re.fullmatch(r"ppt/slides/slide[1-9][0-9]*\.xml", slide_part):
        raise BridgeError(
            f"Slide {slide_index} resolved to an unexpected part: {slide_part!r}"
        )
    if slide_part not in archive.namelist():
        raise BridgeError(f"Presentation package is missing {slide_part}")
    return slide_part


def _resolve_ole_objects(
    graphic_data: ElementTree.Element,
) -> list[ElementTree.Element]:
    """Return the slide's ``p:oleObj`` element(s), structurally anchored to
    one of exactly two allowlisted shapes -- never a loose "1 or 2 anywhere
    in this subtree" count. This bridge's own generator writes a plain,
    unwrapped ``p:oleObj`` directly under ``graphicData``. Real PowerPoint
    for Mac instead wraps it in one ``mc:AlternateContent`` with exactly one
    ``mc:Choice`` and one ``mc:Fallback``, each holding exactly one
    (empirically identical) copy -- confirmed against PowerPoint 16.112.4.
    """
    direct = graphic_data.findall(f"{{{_P_NS}}}oleObj")
    alternate_content = graphic_data.findall(f"{{{_MC_NS}}}AlternateContent")

    if direct and not alternate_content:
        if len(direct) != 1:
            raise BridgeError(f"Expected exactly one p:oleObj, found {len(direct)}")
        return direct

    if alternate_content and not direct:
        if len(alternate_content) != 1:
            raise BridgeError(
                "Expected exactly one mc:AlternateContent, found "
                f"{len(alternate_content)}"
            )
        choices = alternate_content[0].findall(f"{{{_MC_NS}}}Choice")
        fallbacks = alternate_content[0].findall(f"{{{_MC_NS}}}Fallback")
        if len(choices) != 1 or len(fallbacks) != 1:
            raise BridgeError(
                "Expected exactly one mc:Choice and one mc:Fallback, found "
                f"{len(choices)} Choice, {len(fallbacks)} Fallback"
            )
        choice_ole = choices[0].findall(f"{{{_P_NS}}}oleObj")
        fallback_ole = fallbacks[0].findall(f"{{{_P_NS}}}oleObj")
        if len(choice_ole) != 1 or len(fallback_ole) != 1:
            raise BridgeError(
                "Expected exactly one p:oleObj in each of mc:Choice and mc:Fallback"
            )
        return choice_ole + fallback_ole

    raise BridgeError(
        "Expected either a plain p:oleObj or an AlternateContent-wrapped "
        "one, found both or neither"
    )


def _find_ole_object(slide_root: ElementTree.Element, shape_name: str) -> str:
    """Find the slide's one allowlisted OLE graphic frame and return its
    embedded-object relationship id, after confirming it matches
    *shape_name* at every place that name appears."""
    graphic_frames = [
        frame
        for frame in slide_root.iter(f"{{{_P_NS}}}graphicFrame")
        for graphic_data in frame.findall(f"{{{_A_NS}}}graphic/{{{_A_NS}}}graphicData")
        if graphic_data.get("uri") == _OLE_GRAPHIC_DATA_URI
    ]
    if len(graphic_frames) != 1:
        raise BridgeError(
            "Expected exactly one embedded-OLE graphic frame on the slide, "
            f"found {len(graphic_frames)}"
        )
    frame = graphic_frames[0]

    cnv_pr = frame.find(f"{{{_P_NS}}}nvGraphicFramePr/{{{_P_NS}}}cNvPr")
    if cnv_pr is None or cnv_pr.get("name") != shape_name:
        raise BridgeError(
            "The slide's graphic frame name does not match the selected shape"
        )

    graphic_data = frame.find(f"{{{_A_NS}}}graphic/{{{_A_NS}}}graphicData")
    assert graphic_data is not None  # narrowed by the filter above

    ole_objects = _resolve_ole_objects(graphic_data)
    attributes = {
        (
            element.get("name"),
            element.get(f"{{{_R_NS}}}id"),
            element.get("progId"),
            element.get("imgW"),
            element.get("imgH"),
        )
        for element in ole_objects
    }
    if len(attributes) != 1:
        raise BridgeError(
            "The slide's duplicated p:oleObj elements do not agree with each other"
        )
    name, relationship_id, prog_id, _img_w, _img_h = next(iter(attributes))
    if name != shape_name:
        raise BridgeError("The slide's p:oleObj name does not match the selected shape")
    if prog_id != _OLE_PROG_ID:
        raise BridgeError(f"Unexpected OLE object progId: {prog_id!r}")
    if not relationship_id:
        raise BridgeError("The slide's p:oleObj has no relationship id")
    return relationship_id


def _resolve_embedding_target(
    archive: zipfile.ZipFile, slide_part: str, relationship_id: str
) -> str:
    slide_dir = posixpath.dirname(slide_part)
    slide_name = posixpath.basename(slide_part)
    rels_part = f"{slide_dir}/_rels/{slide_name}.rels"
    slide_rels = _read_xml(archive, rels_part)
    matches = [
        relationship
        for relationship in slide_rels.findall(f"{{{_REL_NS}}}Relationship")
        if relationship.get("Id") == relationship_id
    ]
    if len(matches) != 1:
        raise BridgeError(
            f"Expected exactly one relationship {relationship_id!r} on "
            f"{slide_part}, found {len(matches)}"
        )
    relationship = matches[0]
    if relationship.get("Type") != _OLE_RELATIONSHIP_TYPE:
        raise BridgeError(
            f"Unexpected OLE relationship type: {relationship.get('Type')!r}"
        )
    target = relationship.get("Target") or ""
    if not _EMBEDDED_OLE_TARGET_RE.fullmatch(target):
        raise BridgeError(f"Unexpected OLE relationship target: {target!r}")
    embedding_part = posixpath.normpath(posixpath.join(slide_dir, target))
    if not re.fullmatch(r"ppt/embeddings/oleObject[1-9][0-9]*\.bin", embedding_part):
        raise BridgeError(f"Unexpected OLE embedding part: {embedding_part!r}")
    return embedding_part


def _check_content_types(archive: zipfile.ZipFile, embedding_part: str) -> None:
    content_types = _read_xml(archive, "[Content_Types].xml")
    bin_defaults = [
        element
        for element in content_types.findall(f"{{{_CT_NS}}}Default")
        if element.get("Extension") == "bin"
    ]
    if (
        len(bin_defaults) != 1
        or bin_defaults[0].get("ContentType") != _OLE_CONTENT_TYPE
    ):
        raise BridgeError("Unexpected content type for OLE embeddings")
    conflicting_overrides = [
        element
        for element in content_types.findall(f"{{{_CT_NS}}}Override")
        if element.get("PartName") == f"/{embedding_part}"
    ]
    if conflicting_overrides:
        raise BridgeError(f"Unexpected content-type override for {embedding_part}")


def resolve_ole_part(pptx_bytes: bytes, *, slide_index: int, shape_name: str) -> bytes:
    """Return the raw bytes of the one OLE part the selected shape embeds.

    Args:
        pptx_bytes: The raw bytes of a ``.pptx`` package, taken from a
            read-only filesystem copy of an already-saved presentation.
        slide_index: The 1-based slide index PowerPoint reported for the
            current selection.
        shape_name: The exact shape name PowerPoint reported for the
            current selection.

    Returns:
        The embedded OLE Package part's raw bytes, unchanged. The caller
        is responsible for validating and unwrapping them (for example
        via ``matplotlib_extension.container.extract_ole_native_png()``);
        this function never does so itself.

    Raises:
        BridgeError: If the package is not a valid ZIP, or any
            relationship, content type, shape, or target along the way
            is missing, duplicated, or outside this module's exact
            allowlists.
    """
    if len(pptx_bytes) > MAX_PRESENTATION_BYTES:
        raise BridgeError("Presentation package exceeds the size limit")
    try:
        archive = zipfile.ZipFile(BytesIO(pptx_bytes))
    except zipfile.BadZipFile as exc:
        raise BridgeError("Not a valid .pptx package") from exc

    with archive:
        slide_part = _resolve_slide_part(archive, slide_index)
        slide_root = _read_xml(archive, slide_part)
        relationship_id = _find_ole_object(slide_root, shape_name)
        embedding_part = _resolve_embedding_target(archive, slide_part, relationship_id)
        _check_content_types(archive, embedding_part)
        matching_members = [
            info for info in archive.infolist() if info.filename == embedding_part
        ]
        if len(matching_members) != 1:
            raise BridgeError(
                f"Expected exactly one {embedding_part} entry in the "
                f"package, found {len(matching_members)}"
            )
        return _read_member(archive, matching_members[0].filename)
