"""Minimal JSON-over-HTTP primitive shared by the runnable examples."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class JsonResponse:
    status: int
    headers: dict[str, str]
    body: dict[str, Any]


def get_json(url: str, timeout: float = 10) -> JsonResponse:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError(f"Expected an absolute HTTP URL, got: {url}")

    connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connection_type(
        parsed.hostname,
        port=parsed.port,
        timeout=timeout,
    )
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    try:
        connection.request("GET", target, headers={"User-Agent": "resilient-automation-example/1"})
        response = connection.getresponse()
        status = response.status
        headers = dict(response.getheaders())
        payload = response.read()
    finally:
        connection.close()

    body = json.loads(payload) if payload else {}
    if not isinstance(body, dict):
        raise RuntimeError(f"Expected a JSON object from {url}")
    return JsonResponse(status=status, headers=headers, body=body)
