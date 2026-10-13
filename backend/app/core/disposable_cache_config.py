"""Explicit, secret-safe transport configuration for disposable cache replicas."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator


class DisposableCacheEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    transport: Literal["redis", "rest"]
    url: SecretStr
    token: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def validate_transport(self):
        try:
            parsed = urlsplit(self.url.get_secret_value())
            port = parsed.port
            valid = bool(parsed.hostname) and not parsed.fragment and not parsed.query
            if self.transport == "rest":
                valid = valid and parsed.scheme == "https" and parsed.path in {"", "/"}
                valid = valid and not parsed.username and not parsed.password
                valid = valid and bool(self.token.get_secret_value().strip())
            else:
                valid = valid and parsed.scheme in {"redis", "rediss"}
                valid = valid and (not parsed.path.strip("/") or parsed.path.strip("/").isdigit())
                valid = valid and not self.token.get_secret_value()
            valid = valid and (port is None or 0 < port < 65536)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Invalid disposable cache endpoint: use redis/rediss URL or HTTPS REST URL plus token")
        return self
