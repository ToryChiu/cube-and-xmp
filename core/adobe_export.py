"""Export Adobe-readable manual settings and an sRGB reference-match LUT."""

import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import torch

from lutcore.colour_management import rec709_gamma24_to_srgb, reference_srgb_to_rec709_gamma24
from lutcore.cube_export import write_resolve_cube
from lutcore.trilinear import apply_residual_tensor
from photo_edit import bounded

CRS = "http://ns.adobe.com/camera-raw-settings/1.0/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XMP = "adobe:ns:meta/"
ADOBE_HUES = ("Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta")

for prefix, namespace in (("crs", CRS), ("rdf", RDF), ("x", XMP)):
    ET.register_namespace(prefix, namespace)


def adobe_preset(controls, name="Cube & XMP · 手动调色"):
    attributes = {
        "PresetType": "Normal",
        "UUID": uuid.uuid4().hex.upper(),
        "Version": "17.0",
        "ProcessVersion": "15.4",
        "SupportsAmount": "False",
        "SupportsColor": "True",
        "SupportsMonochrome": "True",
        "SupportsOutputReferred": "True",
        "Exposure2012": f"{bounded(controls.get('exposure', 0), -4, 4):+.2f}",
        "Contrast2012": str(round(bounded(controls.get("contrast", 0)))),
        "Highlights2012": str(round(bounded(controls.get("highlights", 0)))),
        "Shadows2012": str(round(bounded(controls.get("shadows", 0)))),
        "Sharpness": str(round(bounded(controls.get("sharpen", 0), 0, 100))),
    }
    hsl = controls.get("hsl", [[0, 0, 0] for _ in ADOBE_HUES])
    if not isinstance(hsl, list) or len(hsl) != len(ADOBE_HUES) or any(
            not isinstance(values, list) or len(values) != 3 for values in hsl):
        raise ValueError("HSL 参数无效。")
    for band, values in zip(ADOBE_HUES, hsl):
        for channel, value in zip(("Hue", "Saturation", "Luminance"), values):
            attributes[f"{channel}Adjustment{band}"] = str(round(bounded(value)))
    root = ET.Element(f"{{{XMP}}}xmpmeta")
    rdf = ET.SubElement(root, f"{{{RDF}}}RDF")
    description = ET.SubElement(rdf, f"{{{RDF}}}Description", {
        f"{{{RDF}}}about": "", **{f"{{{CRS}}}{key}": value for key, value in attributes.items()},
    })
    for field, value in (("Name", name), ("Group", "Cube & XMP")):
        container = ET.SubElement(description, f"{{{CRS}}}{field}")
        alternatives = ET.SubElement(container, f"{{{RDF}}}Alt")
        ET.SubElement(alternatives, f"{{{RDF}}}li", {"xml:lang": "x-default"}).text = value
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def srgb_match_residual(residual, strength, size=33):
    axis = torch.linspace(0, 1, size, dtype=torch.float32)
    blue, green, red = torch.meshgrid(axis, axis, axis, indexing="ij")
    samples = torch.stack((red, green, blue)).reshape(1, 3, size, size * size)
    if strength:
        display = reference_srgb_to_rec709_gamma24(samples)
        matched = rec709_gamma24_to_srgb(apply_residual_tensor(display, residual * strength))
    else:
        matched = samples
    return (matched.clamp(0, 1) - samples).reshape(3, size, size, size)


def write_adobe_bundle(destination: Path, residual, controls):
    strength = bounded(controls.get("strength", 100), 0, 100) / 100
    preset = adobe_preset(controls)
    with TemporaryDirectory() as temporary:
        cube = write_resolve_cube(
            Path(temporary) / "Cube and XMP - sRGB match.cube",
            srgb_match_residual(residual, strength),
            title="Cube and XMP - sRGB match",
            comments=("Input and output: sRGB.", f"Reference match strength baked: {strength:.0%}.",
                      "Manual settings are in the separate XMP preset."),
            output_limits=(0, 1),
        )
        with ZipFile(destination, "w", compression=ZIP_DEFLATED) as bundle:
            bundle.writestr("Cube and XMP - manual adjustments.xmp", preset)
            bundle.write(cube, cube.name)
            bundle.writestr("使用说明.txt", """XMP：先解压 ZIP，再把 XMP 当作用户预设导入 Lightroom 或 Photoshop Camera Raw。
保存了曝光、对比度、高光、阴影、锐化和 HSL。Adobe 的处理曲线与本工具不同，数值是可继续编辑的起点。
CUBE：33 点 sRGB 输入和输出，烘焙了当前强度的自动追色。在 Photoshop 中转换文档到 sRGB 后，
用「颜色查找」调整图层加载。也可在支持加载 CUBE 的 Camera Raw 版本中试用，需核对色彩空间和预览。
CUBE 不包含手动调色或锐化。不同 RAW 显影和处理顺序会影响结果。需要本工具渲染结果时，请导出 JPG。
""")
