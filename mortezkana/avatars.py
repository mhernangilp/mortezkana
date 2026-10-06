"""Validate photos and persist compact JPEG avatars rather than original uploads."""
from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000
AVATAR_TABLES = {'participants': 'participants', 'teams': 'teams'}


def normalize_avatar(upload):
    if upload is None or not upload.filename:
        raise ValueError('Selecciona una foto para el avatar.')
    data = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError('La foto debe ocupar como máximo 5 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValueError('Selecciona una foto en formato JPEG, PNG o WebP.')
                source.verify()
            with Image.open(BytesIO(data)) as source:
                source.draft('RGB', (1024, 1024))
                image = ImageOps.fit(ImageOps.exif_transpose(source), (256, 256), method=Image.Resampling.LANCZOS)
                # Flatten transparent photos onto the application's neutral background.
                background = Image.new('RGBA', image.size, (246, 245, 239, 255))
                background.alpha_composite(image.convert('RGBA'))
                output = BytesIO()
                background.convert('RGB').save(output, format='JPEG', quality=85, optimize=True)
                return output.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('La foto tiene demasiados píxeles. Utiliza una imagen de hasta 20 megapíxeles.') from None
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValueError('No se pudo leer la foto. Utiliza una imagen JPEG, PNG o WebP válida.') from None
