# AMIR_FORCE_LOGS_DIR_IMPORT_START
from pathlib import Path as _amir_force_logs_pathlib_path
import sys as _amir_force_logs_sys

_amir_force_logs_root = _amir_force_logs_pathlib_path(__file__).resolve().parent

while not (_amir_force_logs_root / "utils").exists() and _amir_force_logs_root.parent != _amir_force_logs_root:
    _amir_force_logs_root = _amir_force_logs_root.parent

if str(_amir_force_logs_root) not in _amir_force_logs_sys.path:
    _amir_force_logs_sys.path.insert(0, str(_amir_force_logs_root))

from utils.force_logs_dir import install as _amir_force_logs_install
_amir_force_logs_install()
# AMIR_FORCE_LOGS_DIR_IMPORT_END

from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageCms, ImageOps
import os
import shutil

try:
    import piexif  # type: ignore
except Exception:
    piexif = None


WEB_MAX_SIZE = (1500, 1000)
THUMB_MAX_SIZE = (548, 365)
WEB_JPEG_QUALITY = 100
THUMB_JPEG_QUALITY = 95


def _srgb_profile_bytes():
    srgb_profile = ImageCms.createProfile("sRGB")
    return ImageCms.ImageCmsProfile(srgb_profile).tobytes()


def _convert_to_srgb(src_img):
    icc_bytes = src_img.info.get("icc_profile")
    img = ImageOps.exif_transpose(src_img)

    if icc_bytes:
        try:
            input_profile = ImageCms.ImageCmsProfile(BytesIO(icc_bytes))
            output_profile = ImageCms.createProfile("sRGB")
            img = ImageCms.profileToProfile(
                img,
                input_profile,
                output_profile,
                outputMode="RGB",
                renderingIntent=0,
            )
            return img.convert("RGB")
        except Exception as exc:
            print(f"[WARN] ICC conversion failed, assuming sRGB: {exc}")

    return img.convert("RGB")


def _clean_exif_after_transpose(src_path):
    if piexif is None:
        return None

    try:
        exif_dict = piexif.load(src_path)
        if "0th" in exif_dict:
            exif_dict["0th"][piexif.ImageIFD.Orientation] = 1
        return piexif.dump(exif_dict)
    except Exception:
        return None


def _draw_watermark(img, watermark_text, font_path):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(12, int(img.size[1] * 0.03))
    font = ImageFont.truetype(font_path, font_size)

    lines = watermark_text.strip().split("\n")
    spacing = int(font_size * 0.4)
    line_boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_heights = [box[3] - box[1] for box in line_boxes]
    total_height = sum(line_heights) + spacing * (len(lines) - 1)

    y_offset = img.height - total_height - 10
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = img.width - text_width - 20
        draw.text((x, y_offset), line, font=font, fill=(255, 255, 255, 200))
        y_offset += line_heights[i] + spacing

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _save_jpeg(img, path, quality, exif_bytes, icc_profile_bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_kwargs = {
        "format": "JPEG",
        "quality": quality,
        "subsampling": 0,
        "optimize": True,
        "progressive": True,
        "icc_profile": icc_profile_bytes,
    }
    if exif_bytes:
        save_kwargs["exif"] = exif_bytes
    img.save(path, **save_kwargs)


def resize_and_watermark(src_path, dest_path, thumb_path, desktop_copy_path, watermark_text, font_path, quality=WEB_JPEG_QUALITY):
    try:
        if not font_path or not os.path.exists(font_path):
            raise FileNotFoundError(f"watermark font not found: {font_path}")

        srgb_icc = _srgb_profile_bytes()
        exif_bytes = _clean_exif_after_transpose(src_path)

        with Image.open(src_path) as src_img:
            img = _convert_to_srgb(src_img)

        img.thumbnail(WEB_MAX_SIZE, Image.Resampling.LANCZOS)
        img = _draw_watermark(img, watermark_text, font_path)
        _save_jpeg(img, dest_path, quality, exif_bytes, srgb_icc)

        thumb = img.copy()
        thumb.thumbnail(THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
        _save_jpeg(thumb, thumb_path, THUMB_JPEG_QUALITY, exif_bytes, srgb_icc)

        os.makedirs(os.path.dirname(desktop_copy_path), exist_ok=True)
        shutil.copy2(dest_path, desktop_copy_path)

        print(f"Processed with sRGB ICC: {os.path.basename(src_path)}")
        return True
    except Exception as e:
        print(f"Error processing {src_path}: {e}")
        return False
