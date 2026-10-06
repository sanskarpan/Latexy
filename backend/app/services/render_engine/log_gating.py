"""Lua logs stay private until recorder confinement authorizes publication."""
from ...workers.buffered_events import BufferedEventPublisher


def publish_verified_log(job_id, transcript, compiler, publisher):
    with BufferedEventPublisher(job_id, publisher=publisher) as events:
        for line in transcript.text().splitlines():
            events.publish("log.line", {"line": line, "source": compiler,
                "is_error": line.startswith("!") or "error" in line.lower() or "fatal" in line.lower()})


def interrupted_log(compiler, transcript):
    return "Lua compiler logs withheld: compilation ended before confinement verification." if compiler == "lualatex" else transcript.text()
