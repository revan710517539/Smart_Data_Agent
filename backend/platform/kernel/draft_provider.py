from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from backend.platform.kernel.hermes_endpoint import HermesEndpoint, HermesEndpointError, load_hermes_endpoint
from backend.platform.kernel.store import capability_fingerprint


class DraftProviderError(RuntimeError):
    pass


class LocalDistiller:
    """Deterministic fallback. Never calls Hermes. Safe for analysis isolation."""

    def draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        episode = payload.get("episode") if isinstance(payload.get("episode"), dict) else payload
        trigger = {
            "dataset_id": str(episode.get("dataset_id") or ""),
            "intent_rule_id": str(episode.get("intent_rule_id") or ""),
            "metrics": list(episode.get("metrics") or []),
            "dimensions": list(episode.get("dimensions") or []),
        }
        steps = [str(item) for item in (episode.get("steps") or []) if str(item).strip()]
        if not steps:
            steps = ["supersonic.query", "data.analysis.profile", "conclusion.generate"]
        body = {"steps": steps[:12], "source": "local_distiller"}
        capability_id = str(payload.get("capability_id") or f"learned.{capability_fingerprint({'kind': 'procedure', 'trigger': trigger, 'body': body})[:12]}")
        return {
            "provider": "local_distiller",
            "capability_id": capability_id,
            "title": str(payload.get("title") or "Learned analysis procedure"),
            "description": "Generated from a desensitized analysis episode. Requires four-eye review.",
            "trigger": trigger,
            "body": body,
            "status": "candidate",
        }


class HermesDraftProvider:
    """Optional Hermes backend. Analysis must not call this on the request path."""

    def __init__(self, endpoint: HermesEndpoint | None = None, runner: Any | None = None) -> None:
        self.endpoint = endpoint or load_hermes_endpoint()
        self._runner = runner

    def draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.endpoint.enabled:
            raise DraftProviderError("hermes_disabled")
        prompt = _draft_prompt(payload)
        if self.endpoint.mode == "http":
            raw = self._http_draft(prompt, payload)
        else:
            raw = self._cli_draft(prompt)
        parsed = _parse_draft_json(raw)
        trigger = parsed.get("trigger") if isinstance(parsed.get("trigger"), dict) else {}
        body = parsed.get("body") if isinstance(parsed.get("body"), dict) else {"steps": parsed.get("steps") or []}
        body["source"] = "hermes"
        return {
            "provider": "hermes",
            "capability_id": str(parsed.get("capability_id") or payload.get("capability_id") or "learned.hermes"),
            "title": str(parsed.get("title") or "Hermes drafted procedure")[:200],
            "description": str(parsed.get("description") or "")[:1000],
            "trigger": trigger,
            "body": body,
            "status": "candidate",
            "hermes_mode": self.endpoint.mode,
        }

    def _cli_draft(self, prompt: str) -> str:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("SMART_DATA_AGENT_")
        }
        if self.endpoint.home:
            env["HERMES_HOME"] = self.endpoint.home
        argv = [
            self.endpoint.binary,
            "chat",
            "-q",
            prompt,
            "-Q",
            "--safe-mode",
            "--max-turns",
            "1",
            *self.endpoint.extra_args,
        ]
        runner = self._runner or subprocess.run
        completed = runner(
            argv,
            capture_output=True,
            text=True,
            timeout=self.endpoint.timeout_seconds,
            env=env,
            check=False,
        )
        if getattr(completed, "returncode", 1) not in {0, None}:
            stderr = str(getattr(completed, "stderr", "") or "")[:300]
            raise DraftProviderError(f"hermes_cli_failed:{stderr or 'nonzero_exit'}")
        return str(getattr(completed, "stdout", "") or "")

    def _http_draft(self, prompt: str, payload: dict[str, Any]) -> str:
        body = json.dumps({"prompt": prompt, "episode": payload.get("episode") or {}}, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.endpoint.endpoint}/sda/draft",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.endpoint.timeout_seconds) as response:
                return response.read().decode("utf-8")
        except URLError as exc:
            raise DraftProviderError(f"hermes_http_failed:{exc}") from exc
        except TimeoutError as exc:
            raise DraftProviderError("hermes_http_timeout") from exc


class CompositeDraftProvider:
    """Hermes first when enabled; always fall back to the local distiller."""

    def __init__(self, hermes: HermesDraftProvider | None = None, local: LocalDistiller | None = None) -> None:
        self.hermes = hermes
        self.local = local or LocalDistiller()

    def draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.hermes is not None and self.hermes.endpoint.enabled:
            try:
                return self.hermes.draft(payload)
            except (DraftProviderError, HermesEndpointError, OSError, TimeoutError, json.JSONDecodeError):
                fallback = self.local.draft(payload)
                fallback["fallback_from"] = "hermes"
                return fallback
        return self.local.draft(payload)


def _draft_prompt(payload: dict[str, Any]) -> str:
    episode = payload.get("episode") if isinstance(payload.get("episode"), dict) else payload
    return (
        "You draft a reusable Smart Data Agent procedure from a desensitized episode. "
        "Return ONLY JSON with keys title, description, trigger, body. "
        "trigger may include dataset_id, intent_rule_id, metrics, dimensions, terms. "
        "body.steps is a string array of governed skill ids. "
        "Do not include SQL, row values, credentials, file paths, or account ids.\n"
        f"episode={json.dumps(episode, ensure_ascii=False, sort_keys=True, default=str)[:2000]}"
    )


def _parse_draft_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        raise DraftProviderError("hermes_empty_draft")
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise DraftProviderError("hermes_draft_not_json")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise DraftProviderError("hermes_draft_not_object")
    return payload
