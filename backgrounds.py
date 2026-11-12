"""Validated raster backgrounds stored locally in per-user application data."""
from io import BytesIO
from pathlib import Path
import os
import tempfile
import threading
import warnings

MAX_UPLOAD=8*1024*1024
MAX_PIXELS=16_000_000
MAX_DIMENSION=8192


def user_data_dir():
    override=os.environ.get("VOX_DATA_DIR")
    if override:return Path(override).expanduser()
    if os.name=="nt":return Path(os.environ.get("LOCALAPPDATA",Path.home()/"AppData/Local"))/"VOX-9K"
    return Path(os.environ.get("XDG_DATA_HOME",Path.home()/".local/share"))/"VOX-9K"


class BackgroundStore:
    def __init__(self,directory):
        self.directory=Path(directory)
        self.path=self.directory/"background.png"
        self.lock=threading.RLock()

    def save(self,data):
        if len(data)>MAX_UPLOAD:raise ValueError("Choose an image under 8 MB.")
        # Pillow is an image decoder, not an inference dependency. Import lazily.
        from PIL import Image,ImageOps,UnidentifiedImageError
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error",Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    if image.format not in ("PNG","JPEG","WEBP"):
                        raise ValueError("Choose a PNG, JPEG or WebP image.")
                    if image.width>MAX_DIMENSION or image.height>MAX_DIMENSION or image.width*image.height>MAX_PIXELS:
                        raise ValueError("Image exceeds 8192 pixels per side or 16 megapixels.")
                    if getattr(image,"is_animated",False):raise ValueError("Choose a still image.")
                    image.load()
                    rgba=ImageOps.exif_transpose(image).convert("RGBA")
                    clean=Image.new("RGBA",rgba.size,(18,18,18,255))
                    clean.alpha_composite(rgba)
                    clean=clean.convert("RGB")
                    # Re-encode pixels only, dropping metadata and any appended content.
                    clean.info.clear()
                    encoded=BytesIO();clean.save(encoded,format="PNG")
            payload=encoded.getvalue()
            if len(payload)>32*1024*1024:raise ValueError("Decoded image is too large.")
        except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise ValueError("Invalid or unsupported image content.") from None
        with self.lock:
            self.directory.mkdir(parents=True,exist_ok=True)
            path=None
            try:
                with tempfile.NamedTemporaryFile(dir=self.directory,suffix=".tmp",delete=False) as f:
                    path=Path(f.name);f.write(payload)
                os.replace(path,self.path)
            finally:
                if path:path.unlink(missing_ok=True)

    def restore(self):
        with self.lock:self.path.unlink(missing_ok=True)
