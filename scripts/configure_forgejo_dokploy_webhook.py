#!/usr/bin/env python3
"""Create or update one Qifu Git push webhook for a Dokploy application.

The webhook URL is read from stdin so its Dokploy refresh token is never written
to disk or command-line history.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib import error, request
from urllib.parse import urlparse


def _call(
    *,
    api_root: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, object]:
    headers = {"Authorization": f"token {token}", "Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    target = f"{api_root.rstrip('/')}/{path.lstrip('/')}"
    response = request.Request(target, data=body, headers=headers, method=method)
    try:
        with request.urlopen(response, timeout=20) as result:
            raw = result.read().decode("utf-8", "replace")
            return result.status, json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return exc.code, json.loads(raw) if raw else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default="revan")
    parser.add_argument("--repository", default="smart-data-agent")
    parser.add_argument("--api-root", default="https://xujingbo-jk-git.qifudigitech.com/api/v1")
    parser.add_argument("--token-file", default="~/.config/forgejo/codex-bootstrap-token")
    args = parser.parse_args()

    webhook_url = sys.stdin.read().strip()
    parsed = urlparse(webhook_url)
    if parsed.scheme != "http" or not parsed.netloc or not parsed.path.startswith("/api/deploy/"):
        raise SystemExit("invalid_dokploy_webhook_url")
    token = Path(args.token_file).expanduser().read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("empty_forgejo_token")

    base = f"repos/{args.owner}/{args.repository}/hooks"
    status, response = _call(
        api_root=args.api_root,
        token=token,
        method="GET",
        path=f"{base}?limit=100",
    )
    if status != 200 or not isinstance(response, list):
        raise SystemExit(f"forgejo_hook_list_failed_http_{status}")
    existing = next(
        (
            item
            for item in response
            if isinstance(item, dict) and (item.get("config") or {}).get("url") == webhook_url
        ),
        None,
    )
    payload: dict[str, object] = {
        "config": {"url": webhook_url, "content_type": "json"},
        "events": ["push"],
        "active": True,
    }
    if existing:
        status, _ = _call(
            api_root=args.api_root,
            token=token,
            method="PATCH",
            path=f"{base}/{existing['id']}",
            payload=payload,
        )
        action = "updated"
    else:
        payload["type"] = "gitea"
        status, _ = _call(
            api_root=args.api_root,
            token=token,
            method="POST",
            path=base,
            payload=payload,
        )
        action = "created"
    if status not in {200, 201}:
        raise SystemExit(f"forgejo_webhook_{action}_failed_http_{status}")
    print(f"forgejo_webhook={action} repository={args.owner}/{args.repository}")


if __name__ == "__main__":
    main()
