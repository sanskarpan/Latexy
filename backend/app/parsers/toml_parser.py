"""
TOML Parser - Parse TOML resume files (Python 3.11+ built-in tomllib).
"""
import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)


class TOMLParser(AbstractParser):
    """Parser for TOML resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib  # fallback for older Python
            except ImportError:
                raise ValueError("TOML support requires Python 3.11+ (tomllib built-in) or tomli package")

        if not file_content:
            raise ValueError("TOML file is empty")
        try:
            # TOML is strictly UTF-8; reject files with invalid encoding rather than silently dropping bytes
            try:
                text = file_content.decode('utf-8')
            except UnicodeDecodeError as ue:
                raise ValueError(f"TOML file contains invalid UTF-8 encoding: {ue}")
            data = tomllib.loads(text)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Invalid TOML file: {e}")

        try:
            # Check if it follows JSON Resume schema (basics, work, education, skills)
            from .json_parser import JSON_RESUME_KEYS, JSONParser
            if isinstance(data, dict) and JSON_RESUME_KEYS.intersection(data.keys()):
                jp = JSONParser()
                return jp._parse_json_resume_schema(data, filename)
        except Exception:
            pass

        # Generic TOML — dump to text for LLM
        try:
            import yaml
            raw = yaml.dump(data, allow_unicode=True, default_flow_style=False)
        except Exception:
            import json
            raw = json.dumps(data, indent=2, ensure_ascii=False)

        return self._build_parsed_resume(raw, filename)

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        if not file_content:
            return False, "File is empty"
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib
            try:
                text = file_content.decode('utf-8')
            except UnicodeDecodeError as ue:
                return False, f"TOML file contains invalid UTF-8 encoding: {ue}"
            tomllib.loads(text)
            return True, None
        except Exception as e:
            return False, f"Invalid TOML: {e}"
