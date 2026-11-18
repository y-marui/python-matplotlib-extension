"""Static OOXML part templates for the minimal portable PPTX writer.

Every template here is a fixed, schema-required part of a minimal PPTX
package (content types, relationships, slide master/layout, theme) plus the
one slide that carries the OLE object. Several lines hold long, literal Office
Open XML namespace URIs that must not be wrapped (that would insert
whitespace into an attribute value and corrupt it), so this module disables
the line-length check instead.
"""

# ruff: noqa: E501

from typing import Final

PPTX_SLIDE_WIDTH: Final = 9_144_000
PPTX_SLIDE_HEIGHT: Final = 6_858_000

_SLIDE_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
)


def content_types(slide_count: int) -> bytes:
    """Content types for the package: fixed parts plus one Override per slide."""
    slide_overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{index}.xml" '
        f'ContentType="{_SLIDE_CONTENT_TYPE}"/>'
        for index in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="bin" ContentType="application/vnd.openxmlformats-officedocument.oleObject"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
{slide_overrides}
<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
</Types>
""".encode("ascii")


ROOT_RELS: Final = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

CORE_PROPERTIES: Final = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>Figure</dc:title>
</cp:coreProperties>
"""


def app_properties(slide_count: int) -> bytes:
    """Extended properties: just the actual slide count."""
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
<Slides>{slide_count}</Slides>
</Properties>
""".encode("ascii")


def presentation(slide_count: int) -> bytes:
    """Presentation XML: one ``p:sldId`` per slide, in order."""
    slide_ids = "".join(
        f'<p:sldId id="{255 + index}" r:id="rId{1 + index}"/>'
        for index in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
<p:sldIdLst>{slide_ids}</p:sldIdLst>
<p:sldSz cx="{PPTX_SLIDE_WIDTH}" cy="{PPTX_SLIDE_HEIGHT}"/>
<p:notesSz cx="{PPTX_SLIDE_HEIGHT}" cy="{PPTX_SLIDE_WIDTH}"/>
</p:presentation>
""".encode("ascii")


def presentation_rels(slide_count: int) -> bytes:
    """Presentation relationships: slide master, one relationship per slide, theme."""
    slide_relationships = "".join(
        f'<Relationship Id="rId{1 + index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
        f'Target="slides/slide{index}.xml"/>'
        for index in range(1, slide_count + 1)
    )
    theme_id = 2 + slide_count
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
{slide_relationships}
<Relationship Id="rId{theme_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>
</Relationships>
""".encode("ascii")


SLIDE_MASTER: Final = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:cSld>
<p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>
<p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr/>
</p:spTree>
</p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
</p:sldMaster>
"""

SLIDE_MASTER_RELS: Final = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>
"""

SLIDE_LAYOUT: Final = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">
<p:cSld name="Blank">
<p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr/>
</p:spTree>
</p:cSld>
<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>
"""

THEME: Final = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office Theme">
<a:themeElements>
<a:clrScheme name="Office">
<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>
<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
<a:dk2><a:srgbClr val="44546A"/></a:dk2>
<a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>
<a:accent1><a:srgbClr val="4472C4"/></a:accent1>
<a:accent2><a:srgbClr val="ED7D31"/></a:accent2>
<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3>
<a:accent4><a:srgbClr val="FFC000"/></a:accent4>
<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5>
<a:accent6><a:srgbClr val="70AD47"/></a:accent6>
<a:hlink><a:srgbClr val="0563C1"/></a:hlink>
<a:folHlink><a:srgbClr val="954F72"/></a:folHlink>
</a:clrScheme>
<a:fontScheme name="Office">
<a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>
<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>
</a:fontScheme>
<a:fmtScheme name="Office">
<a:fillStyleLst>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
</a:fillStyleLst>
<a:lnStyleLst>
<a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
<a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
</a:lnStyleLst>
<a:effectStyleLst>
<a:effectStyle><a:effectLst/></a:effectStyle>
<a:effectStyle><a:effectLst/></a:effectStyle>
<a:effectStyle><a:effectLst/></a:effectStyle>
</a:effectStyleLst>
<a:bgFillStyleLst>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
</a:bgFillStyleLst>
</a:fmtScheme>
</a:themeElements>
</a:theme>
"""


def slide_rels(index: int) -> bytes:
    """One slide's relationships: its layout, its OLE object, its fallback image."""
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="../embeddings/oleObject{index}.bin"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image{index}.png"/>
</Relationships>
""".encode("ascii")


def slide_xml(index: int, x: int, y: int, cx: int, cy: int) -> bytes:
    """Render one slide's XML: a single OLE-object graphic frame."""
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:cSld>
<p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr/>
<p:graphicFrame>
<p:nvGraphicFramePr>
<p:cNvPr id="2" name="Figure {index}"/>
<p:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></p:cNvGraphicFramePr>
<p:nvPr/>
</p:nvGraphicFramePr>
<p:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></p:xfrm>
<a:graphic>
<a:graphicData uri="http://schemas.openxmlformats.org/presentationml/2006/ole">
<p:oleObj name="Figure {index}" r:id="rId2" imgW="{cx}" imgH="{cy}" progId="Package">
<p:pic>
<p:nvPicPr><p:cNvPr id="0" name=""/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
<p:blipFill><a:blip r:embed="rId3"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
<p:spPr>
<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
</p:spPr>
</p:pic>
</p:oleObj>
</a:graphicData>
</a:graphic>
</p:graphicFrame>
</p:spTree>
</p:cSld>
<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>
""".encode("ascii")
