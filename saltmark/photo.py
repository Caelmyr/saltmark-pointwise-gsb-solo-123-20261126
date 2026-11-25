"""Decode uploaded photographs in the source coordinate space."""
from io import BytesIO
import math

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from image_lab.validation import Invalid

MAX_IMAGE_BYTES = 18 * 1024 * 1024


def png(image):
    stream = BytesIO()
    image.save(stream,format="PNG")
    return stream.getvalue()


def decode(data):
    if len(data) > MAX_IMAGE_BYTES:
        raise Invalid("单张原片不得超过18 MiB")
    try:
        with Image.open(BytesIO(data)) as photo:
            if photo.format not in {"PNG","JPEG","TIFF","BMP","WEBP"} or getattr(photo,"n_frames",1) != 1:
                raise Invalid("请选择单帧 PNG、JPEG、TIFF、BMP 或 WebP")
            if min(photo.size) < 32 or max(photo.size) > 2600 or math.prod(photo.size) > 4_000_000:
                raise Invalid("原片边长须在32–2600 px内，总像素不超过400万")
            normal=ImageOps.exif_transpose(photo).convert("RGB")
            return normal.size,png(normal)
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as error:
        raise Invalid("原片无法解码") from error


def pixels(path):
    with Image.open(path) as photo:
        return np.asarray(photo.convert("RGB"))

