"""Compiler logs stay private until recorder confinement authorizes each pass."""
from ...workers.buffered_events import BufferedEventPublisher


def publish_verified_log(job_id, transcript, compiler, publisher):
    with BufferedEventPublisher(job_id, publisher=publisher) as events:
        for line in transcript.text().splitlines():
            lowered = line.lower()
            events.publish("log.line", {"line": line, "source": compiler,
                "is_error": line.startswith("!") or any(word in lowered for word in ("error", "fatal", "undefined control"))})


def interrupted_log(compiler, transcript):
    return "Compilation cancelled before engine output could be validated."
