"""
Image Parser - OCR-based text extraction from image files and scanned PDFs.
"""
import io
import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)

# Resource limits
MAX_OCR_PAGES = 10          # Max pages to OCR from scanned PDFs (prevents CPU exhaustion)
MAX_IMAGE_PIXELS = 25_000_000  # 25 megapixels — down-sample oversized images
OCR_TIMEOUT_SECONDS = 30    # Tesseract timeout per image/page


class ImageParser(AbstractParser):
    """Parser for image files (JPEG, PNG, etc.) using OCR."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        if not file_content:
            raise ValueError("Image file is empty")

        try:
            import pytesseract
            from PIL import Image, ImageEnhance
        except ImportError as e:
            raise ValueError(f"OCR libraries not installed: {e}. Run: pip install pytesseract Pillow")

        try:
            img = Image.open(io.BytesIO(file_content))

            # Down-sample if too large to prevent memory exhaustion
            w, h = img.size
            if w * h > MAX_IMAGE_PIXELS:
                img.thumbnail((5000, 5000), Image.LANCZOS)

            # Pre-process for better OCR accuracy
            img = img.convert('L')  # grayscale
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)

            # Run OCR with timeout to prevent hanging
            text = pytesseract.image_to_string(
                img,
                lang='eng',
                config='--psm 6 --oem 3',
                timeout=OCR_TIMEOUT_SECONDS,
            )
            text = text.strip()

            if not text:
                raise ValueError("OCR could not extract text from image (possibly blank or unreadable)")

            return self._build_parsed_resume(text, filename)

        except Exception as e:
            logger.error(f"Error parsing image: {e}")
            raise ValueError(f"Failed to parse image: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        if not file_content:
            return False, "File is empty"
        try:
            from PIL import Image
            Image.open(io.BytesIO(file_content))
            return True, None
        except Exception as e:
            return False, f"Invalid image file: {e}"


def ocr_pdf_bytes(pdf_content: bytes) -> str:
    """
    OCR fallback for image-based (scanned) PDFs.
    Converts PDF pages to images then runs Tesseract.
    Limited to MAX_OCR_PAGES pages to prevent CPU/memory exhaustion.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as e:
        raise ValueError(f"OCR PDF libraries not installed: {e}. Run: pip install pdf2image pytesseract")

    # Enforce page limit at conversion time — avoids loading all pages into memory
    images = convert_from_bytes(
        pdf_content,
        dpi=200,
        fmt='PNG',
        first_page=1,
        last_page=MAX_OCR_PAGES,
    )

    if not images:
        return ""

    pages_text = []
    for page_num, img in enumerate(images, start=1):
        try:
            # Down-sample if too large
            w, h = img.size
            if w * h > MAX_IMAGE_PIXELS:
                img.thumbnail((5000, 5000))

            text = pytesseract.image_to_string(
                img,
                lang='eng',
                config='--psm 6 --oem 3',
                timeout=OCR_TIMEOUT_SECONDS,
            )
            if text.strip():
                pages_text.append(text.strip())
        except Exception as page_err:
            logger.warning(f"OCR failed on page {page_num}: {page_err}")
            continue

    return '\n\n'.join(pages_text)
