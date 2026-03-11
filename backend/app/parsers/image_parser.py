"""
Image Parser - OCR-based text extraction from image files and scanned PDFs.
"""
import io
import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)


class ImageParser(AbstractParser):
    """Parser for image files (JPEG, PNG, etc.) using OCR."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        try:
            import pytesseract
            from PIL import Image, ImageEnhance
        except ImportError as e:
            raise ValueError(f"OCR libraries not installed: {e}. Run: pip install pytesseract Pillow")

        try:
            img = Image.open(io.BytesIO(file_content))

            # Pre-process for better OCR accuracy
            img = img.convert('L')  # grayscale
            # Enhance contrast
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)

            # Run OCR
            text = pytesseract.image_to_string(img, lang='eng', config='--psm 6 --oem 3')
            text = text.strip()

            if not text:
                raise ValueError("OCR could not extract text from image (possibly blank or unreadable)")

            return self._build_parsed_resume(text, filename)

        except Exception as e:
            logger.error(f"Error parsing image: {e}")
            raise ValueError(f"Failed to parse image: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
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
    """
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as e:
        raise ValueError(f"OCR PDF libraries not installed: {e}. Run: pip install pdf2image pytesseract")

    images = convert_from_bytes(pdf_content, dpi=200, fmt='PNG')
    pages_text = []
    for img in images:
        text = pytesseract.image_to_string(img, lang='eng', config='--psm 6 --oem 3')
        if text.strip():
            pages_text.append(text.strip())

    return '\n\n'.join(pages_text)
