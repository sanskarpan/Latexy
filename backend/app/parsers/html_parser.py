"""
HTML Parser - Extract text from HTML resume files using BeautifulSoup.
"""
import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)


class HTMLParser(AbstractParser):
    """Parser for HTML resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ValueError("beautifulsoup4 not installed. Run: pip install beautifulsoup4 lxml")

        try:
            soup = BeautifulSoup(file_content, 'lxml')

            # Remove purely decorative/navigation elements
            # NOTE: <header> and <footer> are intentionally kept because many resume
            # templates place the candidate's name, contact block, and links there.
            for tag in soup(['script', 'style', 'nav', 'meta', 'link', 'noscript']):
                tag.decompose()

            # Extract section headers
            headers = [h.get_text(strip=True) for h in soup.find_all(['h1', 'h2', 'h3']) if h.get_text(strip=True)]

            # Extract text
            text = soup.get_text(separator='\n')
            # Clean up excessive whitespace
            import re
            text = re.sub(r'\n{3,}', '\n\n', text)
            text = re.sub(r'[ \t]+', ' ', text)
            text = text.strip()

            if not text:
                raise ValueError("Could not extract text from HTML file")

            return self._build_parsed_resume(text, filename, section_hints=headers)

        except Exception as e:
            logger.error(f"Error parsing HTML: {e}")
            raise ValueError(f"Failed to parse HTML: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        try:
            content = file_content.decode('utf-8', errors='ignore')[:500].lower()
            if '<html' not in content and '<!doctype' not in content:
                return False, "Not a valid HTML file"
            return True, None
        except Exception as e:
            return False, str(e)
