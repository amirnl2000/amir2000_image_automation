from PIL import Image, ImageDraw, ImageFont
import os
import shutil

try:
    import piexif  # type: ignore
except Exception:
    piexif = None

def resize_and_watermark(src_path, dest_path, thumb_path, desktop_copy_path, watermark_text, font_path, quality=100):
    try:
        # Load original image and EXIF
        with Image.open(src_path) as src_img:
            exif_bytes = src_img.info.get("exif")
            img = src_img.convert("RGB")
        if not exif_bytes and piexif is not None:
            try:
                exif_dict = piexif.load(src_path)
                exif_bytes = piexif.dump(exif_dict)
            except Exception:
                exif_bytes = None

        # Resize to fit within 1500x1000
        max_size = (1500, 1000)
        img.thumbnail(max_size, Image.LANCZOS)

        # Add watermark (multi-line, line-by-line draw)
        draw = ImageDraw.Draw(img)
        font_size = int(img.size[1] * 0.03)
        font = ImageFont.truetype(font_path, font_size)

        lines = watermark_text.strip().split("\n")
        spacing = int(font_size * 0.4)
        line_heights = [draw.textbbox((0, 0), line, font=font)[3] for line in lines]
        total_height = sum(line_heights) + spacing * (len(lines) - 1)

        y_offset = img.height - total_height - 10
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = img.width - text_width - 20
            draw.text((x, y_offset), line, font=font, fill=(255, 255, 255, 200))
            y_offset += line_heights[i] + spacing

        # Save web image with EXIF
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        save_kwargs = {"format": "JPEG", "quality": quality}
        if exif_bytes:
            save_kwargs["exif"] = exif_bytes
        img.save(dest_path, **save_kwargs)

        # Create thumbnail with EXIF
        thumb = img.copy()
        thumb.thumbnail((548, 365), Image.LANCZOS)
        os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
        thumb.save(thumb_path, **save_kwargs)

        # Copy web image to desktop folder
        os.makedirs(os.path.dirname(desktop_copy_path), exist_ok=True)
        shutil.copy2(dest_path, desktop_copy_path)

        print(f"Processed: {os.path.basename(src_path)}")
        return True
    except Exception as e:
        print(f"Error processing {src_path}: {e}")
        return False
