"""Develop a photo and apply the same edit parameters to preview and export."""

from io import BytesIO
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageCms, ImageFilter, ImageOps

from lutcore.colour_management import reference_srgb_to_rec709_gamma24, rec709_gamma24_to_srgb
from lutcore.global_match import fit_global_residual_lut
from lutcore.look_controls import LookControls, apply_look_controls
from lutcore.trilinear import apply_residual_tensor

SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
HUES = (0, 30, 60, 120, 180, 220, 270, 315)


def read_photo(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".arw":
        import rawpy

        try:
            with rawpy.imread(str(path)) as raw:
                data = raw.postprocess(use_camera_wb=True, no_auto_bright=True,
                                       output_color=rawpy.ColorSpace.sRGB, output_bps=16)
        except rawpy.LibRawError as error:
            raise ValueError("无法显影这张 Sony ARW，请检查相机型号和文件。") from error
        return data.astype(np.float32) / 65535
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened)
        profile = image.info.get("icc_profile")
        if profile:
            try:
                image = ImageCms.profileToProfile(
                    image, ImageCms.ImageCmsProfile(BytesIO(profile)), SRGB, outputMode="RGB")
            except ImageCms.PyCMSError as error:
                raise ValueError("无法读取图片内嵌的色彩配置。") from error
        return np.asarray(image.convert("RGB"), dtype=np.float32) / 255


def downsample(rgb, maximum=1200):
    height, width = rgb.shape[:2]
    if max(width, height) <= maximum:
        return rgb
    scale = maximum / max(width, height)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return np.stack([np.asarray(Image.fromarray(channel).resize(size, Image.Resampling.LANCZOS))
                     for channel in rgb.transpose(2, 0, 1)], axis=-1).clip(0, 1)


def tensor(rgb):
    return torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1)))[None]


def fit_photo(original, reference):
    source = reference_srgb_to_rec709_gamma24(tensor(downsample(original)))
    target = reference_srgb_to_rec709_gamma24(tensor(downsample(reference)))
    return apply_look_controls(fit_global_residual_lut(source, target), LookControls(match_strength=100))


def bounded(value, minimum=-100, maximum=100):
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("调色参数无效。") from error
    if not np.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError("调色参数超出范围。")
    return number


def adjust_hsl(rgb, edits):
    maximum, minimum = rgb.amax(dim=1, keepdim=True), rgb.amin(dim=1, keepdim=True)
    chroma = maximum - minimum
    light = (maximum + minimum) / 2
    safe_chroma = chroma.clamp_min(1e-6)
    red, green, blue = rgb.split(1, dim=1)
    hue = torch.where(maximum == red, (green - blue) / safe_chroma,
                      torch.where(maximum == green, (blue - red) / safe_chroma + 2,
                                  (red - green) / safe_chroma + 4)).remainder(6) * 60
    saturation = chroma / (1 - (2 * light - 1).abs()).clamp_min(1e-6)
    adjustment = torch.zeros((3, *hue.shape), dtype=rgb.dtype)
    # Each band has full strength at its centre and blends into its neighbours.
    # Derive the width from the adjacent centres so blue reaches cyan without gaps.
    for index, (center, values) in enumerate(zip(HUES, edits)):
        if values == [0, 0, 0]:
            continue
        previous = HUES[index - 1]
        following = HUES[(index + 1) % len(HUES)]
        distance = (hue - center + 180).remainder(360) - 180
        width = torch.where(distance < 0, (center - previous) % 360, (following - center) % 360)
        weight = (1 - distance.abs() / width).clamp(0, 1)
        weight *= (saturation / .04).clamp(0, 1)
        adjustment += torch.tensor(values, dtype=rgb.dtype).view(3, 1, 1, 1, 1) * weight
    hue = (hue + .6 * adjustment[0]).remainder(360) / 60
    saturation = (saturation * (1 + adjustment[1] / 100)).clamp(0, 1)
    light = (light + adjustment[2] / 250).clamp(0, 1)
    chroma = saturation * (1 - (2 * light - 1).abs())
    channels = [(light - chroma / 2 + chroma *
                 (1 - ((hue - shift + 3).remainder(6) - 3).abs().sub(1).clamp(0, 1)))
                for shift in (0, 2, 4)]
    return torch.cat(channels, dim=1)


def render_photo(rgb, residual, controls):
    strength = bounded(controls.get("strength", 100), 0, 100) / 100
    exposure = bounded(controls.get("exposure", 0), -4, 4)
    contrast = bounded(controls.get("contrast", 0)) / 100
    highlights = bounded(controls.get("highlights", 0)) / 100
    shadows = bounded(controls.get("shadows", 0)) / 100
    sharpen = bounded(controls.get("sharpen", 0), 0, 100)
    hsl = controls.get("hsl", [[0, 0, 0] for _ in HUES])
    if not isinstance(hsl, list) or len(hsl) != len(HUES) or any(
            not isinstance(row, list) or len(row) != 3 for row in hsl):
        raise ValueError("HSL 参数无效。")
    hsl = [[bounded(value) for value in row] for row in hsl]
    result = np.empty(rgb.shape, dtype=np.uint8)
    # Each operation here is per pixel. Render in strips to limit memory for high-resolution ARW.
    for start in range(0, rgb.shape[0], 128):
        strip = rgb[start:start + 128]
        image = tensor(strip)
        if strength:
            display = reference_srgb_to_rec709_gamma24(image)
            image = rec709_gamma24_to_srgb(apply_residual_tensor(display, residual * strength))
        if exposure:
            linear = torch.where(image <= .04045, image / 12.92, ((image + .055) / 1.055) ** 2.4)
            linear *= 2 ** exposure
            image = torch.where(linear <= .0031308, 12.92 * linear, 1.055 * linear ** (1 / 2.4) - .055)
        if contrast or highlights or shadows:
            image = (image - .5) * (1 + .8 * contrast) + .5
            light = (image[:, 0:1] * .2126 + image[:, 1:2] * .7152 + image[:, 2:3] * .0722).clamp(0, 1)
            image += .3 * (shadows * (1 - light) ** 2 + highlights * light ** 2)
        image = image.clamp(0, 1)
        if any(any(row) for row in hsl):
            image = adjust_hsl(image, hsl).clamp(0, 1)
        result[start:start + 128] = (image[0].permute(1, 2, 0).numpy() * 255).round().astype(np.uint8)
    rendered = Image.fromarray(result)
    if sharpen:
        rendered = rendered.filter(ImageFilter.UnsharpMask(radius=1.2, percent=round(2 * sharpen), threshold=2))
    return rendered
