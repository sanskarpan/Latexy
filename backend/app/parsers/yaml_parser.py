"""
YAML Parser - Parse YAML resume files.
"""
import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)

YAML_RESUME_KEYS = {'basics', 'work', 'education', 'skills'}


class YAMLParser(AbstractParser):
    """Parser for YAML resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        try:
            import yaml
        except ImportError:
            raise ValueError("PyYAML not installed")

        try:
            text = file_content.decode('utf-8', errors='ignore')
            data = yaml.safe_load(text)
        except Exception as e:
            raise ValueError(f"Invalid YAML file: {e}")

        try:
            if isinstance(data, dict) and YAML_RESUME_KEYS.intersection(data.keys()):
                # Re-use JSON parser's schema parsing by importing it
                from .json_parser import JSONParser
                jp = JSONParser()
                return jp._parse_json_resume_schema(data, filename)
            else:
                # Generic YAML — use YAML string as raw text
                import yaml
                raw = yaml.dump(data, allow_unicode=True, default_flow_style=False)
                return self._build_parsed_resume(raw, filename)
        except Exception as e:
            logger.error(f"Error parsing YAML: {e}")
            raise ValueError(f"Failed to parse YAML: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        try:
            import yaml
            yaml.safe_load(file_content.decode('utf-8', errors='ignore'))
            return True, None
        except Exception as e:
            return False, f"Invalid YAML: {e}"
