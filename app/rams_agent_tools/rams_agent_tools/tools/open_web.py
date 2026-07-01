from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .telemetry import trace_step


OPEN_WEB_SCHEMA_VERSION = "3d-rams.open-web-signals.v1"
DEFAULT_TAVILY_URL = "https://api.tavily.com/search"
DEFAULT_WARNING_FLAG = "unverified-open-web-signal"
MAX_SNIPPET_CHARS = 500
SENSITIVE_QUERY_KEYS = {
    "access_key",
    "access_token",
    "apikey",
    "api_key",
    "awsaccesskeyid",
    "expires",
    "key",
    "secret",
    "sig",
    "signature",
    "token",
    "x-amz-credential",
    "x-amz-expires",
    "x-amz-security-token",
    "x-amz-signature",
}


def search_open_web_signals(
    location: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
    area_scope: dict[str, Any] | None = None,
    *,
    max_results: int | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return bounded Tavily/open-web signals without making them authoritative evidence."""
    location = location if isinstance(location, dict) else {}
    request = request if isinstance(request, dict) else {}
    area_scope = area_scope if isinstance(area_scope, dict) else {}
    retrieved_at = _timestamp(now)
    query = _query(location, request, area_scope)
    limit = _bounded_max_results(max_results)

    if _env_bool("TAVILY_MOCK_RESPONSE", False):
        open_web = _mock_open_web(query=query, retrieved_at=retrieved_at, max_results=limit)
        return open_web, _trace(open_web, "Deterministic Tavily mock returned open-web signals.")

    if not _env_bool("ENABLE_TAVILY", False):
        open_web = _empty_open_web(
            status="disabled",
            mode="disabled",
            query=query,
            retrieved_at=retrieved_at,
            warnings=["ENABLE_TAVILY is not true; open-web signals were not requested."],
        )
        return open_web, _trace(open_web, "Tavily open-web search is disabled.")

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        open_web = _empty_open_web(
            status="not_configured",
            mode="not_configured",
            query=query,
            retrieved_at=retrieved_at,
            warnings=["TAVILY_API_KEY is not configured; open-web signals were not requested."],
        )
        return open_web, _trace(open_web, "Tavily open-web search is not configured.")

    try:
        response = _call_tavily(query=query, api_key=api_key, max_results=limit)
        items = _items_from_tavily(response, retrieved_at=retrieved_at, max_results=limit)
        warnings = []
        if not items:
            warnings.append("Tavily returned no usable public URL results.")
        open_web = {
            "schemaVersion": OPEN_WEB_SCHEMA_VERSION,
            "status": "ok" if items else "partial",
            "provider": "tavily",
            "mode": "live",
            "sourceBoundary": "non_authoritative_signal",
            "query": _scrub_text(str(response.get("query") or query), 300),
            "retrievedAt": retrieved_at,
            "items": items,
            "warnings": warnings,
            "liveCallAttempted": True,
            "requestId": _scrub_text(str(response.get("request_id") or ""), 120) or None,
            "usage": _safe_usage(response.get("usage")),
        }
        return open_web, _trace(open_web, "Tavily open-web search returned bounded public signals.")
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
        open_web = _empty_open_web(
            status="error",
            mode="live",
            query=query,
            retrieved_at=retrieved_at,
            warnings=[f"Tavily search failed with {exc.__class__.__name__}; no web signals were included."],
        )
        open_web["liveCallAttempted"] = True
        return open_web, _trace(open_web, "Tavily open-web search failed without blocking the workflow.")


def _call_tavily(*, query: str, api_key: str, max_results: int) -> dict[str, Any]:
    payload = {
        "query": query,
        "search_depth": _search_depth(),
        "max_results": max_results,
        "topic": os.getenv("TAVILY_TOPIC", "general").strip().lower() or "general",
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_favicon": False,
        "include_usage": True,
    }
    country = os.getenv("TAVILY_COUNTRY", "").strip().lower()
    if country:
        payload["country"] = country
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        DEFAULT_TAVILY_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=_timeout_seconds()) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Tavily response must be a JSON object.")
    return parsed


def _mock_open_web(*, query: str, retrieved_at: str, max_results: int) -> dict[str, Any]:
    raw = os.getenv("TAVILY_MOCK_RESULTS_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
            items = _items_from_tavily(parsed, retrieved_at=retrieved_at, max_results=max_results)
        elif isinstance(parsed, list):
            items = _items_from_tavily({"results": parsed}, retrieved_at=retrieved_at, max_results=max_results)
        else:
            items = []
    else:
        items = [
            _normalise_item(
                {
                    "title": "Mock public signal for site context",
                    "url": "https://example.org/3d-rams/mock-public-signal",
                    "content": (
                        "Deterministic mock open-web result for public site context. "
                        "Use only as a non-authoritative signal for human review."
                    ),
                    "score": 0.62,
                },
                index=1,
                retrieved_at=retrieved_at,
            )
        ]
    items = [item for item in items if item][:max_results]
    return {
        "schemaVersion": OPEN_WEB_SCHEMA_VERSION,
        "status": "ok" if items else "partial",
        "provider": "tavily",
        "mode": "mock",
        "sourceBoundary": "non_authoritative_signal",
        "query": _scrub_text(query, 300),
        "retrievedAt": retrieved_at,
        "items": items,
        "warnings": [] if items else ["Tavily mock response contained no usable public URL results."],
        "liveCallAttempted": False,
    }


def _items_from_tavily(response: dict[str, Any], *, retrieved_at: str, max_results: int) -> list[dict[str, Any]]:
    raw_results = response.get("results")
    if not isinstance(raw_results, list):
        return []
    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        item = _normalise_item(raw, index=len(items) + 1, retrieved_at=retrieved_at)
        if not item:
            continue
        url = item["url"]
        if url in seen_urls:
            item["flags"].append("duplicate-url-dropped")
            continue
        seen_urls.add(url)
        items.append(item)
        if len(items) >= max_results:
            break
    return items


def _normalise_item(raw: dict[str, Any], *, index: int, retrieved_at: str) -> dict[str, Any] | None:
    url = _safe_url(raw.get("url"))
    if not url:
        return None
    title = _scrub_text(str(raw.get("title") or "Untitled public result"), 180)
    snippet = _scrub_text(str(raw.get("content") or raw.get("snippet") or ""), MAX_SNIPPET_CHARS)
    score = _score(raw.get("score"))
    flags = [DEFAULT_WARNING_FLAG]
    published_at = _published_at(raw)
    if not published_at:
        flags.append("publication-date-unavailable")
    return {
        "id": f"open-web-signal-{_short_hash(url) or index}",
        "title": title,
        "url": url,
        "sourceType": _source_type(url, raw),
        "publishedAt": published_at,
        "retrievedAt": retrieved_at,
        "snippet": snippet,
        "relevance": _relevance(score),
        "confidence": "low",
        "sourceBoundary": "non_authoritative_signal",
        "reasonForInclusion": "Search result matched site, location, or request context; use only as a review signal.",
        "flags": flags,
    }


def _empty_open_web(
    *,
    status: str,
    mode: str,
    query: str,
    retrieved_at: str,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "schemaVersion": OPEN_WEB_SCHEMA_VERSION,
        "status": status,
        "provider": "tavily",
        "mode": mode,
        "sourceBoundary": "non_authoritative_signal",
        "query": _scrub_text(query, 300),
        "retrievedAt": retrieved_at,
        "items": [],
        "warnings": warnings,
        "liveCallAttempted": False,
    }


def _trace(open_web: dict[str, Any], summary: str) -> dict[str, Any]:
    status = str(open_web.get("status") or "not_configured")
    trace_status = "ok" if status == "ok" else "disabled" if status in {"disabled", "not_configured"} else "warning"
    return trace_step(
        "search_open_web_signals",
        trace_status,
        summary,
        {
            "schemaVersion": OPEN_WEB_SCHEMA_VERSION,
            "provider": "tavily",
            "mode": open_web.get("mode"),
            "status": status,
            "itemCount": len(open_web.get("items") or []),
            "sourceBoundary": "non_authoritative_signal",
            "warnings": open_web.get("warnings") or [],
            "liveCallAttempted": bool(open_web.get("liveCallAttempted")),
        },
        source_ids=[item["id"] for item in open_web.get("items") or [] if isinstance(item, dict) and item.get("id")],
    )


def _query(location: dict[str, Any], request: dict[str, Any], area_scope: dict[str, Any]) -> str:
    parts = [
        _text(location.get("label") or request.get("siteName")),
        _text(location.get("authority")),
        _text(request.get("goal")),
        _text(request.get("additionalRequest")),
    ]
    meters = area_scope.get("meters")
    if meters is not None:
        parts.append(f"{meters}m radius")
    parts.extend(["public access", "planning", "flood", "works", "news"])
    return " ".join(part for part in parts if part)[:300]


def _bounded_max_results(max_results: int | None) -> int:
    candidate = max_results if max_results is not None else _env_int("TAVILY_MAX_RESULTS", 5)
    return max(1, min(int(candidate or 5), 10))


def _timeout_seconds() -> int:
    return max(1, min(_env_int("TAVILY_TIMEOUT_SECONDS", 20), 60))


def _search_depth() -> str:
    value = os.getenv("TAVILY_SEARCH_DEPTH", "basic").strip().lower()
    return value if value in {"basic", "advanced", "fast", "ultra-fast"} else "basic"


def _timestamp(now: datetime | None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_url(value: Any) -> str:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.netloc:
        return ""
    query_keys = [part.split("=", 1)[0].lower() for part in parsed.query.split("&") if part]
    if any(_sensitive_query_key(key) for key in query_keys):
        return ""
    if any(secret and secret in text for secret in _secret_values()):
        return ""
    return text[:500]


def _sensitive_query_key(key: str) -> bool:
    return (
        key in SENSITIVE_QUERY_KEYS
        or key.startswith("x-amz-")
        or key.endswith("_token")
        or key.endswith("_secret")
    )


def _scrub_text(value: str, limit: int) -> str:
    scrubbed = value.replace("\r", " ").replace("\n", " ").strip()
    for secret in _secret_values():
        if secret:
            scrubbed = scrubbed.replace(secret, "[redacted]")
    scrubbed = scrubbed.replace("Bearer [redacted]", "[redacted]")
    return " ".join(scrubbed.split())[:limit]


def _secret_values() -> list[str]:
    values = [os.getenv("TAVILY_API_KEY", "")]
    return [value for value in values if len(value) >= 8]


def _published_at(raw: dict[str, Any]) -> str | None:
    for key in ("published_date", "publishedAt", "date"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return _scrub_text(value, 40)
    return None


def _source_type(url: str, raw: dict[str, Any]) -> str:
    topic = str(raw.get("topic") or "").lower()
    lowered = url.lower()
    if topic in {"news", "finance"}:
        return topic
    if any(domain in lowered for domain in ("gov.uk", ".gov/", ".gov.", "nhs.uk")):
        return "official"
    if any(domain in lowered for domain in ("x.com/", "twitter.com/", "facebook.com/", "linkedin.com/")):
        return "social"
    if "blog" in lowered:
        return "blog"
    if any(token in lowered for token in ("news", "press", "article")):
        return "news"
    return "unknown"


def _score(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _relevance(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _safe_usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    usage: dict[str, Any] = {}
    if isinstance(value.get("credits"), (int, float)):
        usage["credits"] = value["credits"]
    return usage or None


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _text(value: Any) -> str:
    return str(value).strip() if value is not None and str(value).strip() else ""
