"""Explicit AI Gateway transport settings, separate from answer compatibility."""

import re
from dataclasses import asdict, dataclass
from typing import Literal

from warmstart.config import fingerprint
from warmstart.models import WarmstartError


def validate_gateway_id(value: str) -> None:
    # Warmstart deliberately accepts a narrower slug format than arbitrary URLs/names.
    if value == "default" or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?", value):
        raise ValueError("Use an explicit provisioned AI Gateway slug; default is forbidden")


@dataclass(frozen=True)
class GatewaySettings:
    gateway_id: str = ""
    log_mode: Literal["off", "metadata"] = "metadata"

    def validate(self) -> None:
        """Fail before paid work without preventing cache-only service construction."""
        try:
            validate_gateway_id(self.gateway_id)
        except (ValueError, TypeError) as exc:
            raise WarmstartError("AI Gateway routing is not configured") from exc
        if self.log_mode not in ("off", "metadata"):
            raise WarmstartError("Invalid AI Gateway log configuration")

    def signature(self) -> str:
        """Record transport settings in evidence without stranding existing exact hits."""
        return fingerprint(asdict(self))

    def options(self, *, affinity: str | None = None) -> dict[str, object]:
        self.validate()
        headers = {
            "cf-aig-max-attempts": "1",
            "cf-aig-collect-log-payload": "false",
        }
        if affinity is not None:
            headers["x-session-affinity"] = affinity
        return {
            "gateway": {
                "id": self.gateway_id,
                "skipCache": True,
                "collectLog": self.log_mode == "metadata",
                "retries": {"maxAttempts": 1},
            },
            "extraHeaders": headers,
        }
