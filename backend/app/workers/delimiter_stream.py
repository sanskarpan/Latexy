"""Incremental filtering for LLM responses wrapped in marker delimiters."""

from dataclasses import dataclass


@dataclass
class DelimitedStreamFilter:
    """Expose only content between delimiters, including split-marker chunks."""

    start: str = "<<<LATEX>>>"
    end: str = "<<<END_LATEX>>>"
    _buffer: str = ""
    _inside: bool = False
    _done: bool = False

    def feed(self, chunk: str) -> str:
        if self._done or not chunk:
            return ""

        self._buffer += chunk
        if not self._inside:
            marker_at = self._buffer.find(self.start)
            if marker_at < 0:
                self._buffer = self._buffer[-(len(self.start) - 1):]
                return ""
            self._inside = True
            self._buffer = self._buffer[marker_at + len(self.start):]

        marker_at = self._buffer.find(self.end)
        if marker_at >= 0:
            visible = self._buffer[:marker_at]
            self._buffer = ""
            self._done = True
            return visible

        safe_length = max(0, len(self._buffer) - (len(self.end) - 1))
        visible = self._buffer[:safe_length]
        self._buffer = self._buffer[safe_length:]
        return visible
