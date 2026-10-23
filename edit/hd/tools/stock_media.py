"""Frozen Pexels and Pixabay media acquisition with explicit stop states.

The module deliberately separates search, staging, validation, and publication.
Provider connection values are request-only data and never enter a frozen
snapshot or published provenance record.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Iterator, Mapping
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import broll_media as _broll_media


PEXELS_API_HOSTS = frozenset({"api.pexels.com"})
PEXELS_CDN_HOSTS = frozenset({"videos.pexels.com", "images.pexels.com"})
PIXABAY_API_HOSTS = frozenset({"pixabay.com"})
PIXABAY_CDN_HOSTS = frozenset({"cdn.pixabay.com", "pixabay.com"})

_PEXELS_PAGE_HOSTS = frozenset({"pexels.com", "www.pexels.com"})
_PIXABAY_PAGE_HOSTS = frozenset({"pixabay.com", "www.pixabay.com"})
_PEXELS_CDN_QUERY = frozenset(
    {"auto", "cs", "fit", "h", "q", "w", "crop", "dpr"}
)
_PIXABAY_CDN_QUERY = frozenset({"download", "attachment"})
_NON_RECORD_QUERY_PARTS = (
    "auth",
    "credential",
    "expires",
    "key",
    "policy",
    "signature",
    "signed",
    "token",
)
_MEDIA_TYPES = frozenset({"image", "video"})
_MIME_FORMATS = {
    "image/jpeg": ("image", "jpeg", frozenset({".jpg", ".jpeg"})),
    "image/png": ("image", "png", frozenset({".png"})),
    "image/webp": ("image", "webp", frozenset({".webp"})),
    "video/mp4": ("video", "mp4", frozenset({".mp4", ".m4v"})),
    "video/webm": ("video", "webm", frozenset({".webm"})),
    "video/quicktime": ("video", "mov", frozenset({".mov"})),
}
_HASH_CHUNK = 1024 * 1024
_SEARCH_LIMIT = 5 * 1024 * 1024
_DEFAULT_MEDIA_LIMIT = 250 * 1024 * 1024
_DEFAULT_TIMEOUT = 30.0
_MAX_REDIRECTS = 2
_SNAPSHOT_KEYS = {
    "schema_version",
    "provider",
    "query",
    "media_type",
    "query_sha256",
    "searched_at",
    "candidate_ids",
    "result_order",
    "candidates",
    "response_sha256",
    "search_generation",
    "snapshot_sha256",
}
_CANDIDATE_KEYS = {
    "provider_asset_id",
    "author",
    "asset_page",
    "download_url",
    "media_type",
    "mime_type",
    "format",
    "extension",
    "width",
    "height",
    "dimensions_source",
    "duration",
    "license_name",
    "license_version",
}
_JOURNAL_KEYS = {
    "schema_version", "state", "idempotency_key", "nonce", "provider",
    "provider_asset_id", "search_generation", "snapshot_sha256", "query_sha256",
    "staging_job_path", "planned_job_path", "planned_license_snapshot",
    "license_staging_job_path", "media_type", "format", "mime_type",
    "expected_identity", "downloaded_at", "byte_count", "sha256",
    "actual_width", "actual_height", "dimensions_source",
    "license_record", "license_sha256", "license_identity",
}
_LICENSE_KEYS = {
    "schema_version", "idempotency_key", "search_generation",
    "snapshot_sha256", "query_sha256", "provider", "provider_asset_id",
    "author", "asset_page", "license_name", "license_version",
    "downloaded_at", "byte_count", "sha256", "job_path",
    "license_snapshot",
}
_NON_RECORD_FIELD_MARKERS = (
    "authorization", "cookie", "api_key", "apikey", "access_key",
    "signature", "token", "credential", "secret",
)

__all__ = [
    "PEXELS_API_HOSTS",
    "PEXELS_CDN_HOSTS",
    "PIXABAY_API_HOSTS",
    "PIXABAY_CDN_HOSTS",
    "StockMediaError",
    "TransportResponse",
    "DownloadRecord",
    "PexelsAdapter",
    "PixabayAdapter",
    "freeze_search_snapshot",
    "stable_idempotency_key",
    "download_to_staging",
    "validate_downloaded_media",
    "publish_frozen_asset",
]


class StockMediaError(RuntimeError):
    """Raised when stock acquisition cannot satisfy its provider contract."""


def _fail(message: str) -> StockMediaError:
    return StockMediaError(message)


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: Any


@dataclass(frozen=True)
class DownloadRecord(Mapping[str, object]):
    schema_version: int
    status: str
    provider: str
    provider_asset_id: str
    search_generation: str
    snapshot_sha256: str
    query_sha256: str
    idempotency_key: str
    journal_job_path: str
    journal_sha256: str
    staging_job_path: str
    license_staging_job_path: str
    planned_job_path: str
    planned_license_snapshot: str
    media_type: str
    format: str
    mime_type: str
    downloaded_at: str
    byte_count: int
    sha256: str
    expected_identity: tuple[int, ...]
    actual_width: int
    actual_height: int
    dimensions_source: str
    license_sha256: str | None

    def __getitem__(self, key: str) -> object:
        if key not in self.__dataclass_fields__:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self.__dataclass_fields__)

    def __len__(self) -> int:
        return len(self.__dataclass_fields__)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _UrllibTransport:
    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirect)

    def request(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> TransportResponse:
        request = Request(url, headers=headers, method="GET")
        try:
            opened = self._opener.open(request, timeout=timeout)
        except HTTPError as failure:
            return TransportResponse(failure.code, dict(failure.headers), failure)
        return TransportResponse(opened.status, dict(opened.headers), opened)


def _text(value: object, *, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise _fail(f"{label} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise _fail(f"{label} is invalid")
    return value


def _utf8_text(value: object, *, label: str, max_bytes: int) -> str:
    text = _text(value, label=label)
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        raise _fail(f"{label} is invalid") from None
    if len(encoded) > max_bytes:
        raise _fail(f"{label} is too long")
    return text


def _positive_integer(value: object, *, label: str, allow_zero: bool = False) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1):
        raise _fail(f"{label} is invalid")
    return value


def _sha256(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _fail(f"{label} is invalid")
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise _fail("stock media data is not canonical") from None


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _timestamp(clock: Callable[[], object] | None) -> str:
    try:
        value = (clock or (lambda: datetime.now(timezone.utc)))()
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail("stock media clock failed") from None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise _fail("stock media clock must be timezone-aware")
        return value.isoformat()
    if type(value) is str:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise _fail("stock media clock returned an invalid timestamp") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise _fail("stock media clock must be timezone-aware")
        return value
    raise _fail("stock media clock returned an invalid timestamp")


def _rfc3339(value: object, *, label: str) -> str:
    text = _text(value, label=label)
    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        text,
    ) is None:
        raise _fail(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise _fail(f"{label} is invalid") from None
    if parsed.utcoffset() is None:
        raise _fail(f"{label} is invalid")
    return text


def _normalized_query_spec(
    provider: str,
    query: str,
    media_type: str,
    *,
    per_page: int,
) -> dict[str, object]:
    return {
        "media_type": media_type,
        "parameters": {
            "per_page": per_page,
            "safesearch": provider == "pixabay",
        },
        "query": query,
    }


def _query_sha256(
    provider: str,
    query: str,
    media_type: str,
    *,
    per_page: int,
) -> str:
    return _digest(
        _normalized_query_spec(provider, query, media_type, per_page=per_page)
    )


def stable_idempotency_key(
    job_id: str,
    segment_id: str,
    component_id: str,
    strategy_revision: int,
    provider: str,
    query_sha256: str,
) -> str:
    """Return the canonical six-field identity for a stock component."""
    fields = {
        "job_id": _text(job_id, label="job_id"),
        "segment_id": _text(segment_id, label="segment_id"),
        "component_id": _text(component_id, label="component_id"),
        "strategy_revision": _positive_integer(
            strategy_revision, label="strategy_revision"
        ),
        "provider": _text(provider, label="provider"),
        "query_sha256": _sha256(query_sha256, label="query_sha256"),
    }
    if fields["provider"] not in {"pexels", "pixabay"}:
        raise _fail("provider is invalid")
    return _digest(fields)


def _headers(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise _fail("stock response headers are invalid")
    result: dict[str, str] = {}
    for key, item in value.items():
        if type(key) is not str or type(item) is not str:
            raise _fail("stock response headers are invalid")
        normalized = key.lower()
        if normalized in result:
            raise _fail("stock response headers are ambiguous")
        result[normalized] = item.strip()
    return result


def _response(value: object) -> TransportResponse:
    if type(value) is not TransportResponse:
        raise _fail("stock transport returned an invalid response")
    try:
        status = value.status
        headers = _headers(value.headers)
        body = value.body
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail("stock transport returned an invalid response") from None
    if type(status) is not int or not 100 <= status <= 599:
        raise _fail("stock transport returned an invalid response")
    return TransportResponse(status, headers, body)


def _iter_body(body: object) -> Iterable[bytes]:
    if type(body) is bytes:
        yield body
        return
    if type(body) is bytearray:
        yield bytes(body)
        return
    try:
        reader = getattr(body, "read", None)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail("stock response body failed") from None
    if callable(reader):
        while True:
            try:
                chunk = reader(_HASH_CHUNK)
            except BaseException as failure:
                if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                    raise
                raise _fail("stock response body failed") from None
            if type(chunk) not in {bytes, bytearray}:
                raise _fail("stock response body is invalid")
            if len(chunk) == 0:
                return
            yield bytes(chunk)
        return
    try:
        iterator = iter(body)  # type: ignore[arg-type]
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail("stock response body failed") from None
    while True:
        try:
            chunk = next(iterator)
        except StopIteration:
            return
        except BaseException as failure:
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise
            raise _fail("stock response body failed") from None
        if type(chunk) not in {bytes, bytearray}:
            raise _fail("stock response body is invalid")
        yield bytes(chunk)


def _close_body(body: object) -> None:
    try:
        closer = getattr(body, "close", None)
        if callable(closer):
            closer()
    except Exception:
        pass


def _read_limited(response: TransportResponse, limit: int) -> bytes:
    collected = bytearray()
    try:
        for chunk in _iter_body(response.body):
            if len(collected) + len(chunk) > limit:
                raise _fail("stock response exceeds the size limit")
            collected.extend(chunk)
        return bytes(collected)
    finally:
        _close_body(response.body)


def _has_disallowed_decoding(value: str) -> bool:
    lowered = value.lower()
    return any(
        token in lowered
        for token in ("%00", "%0a", "%0d", "%2f", "%5c", "%2e%2e")
    )


def _benign_query_value(key: str, value: str) -> bool:
    if key in {"h", "w"}:
        return value.isascii() and value.isdecimal() and 1 <= int(value) <= 10000
    if key == "q":
        return value.isascii() and value.isdecimal() and 1 <= int(value) <= 100
    if key == "dpr":
        try:
            return 0.1 <= float(value) <= 10 and re.fullmatch(r"\d+(?:\.\d+)?", value) is not None
        except ValueError:
            return False
    allowed = {
        "auto": {"compress", "format"},
        "cs": {"tinysrgb", "srgb"},
        "fit": {"crop", "clip", "max", "scale"},
        "fm": {"jpg", "jpeg", "png", "webp"},
        "download": {"1", "true"},
        "attachment": {"1", "true"},
    }
    if key in allowed:
        return value.lower() in allowed[key]
    return key == "crop" and re.fullmatch(r"[A-Za-z0-9_,.-]{1,64}", value) is not None


def _normalize_provider_url(
    value: object,
    *,
    hosts: frozenset[str],
    query_keys: frozenset[str] = frozenset(),
    allow_query: bool = False,
    permitted_provider_query_keys: frozenset[str] = frozenset(),
    constrain_query_values: bool = True,
) -> str:
    url = _text(value, label="URL")
    if url.startswith("//") or "\\" in url or _has_disallowed_decoding(url):
        raise _fail("stock URL does not match the provider URL contract")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise _fail("stock URL does not match the provider URL contract") from None
    if (
        parsed.scheme != "https"
        or not host
        or host not in hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
        or "%" in parsed.netloc
    ):
        raise _fail("stock URL does not match the provider URL contract")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise _fail("stock URL does not match the provider URL contract")
    if parsed.query and not allow_query:
        raise _fail("stock URL query is not allowed")

    canonical_query = ""
    if parsed.query:
        try:
            pairs = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
            )
        except (UnicodeError, ValueError):
            raise _fail("stock URL query does not match the provider contract") from None
        seen: set[str] = set()
        canonical: list[tuple[str, str]] = []
        for raw_key, raw_value in pairs:
            key = raw_key.lower()
            if (
                not key
                or key in seen
                or key not in query_keys
                or (
                    key not in permitted_provider_query_keys
                    and any(part in key for part in _NON_RECORD_QUERY_PARTS)
                )
                or not raw_value
                or any(ord(character) < 32 or ord(character) == 127 for character in raw_value)
                or len(raw_value) > 128
                or (
                    constrain_query_values
                    and key in query_keys - permitted_provider_query_keys
                    and not _benign_query_value(key, raw_value)
                )
            ):
                raise _fail("stock URL query does not match the provider contract")
            seen.add(key)
            canonical.append((key, raw_value))
        canonical_query = urlencode(sorted(canonical))
    return urlunsplit(("https", host, parsed.path, canonical_query, ""))


def _extension(url: str) -> str:
    suffix = PurePosixPath(urlsplit(url).path).suffix.lower()
    if not suffix:
        raise _fail("stock media URL has no extension")
    return suffix


def _format_from_mime(mime_type: str, extension: str, media_type: str) -> str:
    details = _MIME_FORMATS.get(mime_type.lower())
    if details is None:
        raise _fail("stock media MIME is unsupported")
    expected_media, media_format, extensions = details
    if expected_media != media_type or extension not in extensions:
        raise _fail("stock media MIME and extension disagree")
    return media_format


_IMAGE_MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_VIDEO_MIMES = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}


def _candidate(adapter: Any, asset_id: object, author: object, page: object, url: object,
               media_type: str, mime: object, width: object, height: object,
               duration: object = None, dimensions_source: str = "provider_variant") -> dict[str, object]:
    if type(asset_id) is int:
        candidate_id = str(_positive_integer(asset_id, label="provider asset id"))
    elif type(asset_id) is str:
        candidate_id = _text(asset_id, label="provider asset id")
    else:
        raise _fail("provider asset id is invalid")
    normalized_url = _normalize_provider_url(
        url, hosts=adapter.cdn_hosts, query_keys=adapter.cdn_query, allow_query=True
    )
    extension = _extension(normalized_url)
    checked_mime = _text(mime, label="stock MIME").lower()
    checked_duration = None if duration is None else _positive_integer(duration, label="stock duration")
    if dimensions_source not in {
        "provider_variant", "provider_declared", "url_variant", "probe"
    }:
        raise _fail("dimensions_source is invalid")
    return {
        "provider_asset_id": candidate_id,
        "author": _text(author, label="stock author"),
        "asset_page": _normalize_provider_url(page, hosts=adapter.page_hosts),
        "download_url": normalized_url,
        "media_type": media_type,
        "mime_type": checked_mime,
        "format": _format_from_mime(checked_mime, extension, media_type),
        "extension": extension,
        "width": _positive_integer(width, label="stock width"),
        "height": _positive_integer(height, label="stock height"),
        "dimensions_source": _text(dimensions_source, label="dimensions_source"),
        "duration": checked_duration,
        "license_name": adapter.license_name,
        "license_version": adapter.license_version,
    }


def _video_variant(adapter: Any, value: object, *, mime_field: str | None, size_field: str | None) -> tuple[int, int, int, int, str, str]:
    if type(value) is not dict:
        raise _fail(f"{adapter.name} result is malformed")
    width = _positive_integer(value.get("width"), label="stock width")
    height = _positive_integer(value.get("height"), label="stock height")
    size = 0 if size_field is None else _positive_integer(value.get(size_field), label="stock size")
    url = _normalize_provider_url(value.get("link" if adapter.name == "pexels" else "url"),
                              hosts=adapter.cdn_hosts, query_keys=adapter.cdn_query, allow_query=True)
    mime = _text(value.get(mime_field), label="stock MIME").lower() if mime_field else _VIDEO_MIMES.get(_extension(url))
    if mime is None:
        raise _fail(f"{adapter.name} video format is unsupported")
    _format_from_mime(mime, _extension(url), "video")
    return width * height, size, width, height, mime, url


class PexelsAdapter:
    name = "pexels"
    api_hosts = PEXELS_API_HOSTS
    cdn_hosts = PEXELS_CDN_HOSTS
    page_hosts = _PEXELS_PAGE_HOSTS
    cdn_query = _PEXELS_CDN_QUERY
    connection_environment = "PEXELS_API_KEY"
    license_name = "Pexels License"
    license_version = "pexels-license-v1"
    per_page = 40

    def search_request(self, query: str, media_type: str, connection_value: str) -> tuple[str, dict[str, str]]:
        path = "v1/videos/search" if media_type == "video" else "v1/search"
        url = "https://api.pexels.com/{0}?{1}".format(
            path,
            urlencode({"query": query, "per_page": self.per_page}),
        )
        return url, {"Accept": "application/json", "Authorization": connection_value}

    def parse(self, payload: object, media_type: str) -> list[dict[str, object]]:
        key = "videos" if media_type == "video" else "photos"
        items = payload.get(key) if type(payload) is dict else None
        if type(items) is not list:
            raise _fail("Pexels response is malformed")
        results: list[dict[str, object]] = []
        for item in items:
            try:
                if type(item) is not dict:
                    raise _fail("Pexels result is malformed")
                if media_type == "video":
                    variants = item["video_files"]
                    if type(item["user"]) is not dict or type(variants) is not list or not variants:
                        raise _fail("Pexels result is malformed")
                    valid = []
                    for variant in variants:
                        try:
                            checked = _video_variant(
                                self, variant, mime_field="file_type",
                                size_field=None,
                            )
                            if checked[4] == "video/mp4":
                                valid.append(checked)
                        except StockMediaError:
                            continue
                    if not valid:
                        raise _fail("Pexels result has no usable MP4 variant")
                    _, _, width, height, mime, url = sorted(
                        valid, key=lambda variant: (-variant[0], -variant[3], variant[5]))[0]
                    results.append(_candidate(self, item["id"], item["user"]["name"], item["url"], url,
                                              "video", mime, width, height, item.get("duration")))
                else:
                    if type(item["src"]) is not dict:
                        raise _fail("Pexels result is malformed")
                    url = item["src"]["original"]
                    mime = _IMAGE_MIMES.get(_extension(str(url)))
                    if mime is None:
                        raise _fail("Pexels image format is unsupported")
                    query_dimensions = dict(
                        parse_qsl(urlsplit(str(url)).query, keep_blank_values=True)
                    )
                    if "w" in query_dimensions and "h" in query_dimensions:
                        width = _positive_integer(
                            int(query_dimensions["w"]), label="stock width"
                        )
                        height = _positive_integer(
                            int(query_dimensions["h"]), label="stock height"
                        )
                        dimensions_source = "url_variant"
                    else:
                        width, height = item["width"], item["height"]
                        dimensions_source = "provider_declared"
                    results.append(_candidate(self, item["id"], item["photographer"], item["url"], url,
                                              "image", mime, width, height,
                                              dimensions_source=dimensions_source))
            except StockMediaError:
                raise
            except (KeyError, TypeError, ValueError):
                raise _fail("Pexels result is malformed") from None
        return results


class PixabayAdapter:
    name = "pixabay"
    api_hosts = PIXABAY_API_HOSTS
    cdn_hosts = PIXABAY_CDN_HOSTS
    page_hosts = _PIXABAY_PAGE_HOSTS
    cdn_query = _PIXABAY_CDN_QUERY
    connection_environment = "PIXABAY_API_KEY"
    license_name = "Pixabay Content License"
    license_version = "pixabay-content-license-v1"
    per_page = 40

    def search_request(self, query: str, media_type: str, connection_value: str) -> tuple[str, dict[str, str]]:
        path = "/api/videos/" if media_type == "video" else "/api/"
        query_string = urlencode({"key": connection_value, "q": query, "per_page": self.per_page, "safesearch": "true"})
        return f"https://pixabay.com{path}?{query_string}", {"Accept": "application/json"}

    def parse(self, payload: object, media_type: str) -> list[dict[str, object]]:
        if type(payload) is not dict or type(payload.get("hits")) is not list:
            raise _fail("Pixabay response is malformed")
        results: list[dict[str, object]] = []
        for item in payload["hits"]:
            try:
                if type(item) is not dict:
                    raise _fail("Pixabay result is malformed")
                if media_type == "video":
                    variants = item["videos"]
                    if type(variants) is not dict or not variants:
                        raise _fail("Pixabay result is malformed")
                    for name in variants:
                        if type(name) is not str:
                            raise _fail("Pixabay result is malformed")
                    chosen = None
                    for name in ("large", "medium", "small", "tiny"):
                        if name not in variants:
                            continue
                        try:
                            chosen = _video_variant(self, variants[name], mime_field=None, size_field="size")
                        except StockMediaError:
                            continue
                        break
                    if chosen is None:
                        raise _fail("Pixabay result has no usable video variant")
                    _, _, width, height, mime, download_url = chosen
                    duration = item.get("duration")
                else:
                    if item.get("webformatURL"):
                        width, height = item["webformatWidth"], item["webformatHeight"]
                        download_url = item["webformatURL"]
                        dimensions_source = "provider_variant"
                    else:
                        width, height = item["imageWidth"], item["imageHeight"]
                        download_url = item["largeImageURL"]
                        dimensions_source = "provider_declared"
                    mime = _IMAGE_MIMES.get(_extension(str(download_url)))
                    if mime is None:
                        raise _fail("Pixabay image format is unsupported")
                    duration = None
                results.append(_candidate(
                    self, item["id"], item["user"], item["pageURL"], download_url,
                    media_type, mime, width, height, duration,
                    dimensions_source if media_type == "image" else "provider_variant"))
            except StockMediaError:
                raise
            except (KeyError, TypeError, ValueError):
                raise _fail("Pixabay result is malformed") from None
        return results


_ADAPTERS = {"pexels": PexelsAdapter(), "pixabay": PixabayAdapter()}


def _adapter(provider: object) -> PexelsAdapter | PixabayAdapter:
    if type(provider) is not str or provider not in _ADAPTERS:
        raise _fail("stock provider is invalid")
    return _ADAPTERS[provider]


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("provider response contains duplicate keys")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise _fail("provider response contains a non-finite number")


def _response_contains_non_record_data(
    value: object, connection_value: str
) -> bool:
    if type(value) is dict:
        return any(
            _non_record_field_name(key)
            or _response_contains_non_record_data(item, connection_value)
            for key, item in value.items()
        )
    if type(value) is list:
        return any(
            _response_contains_non_record_data(item, connection_value)
            for item in value
        )
    return type(value) is str and connection_value in value


def _non_record_field_name(value: object) -> bool:
    if type(value) is not str:
        return True
    normalized = value.strip().lower().replace("-", "_")
    return normalized in _NON_RECORD_FIELD_MARKERS or normalized.startswith(
        ("authorization_", "cookie_", "credential_", "secret_")
    ) or normalized.endswith(("_api_key", "_access_key", "_token", "_signature"))


def _request_with_redirects(
    transport: object,
    url: str,
    *,
    headers: dict[str, str],
    allowed_hosts: frozenset[str],
    query_keys: frozenset[str],
    allow_query: bool,
    permitted_provider_query_keys: frozenset[str] = frozenset(),
    constrain_query_values: bool = True,
    timeout: float,
    max_redirects: int,
) -> TransportResponse:
    current = _normalize_provider_url(
        url,
        hosts=allowed_hosts,
        query_keys=query_keys,
        allow_query=allow_query,
        permitted_provider_query_keys=permitted_provider_query_keys,
        constrain_query_values=constrain_query_values,
    )
    for redirect_count in range(max_redirects + 1):
        try:
            requester = getattr(transport, "request")
        except BaseException as failure:
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise
            raise _fail("stock transport failed") from None
        try:
            raw_response = requester(current, headers=headers, timeout=timeout)
        except BaseException as failure:
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise
            raise _fail("stock transport failed") from None
        try:
            response = _response(raw_response)
        except BaseException as failure:
            if type(raw_response) is TransportResponse:
                _close_body(raw_response.body)
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise
            raise _fail("stock transport returned an invalid response") from None
        if response.status not in {301, 302, 303, 307, 308}:
            return response
        response_headers = _headers(response.headers)
        location = response_headers.get("location")
        _close_body(response.body)
        if redirect_count >= max_redirects or not location or location.startswith("//"):
            raise _fail("stock redirect failed")
        joined = urljoin(current, location)
        current = _normalize_provider_url(
            joined,
            hosts=allowed_hosts,
            query_keys=query_keys,
            allow_query=allow_query,
            permitted_provider_query_keys=permitted_provider_query_keys,
            constrain_query_values=constrain_query_values,
        )
    raise _fail("stock redirect failed")


def _connection_value(
    adapter: PexelsAdapter | PixabayAdapter, explicit: object
) -> str:
    value = (
        explicit
        if explicit is not None
        else os.environ.get(adapter.connection_environment)
    )
    return _utf8_text(
        value, label="stock provider connection value", max_bytes=4096
    )


def _validate_candidate(
    candidate: object,
    adapter: PexelsAdapter | PixabayAdapter,
    media_type: str,
) -> dict[str, object]:
    if type(candidate) is not dict or set(candidate) != _CANDIDATE_KEYS:
        raise _fail("frozen stock candidate is invalid")
    checked = _candidate(
        adapter, candidate["provider_asset_id"], candidate["author"], candidate["asset_page"],
        candidate["download_url"], media_type, candidate["mime_type"], candidate["width"],
        candidate["height"], candidate["duration"], candidate["dimensions_source"])
    if checked != candidate:
        raise _fail("frozen stock candidate is not canonical")
    return checked


def _validate_snapshot(snapshot: object) -> dict[str, object]:
    if type(snapshot) is not dict or set(snapshot) != _SNAPSHOT_KEYS:
        raise _fail("frozen stock snapshot is invalid")
    adapter = _adapter(snapshot["provider"])
    if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1:
        raise _fail("frozen stock snapshot version is invalid")
    query = _text(snapshot["query"], label="stock query")
    media_type = snapshot["media_type"]
    if type(media_type) is not str or media_type not in _MEDIA_TYPES:
        raise _fail("stock media_type is invalid")
    expected_query_sha = _query_sha256(
        adapter.name, query, media_type, per_page=adapter.per_page
    )
    if _sha256(snapshot["query_sha256"], label="query_sha256") != expected_query_sha:
        raise _fail("frozen stock query hash is invalid")
    _rfc3339(snapshot["searched_at"], label="searched_at")
    response_sha = _sha256(snapshot["response_sha256"], label="response_sha256")
    if type(snapshot["candidates"]) is not list:
        raise _fail("frozen stock candidates are invalid")
    candidates = [
        _validate_candidate(candidate, adapter, media_type)
        for candidate in snapshot["candidates"]
    ]
    ids = [candidate["provider_asset_id"] for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise _fail("frozen stock candidates contain duplicates")
    if (
        type(snapshot["result_order"]) is not list
        or type(snapshot["candidate_ids"]) is not list
        or any(type(item) is not str for item in snapshot["result_order"])
        or any(type(item) is not str for item in snapshot["candidate_ids"])
        or snapshot["result_order"] != ids
        or snapshot["candidate_ids"] != sorted(ids)
    ):
        raise _fail("frozen stock candidate order is invalid")
    generation_body = {
        "provider": adapter.name,
        "query_sha256": expected_query_sha,
        "response_sha256": response_sha,
        "candidate_ids": sorted(ids),
        "result_order": ids,
    }
    if _sha256(snapshot["search_generation"], label="search_generation") != _digest(
        generation_body
    ):
        raise _fail("frozen stock generation is invalid")
    body = {key: snapshot[key] for key in snapshot if key != "snapshot_sha256"}
    if _sha256(snapshot["snapshot_sha256"], label="snapshot_sha256") != _digest(body):
        raise _fail("frozen stock snapshot hash is invalid")
    try:
        return copy.deepcopy(snapshot)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail("frozen stock snapshot cannot be copied") from None


def _checked_snapshot(snapshot: object) -> dict[str, object]:
    try:
        return _validate_snapshot(snapshot)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(failure, StockMediaError):
            raise
        raise _fail("frozen stock snapshot is invalid") from None


def freeze_search_snapshot(
    provider: str,
    query: str,
    *,
    media_type: str,
    api_key: str | None = None,
    transport: object | None = None,
    clock: Callable[[], object] | None = None,
    frozen_snapshot: object | None = None,
) -> dict[str, object]:
    """Freeze provider order and candidate metadata, or replay an existing freeze."""
    if transport is not None:
        try:
            valid_transport = callable(getattr(transport, "request", None))
        except BaseException as failure:
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise
            raise _fail("stock transport is invalid") from None
        if not valid_transport:
            raise _fail("stock transport is invalid")
    if clock is not None and not callable(clock):
        raise _fail("stock clock is invalid")
    adapter = _adapter(provider)
    checked_query = _utf8_text(query, label="stock query", max_bytes=1024)
    if type(media_type) is not str or media_type not in _MEDIA_TYPES:
        raise _fail("stock media_type is invalid")
    if frozen_snapshot is not None:
        frozen = _checked_snapshot(frozen_snapshot)
        if (
            frozen["provider"] != provider
            or frozen["query"] != checked_query
            or frozen["media_type"] != media_type
        ):
            raise _fail("frozen stock snapshot does not match the request")
        return frozen

    searched_at = _rfc3339(_timestamp(clock), label="searched_at")
    connection_value = _connection_value(adapter, api_key)
    try:
        url, request_headers = adapter.search_request(
            checked_query, media_type, connection_value
        )
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail("stock search request is invalid") from None
    # The API request is constructed locally; only its host is persisted indirectly.
    response = _request_with_redirects(
        transport or _UrllibTransport(),
        url,
        headers=request_headers,
        allowed_hosts=adapter.api_hosts,
        query_keys=frozenset({"query", "q", "per_page", "safesearch", "key"}),
        allow_query=True,
        permitted_provider_query_keys=(
            frozenset({"key"}) if provider == "pixabay" else frozenset()
        ),
        constrain_query_values=False,
        timeout=_DEFAULT_TIMEOUT,
        max_redirects=_MAX_REDIRECTS,
    )
    if response.status != 200:
        _close_body(response.body)
        raise _fail(f"{provider} search failed")
    response_headers = _headers(response.headers)
    if response_headers.get("content-type", "").split(";", 1)[0].strip().lower() not in {
        "application/json",
        "application/problem+json",
    }:
        _close_body(response.body)
        raise _fail(f"{provider} search failed")
    raw = _read_limited(response, _SEARCH_LIMIT)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except StockMediaError:
        raise
    except (UnicodeError, json.JSONDecodeError):
        raise _fail(f"{provider} search response is malformed") from None
    if _response_contains_non_record_data(payload, connection_value):
        raise _fail("provider response contains request-only connection data")
    try:
        candidates = adapter.parse(payload, media_type)
    except StockMediaError:
        raise
    except Exception:
        raise _fail(f"{provider} search response is malformed") from None
    ids = [candidate["provider_asset_id"] for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise _fail(f"{provider} search returned duplicate candidates")
    query_sha = _query_sha256(
        provider, checked_query, media_type, per_page=adapter.per_page
    )
    response_sha = hashlib.sha256(raw).hexdigest()
    generation_body = {
        "provider": provider,
        "query_sha256": query_sha,
        "response_sha256": response_sha,
        "candidate_ids": sorted(ids),
        "result_order": ids,
    }
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "provider": provider,
        "query": checked_query,
        "media_type": media_type,
        "query_sha256": query_sha,
        "searched_at": searched_at,
        "candidate_ids": sorted(ids),
        "result_order": ids,
        "candidates": candidates,
        "response_sha256": response_sha,
        "search_generation": _digest(generation_body),
    }
    if connection_value.encode("utf-8") in _canonical_bytes(snapshot):
        raise _fail("provider response contains request-only connection data")
    snapshot["snapshot_sha256"] = _digest(snapshot)
    return _checked_snapshot(snapshot)


def _pin_job(job_dir: os.PathLike[str] | str) -> Any:
    try:
        return _broll_media._PinnedJob.open(SimpleNamespace(job_dir=os.fspath(job_dir)))
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail("Job directory is unavailable") from None


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _job_parts(value: object, *, label: str) -> tuple[str, ...]:
    text = _text(value, label=label)
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or "\\" in text
        or len(path.parts) < 2
    ):
        raise _fail(f"{label} is invalid")
    return path.parts


def _open_parent(
    root_descriptor: int,
    parent_parts: tuple[str, ...],
    *,
    create: bool,
) -> tuple[int, list[int]]:
    descriptors: list[int] = []
    current = root_descriptor
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for name in parent_parts:
            try:
                visible = os.stat(name, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(name, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
                visible = os.stat(name, dir_fd=current, follow_symlinks=False)
            if not stat.S_ISDIR(visible.st_mode):
                raise _fail("Job-relative path does not match the path contract")
            descriptor = os.open(name, flags, dir_fd=current)
            descriptors.append(descriptor)
            opened = os.fstat(descriptor)
            if _broll_media._directory_identity(opened) != _broll_media._directory_identity(visible):
                raise _fail("Job-relative path changed")
            current = descriptor
        return current, descriptors
    except StockMediaError:
        _broll_media._close_all(descriptors)
        raise
    except OSError:
        _broll_media._close_all(descriptors)
        raise _fail("Job-relative path is unavailable") from None


def _verify_parent_chain(root: Any, parts: tuple[str, ...], descriptors: list[int]) -> None:
    root.verify_visible()
    current = root.descriptor
    try:
        for name, descriptor in zip(parts, descriptors):
            visible = os.stat(name, dir_fd=current, follow_symlinks=False)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(visible.st_mode)
                or _broll_media._directory_identity(visible)
                != _broll_media._directory_identity(opened)
            ):
                raise _fail("Job-relative directory changed")
            current = descriptor
    except StockMediaError:
        raise
    except Exception:
        raise _fail("Job-relative directory changed") from None


def _planned_paths(idempotency_key: str, extension: str) -> tuple[str, str, str]:
    key = _sha256(idempotency_key, label="idempotency_key")
    return (
        f"stock/{key[:2]}/{key}{extension}",
        f"stock/{key[:2]}/{key}.license.json",
        f"stock/{key[:2]}/{key}.download.json",
    )


def _find_candidate(snapshot: dict[str, object], candidate_id: object) -> dict[str, object]:
    checked_id = _text(candidate_id, label="candidate_id")
    for candidate in snapshot["candidates"]:
        if candidate["provider_asset_id"] == checked_id:
            return candidate
    raise _fail("candidate_id is not in the frozen snapshot")


def _content_type(response: TransportResponse) -> str:
    value = _headers(response.headers).get("content-type", "")
    return value.split(";", 1)[0].strip().lower()


def _sniff_format(header: bytes) -> str | None:
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "iso-bmff"
    if header.startswith(b"\x1aE\xdf\xa3"):
        return "webm"
    return None


def _sha256_descriptor(descriptor: int, capture_limit: int = 64) -> tuple[str, int, bytes]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = 0
    captured = bytearray()
    while True:
        chunk = os.read(descriptor, _HASH_CHUNK)
        if not chunk:
            break
        if len(captured) < capture_limit:
            captured.extend(chunk[: capture_limit - len(captured)])
        size += len(chunk)
        digest.update(chunk)
    return digest.hexdigest(), size, bytes(captured)


def validate_downloaded_media(
    job_dir: os.PathLike[str] | str,
    job_path: str,
    *,
    declared_mime: str,
    media_type: str,
    expected_sha256: str,
    probe: Callable[[str, str], object],
    expected_width: int | None = None,
    expected_height: int | None = None,
    dimensions_source: str | None = None,
) -> dict[str, object]:
    """Validate one pinned Job-relative media file and its external probe result."""
    if not callable(probe):
        raise _fail("media probe is required")
    parts = _job_parts(job_path, label="media job_path")
    mime = _text(declared_mime, label="declared MIME").lower()
    extension = PurePosixPath(job_path).suffix.lower()
    expected_format = _format_from_mime(mime, extension, media_type)
    expected_hash = _sha256(expected_sha256, label="expected_sha256")
    if dimensions_source is not None:
        if dimensions_source not in {
            "provider_variant", "provider_declared", "url_variant"
        }:
            raise _fail("dimensions_source is invalid")
        checked_width = _positive_integer(expected_width, label="stock width")
        checked_height = _positive_integer(expected_height, label="stock height")
    elif expected_width is not None or expected_height is not None:
        raise _fail("media dimensions are invalid")
    else:
        checked_width = checked_height = None
    pinned = _pin_job(job_dir)
    parents: list[int] = []
    descriptor: int | None = None
    try:
        parent, parents = _open_parent(pinned.descriptor, parts[:-1], create=False)
        visible = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(parts[-1], flags, dir_fd=parent)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(visible.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or visible.st_nlink != 1
            or before.st_nlink != 1
            or _file_identity(visible) != _file_identity(before)
        ):
            raise _fail("downloaded media does not match the media contract")
        digest, byte_count, header = _sha256_descriptor(descriptor)
        sniffed = _sniff_format(header)
        if digest != expected_hash or (
            sniffed != expected_format
            and not (sniffed == "iso-bmff" and expected_format in {"mp4", "mov"})
        ):
            raise _fail("downloaded media failed validation")
        absolute = str(pinned.path.joinpath(*parts))
        _verify_parent_chain(pinned, parts[:-1], parents)
        try:
            probe_result = probe(absolute, media_type)
        except BaseException as failure:
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise
            raise _fail("downloaded media probe failed") from None
        _verify_parent_chain(pinned, parts[:-1], parents)
        probe_keys = {"media_type", "format", "width", "height"}
        if type(probe_result) is not dict or set(probe_result) != probe_keys:
            raise _fail("downloaded media probe returned an invalid result")
        if (
            probe_result["media_type"] != media_type
            or probe_result["format"] != expected_format
        ):
            raise _fail("downloaded media probe disagrees with the contract")
        actual_width = _positive_integer(
            probe_result["width"], label="probed width"
        )
        actual_height = _positive_integer(
            probe_result["height"], label="probed height"
        )
        if dimensions_source in {None, "provider_declared"}:
            actual_source = "probe"
        else:
            if (
                actual_width != checked_width
                or actual_height != checked_height
            ):
                raise _fail("downloaded media probe disagrees with dimensions")
            actual_source = dimensions_source
        after = os.fstat(descriptor)
        current = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        digest_after, size_after, header_after = _sha256_descriptor(descriptor)
        if (
            _file_identity(before) != _file_identity(after)
            or _file_identity(before) != _file_identity(current)
            or digest_after != digest
            or size_after != byte_count
            or header_after != header
        ):
            raise _fail("downloaded media changed during validation")
        return {
            "job_path": job_path,
            "media_type": media_type,
            "format": expected_format,
            "mime_type": mime,
            "byte_count": byte_count,
            "sha256": digest,
            "actual_width": actual_width,
            "actual_height": actual_height,
            "dimensions_source": actual_source,
        }
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(failure, StockMediaError):
            raise
        raise _fail("downloaded media is unavailable") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _broll_media._close_all(parents)
        pinned.close()


def _remove_recorded_stage(
    root: Any, job_path: str, identity: tuple[int, ...]
) -> bool:
    parts = _job_parts(job_path, label="staging job_path")
    parents: list[int] = []
    try:
        parent, parents = _open_parent(root.descriptor, parts[:-1], create=False)
        _verify_parent_chain(root, parts[:-1], parents)
        _remove_owned_name(parent, parts[-1], identity=identity)
        _verify_parent_chain(root, parts[:-1], parents)
        return True
    except Exception:
        return False
    finally:
        _broll_media._close_all(parents)


def _journal_value(
    snapshot: dict[str, object], candidate: dict[str, object], key: str,
    nonce: str, staging_path: str, planned_path: str, license_path: str,
    *, state: str, expected_identity: tuple[int, ...] | None = None,
    downloaded_at: str | None = None, byte_count: int | None = None,
    sha256: str | None = None, license_record: dict[str, object] | None = None,
    actual_width: int | None = None, actual_height: int | None = None,
    dimensions_source: str | None = None,
    license_sha256: str | None = None,
    license_identity: tuple[int, ...] | None = None,
) -> dict[str, object]:
    parent = PurePosixPath(staging_path).parent
    license_staging_path = str(
        parent / f".{key}.{nonce}.license.staging.json"
    )
    return {
        "schema_version": 1, "state": state, "idempotency_key": key,
        "nonce": nonce, "provider": snapshot["provider"],
        "provider_asset_id": candidate["provider_asset_id"],
        "search_generation": snapshot["search_generation"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "query_sha256": snapshot["query_sha256"],
        "staging_job_path": staging_path, "planned_job_path": planned_path,
        "planned_license_snapshot": license_path,
        "license_staging_job_path": license_staging_path,
        "media_type": candidate["media_type"], "format": candidate["format"],
        "mime_type": candidate["mime_type"],
        "expected_identity": list(expected_identity) if expected_identity else None,
        "downloaded_at": downloaded_at, "byte_count": byte_count, "sha256": sha256,
        "actual_width": actual_width, "actual_height": actual_height,
        "dimensions_source": dimensions_source,
        "license_record": license_record, "license_sha256": license_sha256,
        "license_identity": (
            list(license_identity) if license_identity is not None else None
        ),
    }


def _validate_journal(
    value: object, snapshot: dict[str, object], candidate: dict[str, object], key: str,
    planned_path: str, license_path: str,
) -> dict[str, object]:
    if type(value) is not dict or set(value) != _JOURNAL_KEYS:
        raise _fail("download journal is invalid")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise _fail("download journal is invalid")
    state = value["state"]
    nonce = value["nonce"]
    if state not in {
        "planned", "partial", "complete", "publishing", "published"
    } or type(nonce) is not str or re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
        raise _fail("download journal is invalid")
    expected = _journal_value(
        snapshot, candidate, key, nonce, value["staging_job_path"], planned_path,
        license_path, state=state,
        expected_identity=(tuple(value["expected_identity"]) if type(value["expected_identity"]) is list else None),
        downloaded_at=value["downloaded_at"], byte_count=value["byte_count"],
        sha256=value["sha256"], license_record=value["license_record"],
        actual_width=value["actual_width"],
        actual_height=value["actual_height"],
        dimensions_source=value["dimensions_source"],
        license_sha256=value["license_sha256"],
        license_identity=(
            tuple(value["license_identity"])
            if type(value["license_identity"]) is list else None
        ))
    if expected != value:
        raise _fail("download journal conflict")
    staging_parts = _job_parts(value["staging_job_path"], label="staging_job_path")
    planned_parts = _job_parts(planned_path, label="planned_job_path")
    expected_name = f".{key}.{nonce}.staging{candidate['extension']}"
    if staging_parts[:-1] != planned_parts[:-1] or staging_parts[-1] != expected_name:
        raise _fail("download journal staging capability is invalid")
    license_staging_parts = _job_parts(
        value["license_staging_job_path"], label="license_staging_job_path"
    )
    expected_license_staging = f".{key}.{nonce}.license.staging.json"
    if (
        license_staging_parts[:-1] != planned_parts[:-1]
        or license_staging_parts[-1] != expected_license_staging
    ):
        raise _fail("license journal staging capability is invalid")
    if state == "planned":
        if any(value[field] is not None for field in (
            "expected_identity", "downloaded_at", "byte_count", "sha256",
            "actual_width", "actual_height", "dimensions_source",
            "license_record", "license_sha256", "license_identity",
        )):
            raise _fail("planned download journal is invalid")
    else:
        identity = value["expected_identity"]
        expected_length = 4 if state == "partial" else 7
        if (
            type(identity) is not list or len(identity) != expected_length
            or any(type(item) is not int for item in identity)
            or identity[3] != 1
        ):
            raise _fail("download journal identity is invalid")
        if state == "partial":
            if any(value[field] is not None for field in (
                "downloaded_at", "byte_count", "sha256", "license_record",
                "actual_width", "actual_height", "dimensions_source",
                "license_sha256", "license_identity",
            )):
                raise _fail("partial download journal is invalid")
        else:
            _rfc3339(value["downloaded_at"], label="downloaded_at")
            _positive_integer(value["byte_count"], label="byte_count")
            _sha256(value["sha256"], label="sha256")
            _positive_integer(value["actual_width"], label="actual_width")
            _positive_integer(value["actual_height"], label="actual_height")
            expected_source = (
                "probe"
                if candidate["dimensions_source"] == "provider_declared"
                else candidate["dimensions_source"]
            )
            if value["dimensions_source"] != expected_source:
                raise _fail("download journal dimensions are invalid")
            if expected_source != "probe" and (
                value["actual_width"] != candidate["width"]
                or value["actual_height"] != candidate["height"]
            ):
                raise _fail("download journal dimensions are invalid")
            if state == "complete":
                if any(value[field] is not None for field in (
                    "license_record", "license_sha256", "license_identity"
                )):
                    raise _fail("complete download journal is invalid")
            else:
                license_record = _validate_license_record(
                    value["license_record"], snapshot=snapshot,
                    candidate=candidate, idempotency_key=key,
                    planned_path=planned_path, license_path=license_path,
                )
                if (
                    license_record["downloaded_at"] != value["downloaded_at"]
                    or license_record["byte_count"] != value["byte_count"]
                    or license_record["sha256"] != value["sha256"]
                    or _sha256(value["license_sha256"], label="license_sha256")
                    != hashlib.sha256(
                        _canonical_bytes(license_record) + b"\n"
                    ).hexdigest()
                ):
                    raise _fail("publication journal license is invalid")
                license_identity = value["license_identity"]
                if license_identity is not None and (
                    type(license_identity) is not list
                    or len(license_identity) != 3
                    or any(type(item) is not int for item in license_identity)
                ):
                    raise _fail("publication journal license identity is invalid")
                if state == "published" and license_identity is None:
                    raise _fail("published journal has no license identity")
    return copy.deepcopy(value)


def _file_evidence(
    parent: int,
    name: str,
    *,
    allowed_links: frozenset[int],
    capture_limit: int = 0,
) -> tuple[tuple[int, ...], str, int, bytes]:
    descriptor: int | None = None
    try:
        visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(visible.st_mode) or visible.st_nlink not in allowed_links:
            raise _fail("stock file does not match the file contract")
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink not in allowed_links
            or _file_identity(before) != _file_identity(visible)
        ):
            raise _fail("stock file does not match the file contract")
        digest, size, captured = _sha256_descriptor(descriptor, capture_limit)
        after = os.fstat(descriptor)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if _file_identity(before) != _file_identity(after) or _file_identity(before) != _file_identity(current):
            raise _fail("stock file changed")
        return _file_identity(before), digest, size, captured
    except StockMediaError:
        raise
    except Exception:
        raise _fail("stock file is unavailable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _stage_evidence(parent: int, name: str) -> tuple[tuple[int, ...], str, int]:
    identity, digest, size, _ = _file_evidence(
        parent, name, allowed_links=frozenset({1})
    )
    return identity, digest, size


def _remove_owned_name(
    parent: int,
    name: str,
    *,
    identity: tuple[int, ...],
    digest: str | None = None,
    size: int | None = None,
    raw: bytes | None = None,
) -> bool:
    """Move a recorded name into a cleanup directory before deleting it."""
    token = hashlib.sha256(
        f"{name}\0{identity[0]}\0{identity[1]}".encode("utf-8")
    ).hexdigest()[:24]
    cleanup_stage = f".stock-owned-{token}.cleanup-stage"
    try:
        os.mkdir(cleanup_stage, 0o700, dir_fd=parent)
    except FileExistsError:
        pass
    visible_directory = os.stat(
        cleanup_stage, dir_fd=parent, follow_symlinks=False
    )
    if not stat.S_ISDIR(visible_directory.st_mode):
        raise _fail("recorded cleanup stage conflicts with current files")
    descriptor = os.open(
        cleanup_stage,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        dir_fd=parent,
    )
    try:
        if (
            _broll_media._directory_identity(os.fstat(descriptor))
            != _broll_media._directory_identity(visible_directory)
        ):
            raise _fail("recorded cleanup stage changed")
        payload_exists = _exists_nofollow(descriptor, "payload")
        source_exists = _exists_nofollow(parent, name)
        if not payload_exists and source_exists:
            os.rename(
                name,
                "payload",
                src_dir_fd=parent,
                dst_dir_fd=descriptor,
            )
            payload_exists = True
            source_exists = False
        if not payload_exists:
            if source_exists:
                raise _fail("owned removal conflict")
            os.close(descriptor)
            descriptor = -1
            os.rmdir(cleanup_stage, dir_fd=parent)
            os.fsync(parent)
            return True
        evidence = _file_evidence(
            descriptor,
            "payload",
            allowed_links=frozenset({1, 2}),
            capture_limit=(len(raw) if raw is not None else 0),
        )
        matches = (
            evidence[0][:3] == identity[:3]
            and (size is None or evidence[2] == size)
            and (digest is None or evidence[1] == digest)
            and (raw is None or evidence[3] == raw)
        )
        if not matches:
            if not source_exists:
                try:
                    os.link(
                        "payload",
                        name,
                        src_dir_fd=descriptor,
                        dst_dir_fd=parent,
                        follow_symlinks=False,
                    )
                    os.fsync(parent)
                except FileExistsError:
                    pass
            raise _fail("owned removal conflict")
        os.unlink("payload", dir_fd=descriptor)
        os.fsync(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    os.rmdir(cleanup_stage, dir_fd=parent)
    os.fsync(parent)
    return True


def _download_record(journal: dict[str, object], journal_path: str,
                     journal_sha: str) -> DownloadRecord:
    return DownloadRecord(
        schema_version=1, status=journal["state"], provider=journal["provider"],
        provider_asset_id=journal["provider_asset_id"],
        search_generation=journal["search_generation"], snapshot_sha256=journal["snapshot_sha256"],
        query_sha256=journal["query_sha256"], idempotency_key=journal["idempotency_key"],
        journal_job_path=journal_path, journal_sha256=journal_sha,
        staging_job_path=journal["staging_job_path"],
        license_staging_job_path=journal["license_staging_job_path"],
        planned_job_path=journal["planned_job_path"],
        planned_license_snapshot=journal["planned_license_snapshot"], media_type=journal["media_type"],
        format=journal["format"], mime_type=journal["mime_type"], downloaded_at=journal["downloaded_at"],
        byte_count=journal["byte_count"], sha256=journal["sha256"],
        expected_identity=tuple(journal["expected_identity"]),
        actual_width=journal["actual_width"],
        actual_height=journal["actual_height"],
        dimensions_source=journal["dimensions_source"],
        license_sha256=journal["license_sha256"],
    )


def _open_lock(parent: int, key: str) -> int:
    name = f".{_sha256(key, label='idempotency_key')}.publish.lock"
    flags = (
        os.O_RDWR
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
        except FileExistsError:
            visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(visible.st_mode) or visible.st_nlink != 1:
                raise _fail("stock lock does not match the lock contract")
            descriptor = os.open(name, flags, dir_fd=parent)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (
                "visible" in locals()
                and _file_identity(metadata) != _file_identity(visible)
            )
        ):
            raise _fail("stock lock does not match the lock contract")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        result = descriptor
        descriptor = None
        return result
    except BaseException as failure:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if isinstance(failure, (KeyboardInterrupt, SystemExit, StockMediaError)):
            raise
        raise _fail("stock lock is unavailable") from None


def download_to_staging(
    frozen_snapshot: object,
    candidate_id: str,
    *,
    job_dir: os.PathLike[str] | str,
    idempotency_key: str,
    transport: object | None = None,
    probe: Callable[[str, str], object],
    max_bytes: int = _DEFAULT_MEDIA_LIMIT,
    clock: Callable[[], object] | None = None,
    max_redirects: int = _MAX_REDIRECTS,
) -> DownloadRecord:
    """Stream a frozen candidate into a same-directory staging file."""
    if not callable(probe):
        raise _fail("media probe is required")
    if transport is not None:
        try:
            valid_transport = callable(getattr(transport, "request", None))
        except BaseException as failure:
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise
            raise _fail("stock transport is invalid") from None
        if not valid_transport:
            raise _fail("stock transport is invalid")
    if clock is not None and not callable(clock):
        raise _fail("stock clock is invalid")
    snapshot = _checked_snapshot(frozen_snapshot)
    adapter = _adapter(snapshot["provider"])
    candidate = _find_candidate(snapshot, candidate_id)
    limit = _positive_integer(max_bytes, label="max_bytes")
    redirects = _positive_integer(max_redirects, label="max_redirects", allow_zero=True)
    planned_path, license_path, journal_path = _planned_paths(idempotency_key, candidate["extension"])
    planned_parts = _job_parts(planned_path, label="planned job_path")
    journal_parts = _job_parts(journal_path, label="journal_job_path")
    pinned = _pin_job(job_dir)
    parent_descriptors: list[int] = []
    lock_descriptor: int | None = None
    descriptor: int | None = None
    created_identity: tuple[int, ...] | None = None
    journal_owned_identity: tuple[int, ...] | None = None
    staging_path = ""
    try:
        parent, parent_descriptors = _open_parent(
            pinned.descriptor, planned_parts[:-1], create=True
        )
        _verify_parent_chain(pinned, planned_parts[:-1], parent_descriptors)
        lock_descriptor = _open_lock(parent, idempotency_key)
        _recover_json_install(parent, journal_parts[-1])
        if _exists_nofollow(parent, journal_parts[-1]):
            raw_journal, journal_sha, journal_identity = _read_exact_json_record(
                pinned, journal_path
            )
            journal = _validate_journal(
                raw_journal, snapshot, candidate, idempotency_key,
                planned_path, license_path)
            staging_path = journal["staging_job_path"]
            staging_name = _job_parts(staging_path, label="staging_job_path")[-1]
            stage_exists = _exists_nofollow(parent, staging_name)
            if journal["state"] == "published":
                existing = _existing_publish(
                    pinned, planned_path=planned_path,
                    license_path=license_path,
                    idempotency_key=idempotency_key,
                    snapshot=snapshot, candidate=candidate,
                )
                if existing is None:
                    raise _fail("published stock receipt conflicts with Job files")
                _validate_published_files(
                    parent, journal, planned_parts[-1],
                    _job_parts(license_path, label="license_snapshot")[-1],
                )
                _verify_parent_chain(
                    pinned, planned_parts[:-1], parent_descriptors
                )
                return _download_record(journal, journal_path, journal_sha)
            if journal["state"] == "publishing":
                _verify_parent_chain(
                    pinned, planned_parts[:-1], parent_descriptors
                )
                return _download_record(journal, journal_path, journal_sha)
            if journal["state"] == "complete":
                if not stage_exists:
                    raise _fail("complete download journal has no staging asset")
                identity, digest, size = _stage_evidence(parent, staging_name)
                if (
                    list(identity) != journal["expected_identity"]
                    or digest != journal["sha256"] or size != journal["byte_count"]
                ):
                    raise _fail("complete download journal does not match staging")
                _verify_parent_chain(pinned, planned_parts[:-1], parent_descriptors)
                return _download_record(journal, journal_path, journal_sha)
            if journal["state"] == "partial":
                recorded_stage_identity = tuple(journal["expected_identity"])
                if stage_exists:
                    identity, _, _ = _stage_evidence(parent, staging_name)
                    if identity[:4] != recorded_stage_identity:
                        raise _fail(
                            "partial download journal does not match staging"
                        )
                    retirement_identity = identity
                else:
                    retirement_identity = recorded_stage_identity
                try:
                    _remove_owned_name(
                        parent, staging_name, identity=retirement_identity
                    )
                except (OSError, StockMediaError):
                    raise _fail(
                        "partial staging asset could not be retired"
                    ) from None
                if _exists_nofollow(parent, staging_name):
                    raise _fail("partial staging asset could not be retired")
                planned_recovery = _journal_value(
                    snapshot, candidate, idempotency_key, journal["nonce"],
                    journal["staging_job_path"], planned_path, license_path,
                    state="planned",
                )
                _, journal_identity = _install_json(
                    parent, journal_parts[-1], planned_recovery,
                    replace_identity=journal_identity,
                )
                journal = planned_recovery
                _verify_parent_chain(
                    pinned, planned_parts[:-1], parent_descriptors
                )
                journal_owned_identity = journal_identity
                stage_exists = False
            if journal["state"] == "planned" and stage_exists:
                try:
                    identity, digest, size = _stage_evidence(
                        parent, staging_name
                    )
                except StockMediaError:
                    raise _fail(
                        "planned download staging does not match its record"
                    ) from None
                if stat.S_IMODE(identity[2]) != 0o600 or size != 0:
                    raise _fail("planned download staging does not match its record")
                try:
                    _remove_owned_name(
                        parent, staging_name, identity=identity,
                        digest=digest, size=0,
                    )
                except (OSError, StockMediaError):
                    raise _fail(
                        "planned download staging could not be retired"
                    ) from None
                if _exists_nofollow(parent, staging_name):
                    raise _fail(
                        "planned download staging could not be retired"
                    )
                stage_exists = False
            if stage_exists:
                raise _fail("planned download journal has ambiguous staging")
            if journal["state"] == "planned":
                journal_owned_identity = journal_identity

        nonce = secrets.token_hex(16)
        staging_name = f".{idempotency_key}.{nonce}.staging{candidate['extension']}"
        staging_path = str(PurePosixPath(*planned_parts[:-1], staging_name))
        planned_journal = _journal_value(
            snapshot, candidate, idempotency_key, nonce, staging_path,
            planned_path, license_path, state="planned")
        _, journal_owned_identity = _install_json(
            parent, journal_parts[-1], planned_journal,
            replace_identity=journal_owned_identity,
        )
        _verify_parent_chain(pinned, planned_parts[:-1], parent_descriptors)
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        descriptor = os.open(staging_name, flags, 0o600, dir_fd=parent)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise _fail("staging file does not match its record")
        created_identity = _file_identity(opened)
        partial_journal = _journal_value(
            snapshot, candidate, idempotency_key, nonce, staging_path,
            planned_path, license_path, state="partial",
            expected_identity=created_identity[:4],
        )
        _, journal_owned_identity = _install_json(
            parent, journal_parts[-1], partial_journal,
            replace_identity=journal_owned_identity,
        )
        _verify_parent_chain(pinned, planned_parts[:-1], parent_descriptors)
        response = _request_with_redirects(
            transport or _UrllibTransport(),
            candidate["download_url"],
            headers={"Accept": candidate["mime_type"]},
            allowed_hosts=adapter.cdn_hosts,
            query_keys=adapter.cdn_query,
            allow_query=True,
            timeout=_DEFAULT_TIMEOUT,
            max_redirects=redirects,
        )
        if response.status != 200 or _content_type(response) != candidate["mime_type"]:
            _close_body(response.body)
            raise _fail("stock media download failed")
        response_headers = _headers(response.headers)
        content_length = response_headers.get("content-length")
        declared_length: int | None = None
        if content_length is not None:
            if not content_length.isascii() or not content_length.isdecimal():
                _close_body(response.body)
                raise _fail("stock media content length is invalid")
            declared_length = int(content_length)
            if declared_length > limit:
                _close_body(response.body)
                raise _fail("stock media exceeds the size limit")
        digest = hashlib.sha256()
        byte_count = 0
        try:
            for chunk in _iter_body(response.body):
                byte_count += len(chunk)
                if byte_count > limit:
                    raise _fail("stock media exceeds the size limit")
                view = memoryview(chunk)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise _fail("stock media staging write failed")
                    view = view[written:]
                digest.update(chunk)
        finally:
            _close_body(response.body)
        if byte_count == 0:
            raise _fail("stock media download is empty")
        if declared_length is not None and byte_count != declared_length:
            raise _fail("stock media content length disagrees with the stream")
        os.fsync(descriptor)
        _verify_parent_chain(pinned, planned_parts[:-1], parent_descriptors)
        after = os.fstat(descriptor)
        if after.st_nlink != 1 or after.st_size != byte_count:
            raise _fail("staging file changed during download")
        created_identity = _file_identity(after)
        os.close(descriptor)
        descriptor = None
        os.fsync(parent)
        validated = validate_downloaded_media(
            pinned.path,
            staging_path,
            declared_mime=candidate["mime_type"],
            media_type=candidate["media_type"],
            expected_sha256=digest.hexdigest(),
            probe=probe,
            expected_width=candidate["width"],
            expected_height=candidate["height"],
            dimensions_source=candidate["dimensions_source"],
        )
        _verify_parent_chain(pinned, planned_parts[:-1], parent_descriptors)
        identity, final_digest, final_size = _stage_evidence(parent, staging_name)
        if final_digest != validated["sha256"] or final_size != validated["byte_count"]:
            raise _fail("validated staging evidence changed")
        downloaded_at = _rfc3339(
            _timestamp(clock), label="downloaded_at"
        )
        complete_journal = _journal_value(
            snapshot, candidate, idempotency_key, nonce, staging_path,
            planned_path, license_path, state="complete",
            expected_identity=identity, downloaded_at=downloaded_at,
            byte_count=final_size, sha256=final_digest,
            actual_width=validated["actual_width"],
            actual_height=validated["actual_height"],
            dimensions_source=validated["dimensions_source"],
        )
        journal_sha, journal_owned_identity = _install_json(
            parent, journal_parts[-1], complete_journal,
            replace_identity=journal_owned_identity)
        _verify_parent_chain(pinned, planned_parts[:-1], parent_descriptors)
        return _download_record(complete_journal, journal_path, journal_sha)
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        cleanup_identity = created_identity
        cleanup_staging_path = staging_path
        cleanup_journal_identity = journal_owned_identity
        cleanup_journal_value: dict[str, object] | None = None
        if descriptor is not None:
            try:
                cleanup_identity = _file_identity(os.fstat(descriptor))
            except OSError:
                pass
        cleanup_allowed = False
        try:
            if "parent" in locals():
                _recover_json_install(parent, journal_parts[-1])
            if "parent" in locals() and _exists_nofollow(parent, journal_parts[-1]):
                raw_recovery, _, recovered_journal_identity = _read_exact_json_record(
                    pinned, journal_path
                )
                recovered_journal = _validate_journal(
                    raw_recovery, snapshot, candidate, idempotency_key,
                    planned_path, license_path,
                )
                if recovered_journal["state"] == "complete":
                    recovered_name = _job_parts(
                        recovered_journal["staging_job_path"],
                        label="staging_job_path",
                    )[-1]
                    recovered_identity, recovered_digest, recovered_size = (
                        _stage_evidence(parent, recovered_name)
                    )
                    evidence_matches = (
                        list(recovered_identity)
                        == recovered_journal["expected_identity"]
                        and recovered_digest == recovered_journal["sha256"]
                        and recovered_size == recovered_journal["byte_count"]
                    )
                    if not evidence_matches:
                        raise _fail("complete download recovery conflict")
                elif recovered_journal["state"] == "partial":
                    recovered_path = recovered_journal["staging_job_path"]
                    recovered_name = _job_parts(
                        recovered_path, label="staging_job_path"
                    )[-1]
                    recovered_identity, _, _ = _stage_evidence(
                        parent, recovered_name
                    )
                    if (
                        list(recovered_identity[:4])
                        == recovered_journal["expected_identity"]
                    ):
                        cleanup_identity = recovered_identity
                        cleanup_staging_path = recovered_path
                        cleanup_journal_identity = recovered_journal_identity
                        cleanup_journal_value = recovered_journal
                        cleanup_allowed = True
                elif recovered_journal["state"] == "planned":
                    cleanup_journal_identity = recovered_journal_identity
                    cleanup_journal_value = recovered_journal
                    cleanup_allowed = True
        except Exception:
            cleanup_allowed = False
        stage_retired = cleanup_identity is None
        if cleanup_identity is not None and cleanup_allowed:
            stage_retired = _remove_recorded_stage(
                pinned, cleanup_staging_path, cleanup_identity
            )
        if (
            cleanup_journal_identity is not None
            and cleanup_allowed
            and stage_retired
            and "parent" in locals()
            and cleanup_journal_value is not None
            and cleanup_journal_value["state"] == "partial"
        ):
            planned_recovery = _journal_value(
                snapshot, candidate, idempotency_key,
                cleanup_journal_value["nonce"],
                cleanup_journal_value["staging_job_path"],
                planned_path, license_path, state="planned",
            )
            try:
                _install_json(
                    parent, journal_parts[-1], planned_recovery,
                    replace_identity=cleanup_journal_identity,
                )
            except BaseException as cleanup_failure:
                if isinstance(cleanup_failure, (KeyboardInterrupt, SystemExit)):
                    raise
                raise _fail("download recovery journal update failed") from None
        if isinstance(failure, StockMediaError):
            raise
        raise _fail("stock media download failed") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if lock_descriptor is not None:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(lock_descriptor)
        _broll_media._close_all(parent_descriptors)
        pinned.close()


def _inspect_job_file(root: Any, job_path: str, *, capture_limit: int) -> tuple[str, int, bytes, tuple[int, ...]]:
    parts = _job_parts(job_path, label="published job_path")
    parents: list[int] = []
    try:
        parent, parents = _open_parent(root.descriptor, parts[:-1], create=False)
        _verify_parent_chain(root, parts[:-1], parents)
        identity, digest, size, captured = _file_evidence(
            parent, parts[-1], allowed_links=frozenset({1}),
            capture_limit=capture_limit,
        )
        _verify_parent_chain(root, parts[:-1], parents)
        return digest, size, captured, identity
    except StockMediaError:
        raise
    except OSError:
        raise _fail("published stock file is unavailable") from None
    finally:
        _broll_media._close_all(parents)


def _read_exact_json_record(
    root: Any, job_path: str
) -> tuple[dict[str, object], str, tuple[int, ...]]:
    try:
        digest, size, data, identity = _inspect_job_file(root, job_path, capture_limit=128 * 1024)
        if size > len(data):
            raise _fail("license snapshot is too large")
        parsed = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        if type(parsed) is not dict:
            raise _fail("license snapshot is invalid")
        if data != _canonical_bytes(parsed) + b"\n":
            raise _fail("persistent JSON is not canonical")
        return parsed, digest, identity
    except StockMediaError:
        raise
    except (UnicodeError, json.JSONDecodeError):
        raise _fail("license snapshot is invalid") from None


def _read_exact_json(root: Any, job_path: str) -> dict[str, object]:
    return _read_exact_json_record(root, job_path)[0]


def _hash_job_file(root: Any, job_path: str) -> tuple[str, int]:
    digest, size, _, _ = _inspect_job_file(root, job_path, capture_limit=0)
    return digest, size


def _binding_from_license(record: dict[str, object]) -> dict[str, object]:
    return {
        "provider": record["provider"],
        "provider_asset_id": record["provider_asset_id"],
        "author": record["author"],
        "asset_page": record["asset_page"],
        "job_path": record["job_path"],
        "license_snapshot": record["license_snapshot"],
        "downloaded_at": record["downloaded_at"],
        "sha256": record["sha256"],
    }


def _license_record(snapshot: dict[str, object], candidate: dict[str, object],
                    download: Mapping[str, object], key: str,
                    job_path: str, license_path: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "idempotency_key": key,
        "search_generation": snapshot["search_generation"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "query_sha256": snapshot["query_sha256"],
        "provider": snapshot["provider"],
        "provider_asset_id": candidate["provider_asset_id"],
        "author": candidate["author"],
        "asset_page": candidate["asset_page"],
        "license_name": candidate["license_name"],
        "license_version": candidate["license_version"],
        "downloaded_at": _text(download.get("downloaded_at"), label="downloaded_at"),
        "byte_count": _positive_integer(download.get("byte_count"), label="byte_count"),
        "sha256": _sha256(download.get("sha256"), label="sha256"),
        "job_path": job_path,
        "license_snapshot": license_path,
    }


def _contains_non_record_field(value: object) -> bool:
    if type(value) is dict:
        return any(
            _non_record_field_name(key)
            or _contains_non_record_field(item)
            for key, item in value.items()
        )
    if type(value) is list:
        return any(_contains_non_record_field(item) for item in value)
    return False


def _validate_license_record(
    value: object,
    *,
    snapshot: dict[str, object],
    candidate: dict[str, object],
    idempotency_key: str,
    planned_path: str,
    license_path: str,
) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != _LICENSE_KEYS
        or _contains_non_record_field(value)
    ):
        raise _fail("license snapshot is invalid")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise _fail("license snapshot is invalid")
    expected = {
        "idempotency_key": idempotency_key,
        "search_generation": snapshot["search_generation"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "query_sha256": snapshot["query_sha256"],
        "provider": snapshot["provider"],
        "provider_asset_id": candidate["provider_asset_id"],
        "author": candidate["author"],
        "asset_page": candidate["asset_page"],
        "license_name": candidate["license_name"],
        "license_version": candidate["license_version"],
        "job_path": planned_path,
        "license_snapshot": license_path,
    }
    if any(value[key] != item for key, item in expected.items()):
        raise _fail("license snapshot does not match the frozen candidate")
    _rfc3339(value["downloaded_at"], label="downloaded_at")
    _positive_integer(value["byte_count"], label="byte_count")
    _sha256(value["sha256"], label="sha256")
    return copy.deepcopy(value)


def _existing_publish(
    root: Any,
    *,
    planned_path: str,
    license_path: str,
    idempotency_key: str,
    snapshot: dict[str, object],
    candidate: dict[str, object],
) -> dict[str, object] | None:
    try:
        record = _validate_license_record(
            _read_exact_json(root, license_path),
            snapshot=snapshot,
            candidate=candidate,
            idempotency_key=idempotency_key,
            planned_path=planned_path,
            license_path=license_path,
        )
        digest, size = _hash_job_file(root, planned_path)
    except StockMediaError:
        return None
    if record["sha256"] != digest or record["byte_count"] != size:
        return None
    return _binding_from_license(record)


def _write_staged_json(
    parent: int,
    name: str,
    value: object,
    *,
    temporary_name: str | None = None,
) -> tuple[str, tuple[int, ...]]:
    temporary = temporary_name or f".{name}.{secrets.token_hex(12)}.staging"
    descriptor: int | None = None
    identity: tuple[int, ...] | None = None
    succeeded = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
        data = _canonical_bytes(value) + b"\n"
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise _fail("license snapshot write failed")
            view = view[written:]
        os.fsync(descriptor)
        identity = _file_identity(os.fstat(descriptor))
        if identity[3] != 1:
            raise _fail("license staging does not match its record")
        os.close(descriptor)
        descriptor = None
        succeeded = True
        return temporary, identity
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(failure, StockMediaError):
            raise
        raise _fail("license snapshot write failed") from None
    finally:
        if descriptor is not None:
            try:
                identity = _file_identity(os.fstat(descriptor))
            except OSError:
                pass
            os.close(descriptor)
        if not succeeded and identity is not None:
            _unlink_if_identity(parent, temporary, identity)


def _json_cas_directory(name: str) -> str:
    token = hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]
    return f".stock-json-{token}.cas"


def _open_json_cas(parent: int, name: str, *, create: bool) -> tuple[int, str] | None:
    directory = _json_cas_directory(name)
    if create:
        try:
            os.mkdir(directory, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    try:
        visible = os.stat(directory, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(visible.st_mode) or stat.S_IMODE(visible.st_mode) != 0o700:
        raise _fail("JSON transaction conflict")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            directory,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent,
        )
        opened = os.fstat(descriptor)
    except BaseException as failure:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        raise _fail("JSON transaction is unavailable") from None
    if (
        _broll_media._directory_identity(opened)
        != _broll_media._directory_identity(visible)
    ):
        os.close(descriptor)
        raise _fail("JSON transaction changed")
    return descriptor, directory


def _json_cas_evidence(parent: int, name: str) -> tuple[tuple[int, ...], str, int, bytes] | None:
    if not _exists_nofollow(parent, name):
        return None
    evidence = _file_evidence(
        parent, name, allowed_links=frozenset({1, 2}), capture_limit=128 * 1024
    )
    if evidence[2] > len(evidence[3]):
        raise _fail("JSON transaction record is too large")
    try:
        parsed = json.loads(
            evidence[3].decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError):
        raise _fail("JSON transaction record is invalid") from None
    if type(parsed) is not dict or evidence[3] != _canonical_bytes(parsed) + b"\n":
        raise _fail("JSON transaction record is not canonical")
    return evidence


def _recover_torn_cas_new(
    parent: int, name: str
) -> tuple[tuple[int, ...], str, int, bytes] | None:
    try:
        return _json_cas_evidence(parent, name)
    except StockMediaError:
        evidence = _file_evidence(
            parent, name, allowed_links=frozenset({1}),
            capture_limit=128 * 1024,
        )
        if (
            stat.S_IMODE(evidence[0][2]) != 0o600
            or evidence[2] > len(evidence[3])
        ):
            raise _fail("JSON transaction record is invalid") from None
        canonical = False
        try:
            parsed = json.loads(
                evidence[3].decode("utf-8"),
                object_pairs_hook=_no_duplicate_keys,
                parse_constant=_reject_nonfinite,
            )
            canonical = evidence[3] == _canonical_bytes(parsed) + b"\n"
        except (StockMediaError, UnicodeError, json.JSONDecodeError):
            pass
        if canonical:
            raise _fail("JSON transaction record is invalid")
        _remove_owned_name(
            parent, name, identity=evidence[0], digest=evidence[1],
            size=evidence[2], raw=evidence[3],
        )
        if _exists_nofollow(parent, name):
            raise _fail("JSON transaction record could not be retired")
        return None


def _same_file(
    left: tuple[tuple[int, ...], str, int, bytes] | None,
    right: tuple[tuple[int, ...], str, int, bytes] | None,
) -> bool:
    return left is not None and right is not None and left[0][:3] == right[0][:3]


def _retire_json_entry(
    descriptor: int,
    name: str,
    expected: tuple[tuple[int, ...], str, int, bytes],
) -> None:
    retired = f"retired-{name}"
    current = _json_cas_evidence(descriptor, name)
    isolated = _json_cas_evidence(descriptor, retired)
    if current is not None and isolated is not None:
        raise _fail("JSON transaction cleanup conflict")
    if isolated is None:
        if current is None:
            return
        os.rename(name, retired, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        isolated = _json_cas_evidence(descriptor, retired)
    if isolated is None or (
        isolated[0][:3] != expected[0][:3]
        or isolated[1:] != expected[1:]
    ):
        if isolated is not None and not _exists_nofollow(descriptor, name):
            try:
                os.link(
                    retired, name,
                    src_dir_fd=descriptor, dst_dir_fd=descriptor,
                    follow_symlinks=False,
                )
                os.fsync(descriptor)
            except FileExistsError:
                pass
        raise _fail("JSON transaction cleanup conflict")
    os.unlink(retired, dir_fd=descriptor)
    os.fsync(descriptor)


def _close_json_cas(parent: int, descriptor: int, directory: str) -> None:
    os.fsync(descriptor)
    visible = os.stat(directory, dir_fd=parent, follow_symlinks=False)
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(visible.st_mode)
        or _broll_media._directory_identity(visible)
        != _broll_media._directory_identity(opened)
    ):
        raise _fail("JSON transaction changed")
    os.rmdir(directory, dir_fd=parent)
    os.fsync(parent)


def _recover_json_install(parent: int, name: str) -> None:
    opened = _open_json_cas(parent, name, create=False)
    if opened is None:
        return
    descriptor, directory = opened
    closed = False
    try:
        entries = set(os.listdir(descriptor))
        if not entries <= {"old", "new", "retired-old", "retired-new"}:
            raise _fail("JSON transaction has unexpected entries")
        destination = _json_cas_evidence(parent, name)
        old_name = "old" if "old" in entries else "retired-old"
        new_name = "new" if "new" in entries else "retired-new"
        old = _json_cas_evidence(descriptor, old_name) if old_name in entries else None
        if new_name == "new" and new_name in entries:
            new = _recover_torn_cas_new(descriptor, new_name)
        else:
            new = (
                _json_cas_evidence(descriptor, new_name)
                if new_name in entries else None
            )
        if old is not None and destination is None:
            os.link(
                old_name, name,
                src_dir_fd=descriptor, dst_dir_fd=parent,
                follow_symlinks=False,
            )
            os.fsync(parent)
            destination = _json_cas_evidence(parent, name)
        committed = _same_file(destination, new)
        rolled_back = _same_file(destination, old)
        if old is not None and not committed and not rolled_back:
            raise _fail("JSON transaction destination conflict")
        if old is None and destination is not None and new is not None and not committed:
            # Another writer completed the initial install first. Keep the
            # destination and discard only this staged desired record.
            pass
        for entry_name, evidence in ((old_name, old), (new_name, new)):
            if evidence is not None:
                if entry_name.startswith("retired-"):
                    os.unlink(entry_name, dir_fd=descriptor)
                    os.fsync(descriptor)
                else:
                    _retire_json_entry(descriptor, entry_name, evidence)
        _close_json_cas(parent, descriptor, directory)
        os.close(descriptor)
        closed = True
    finally:
        if not closed:
            os.close(descriptor)


def _install_json(
    parent: int,
    name: str,
    value: object,
    *,
    replace_identity: tuple[int, ...] | None = None,
) -> tuple[str, tuple[int, ...]]:
    data = _canonical_bytes(value) + b"\n"
    digest = hashlib.sha256(data).hexdigest()
    _recover_json_install(parent, name)
    opened = _open_json_cas(parent, name, create=True)
    if opened is None:
        raise _fail("JSON transaction is unavailable")
    descriptor, directory = opened
    closed = False
    try:
        if os.listdir(descriptor):
            raise _fail("JSON transaction is not empty")
        _write_staged_json(
            descriptor, name, value, temporary_name="new"
        )
        desired = _json_cas_evidence(descriptor, "new")
        if desired is None or desired[1] != digest or desired[3] != data:
            raise _fail("JSON transaction desired record changed")
        if replace_identity is None:
            try:
                os.link(
                    "new", name,
                    src_dir_fd=descriptor, dst_dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileExistsError:
                raise _fail("JSON destination conflict")
        else:
            before = _json_cas_evidence(parent, name)
            if before is None or before[0] != replace_identity:
                raise _fail("journal changed before update")
            try:
                os.rename(
                    name, "old", src_dir_fd=parent, dst_dir_fd=descriptor
                )
            except FileNotFoundError:
                raise _fail("journal changed before update") from None
            old_file = _file_evidence(
                descriptor, "old", allowed_links=frozenset({1}),
                capture_limit=len(before[3]),
            )
            if (
                old_file[0][:3] != before[0][:3]
                or old_file[1:] != before[1:]
            ):
                if not _exists_nofollow(parent, name):
                    try:
                        os.link(
                            "old", name,
                            src_dir_fd=descriptor, dst_dir_fd=parent,
                            follow_symlinks=False,
                        )
                        os.fsync(parent)
                    except FileExistsError:
                        pass
                raise _fail("journal changed before update")
            old = _json_cas_evidence(descriptor, "old")
            if old is None:
                raise _fail("journal changed before update")
            os.link(
                "new", name,
                src_dir_fd=descriptor, dst_dir_fd=parent,
                follow_symlinks=False,
            )
        os.fsync(parent)
        installed = _json_cas_evidence(parent, name)
        if not _same_file(installed, desired):
            raise _fail("installed JSON record does not match the transaction")
        old = _json_cas_evidence(descriptor, "old")
        if old is not None:
            _retire_json_entry(descriptor, "old", old)
        desired = _json_cas_evidence(descriptor, "new")
        if desired is not None:
            _retire_json_entry(descriptor, "new", desired)
        _close_json_cas(parent, descriptor, directory)
        os.close(descriptor)
        closed = True
        installed = _json_cas_evidence(parent, name)
        if installed is None or installed[0][3] != 1 or installed[1] != digest:
            raise _fail("installed JSON record does not match the transaction")
        return digest, installed[0]
    finally:
        if not closed:
            os.close(descriptor)


def _checked_file_evidence(
    parent: int,
    name: str,
    *,
    digest: str,
    size: int,
    raw: bytes | None = None,
) -> tuple[tuple[int, ...], str, int, bytes] | None:
    if not _exists_nofollow(parent, name):
        return None
    evidence = _file_evidence(
        parent,
        name,
        allowed_links=frozenset({1, 2}),
        capture_limit=(len(raw) if raw is not None else 0),
    )
    if evidence[1] != digest or evidence[2] != size:
        raise _fail("published stock asset conflict")
    if raw is not None and evidence[3] != raw:
        raise _fail("published stock asset conflict")
    return evidence


def _retire_torn_license_stage(
    parent: int, name: str, expected_raw: bytes
) -> None:
    evidence = _file_evidence(
        parent, name, allowed_links=frozenset({1}),
        capture_limit=len(expected_raw),
    )
    if (
        stat.S_IMODE(evidence[0][2]) != 0o600
        or evidence[2] >= len(expected_raw)
        or evidence[3] != expected_raw[: evidence[2]]
    ):
        raise _fail("license staging conflicts with publication")
    _remove_owned_name(
        parent, name, identity=evidence[0], digest=evidence[1],
        size=evidence[2], raw=evidence[3],
    )
    if _exists_nofollow(parent, name):
        raise _fail("license staging could not be retired")


def _validate_published_files(
    parent: int,
    journal: dict[str, object],
    planned_name: str,
    license_name: str,
) -> None:
    license_raw = _canonical_bytes(journal["license_record"]) + b"\n"
    license_evidence = _checked_file_evidence(
        parent, license_name, digest=journal["license_sha256"],
        size=len(license_raw), raw=license_raw,
    )
    asset_evidence = _checked_file_evidence(
        parent, planned_name, digest=journal["sha256"],
        size=journal["byte_count"],
    )
    if (
        license_evidence is None
        or asset_evidence is None
        or license_evidence[0][3] != 1
        or asset_evidence[0][3] != 1
        or license_evidence[0][:3] != tuple(journal["license_identity"])
        or asset_evidence[0][:3] != tuple(journal["expected_identity"][:3])
    ):
        raise _fail("published stock receipt conflicts with Job files")
    for job_path in (
        journal["staging_job_path"], journal["license_staging_job_path"]
    ):
        if _exists_nofollow(
            parent, _job_parts(job_path, label="staging job_path")[-1]
        ):
            raise _fail("published stock receipt has orphan staging")


def _download_record_matches(
    record: object,
    journal: dict[str, object],
    journal_path: str,
    journal_sha: str,
) -> bool:
    if type(record) is not DownloadRecord:
        return False
    immutable = (
        "provider", "provider_asset_id", "search_generation",
        "snapshot_sha256", "query_sha256", "idempotency_key",
        "staging_job_path", "license_staging_job_path", "planned_job_path",
        "planned_license_snapshot", "media_type", "format", "mime_type",
        "downloaded_at", "byte_count", "sha256", "actual_width",
        "actual_height", "dimensions_source",
    )
    if (
        record.schema_version != 1
        or record.journal_job_path != journal_path
        or any(record[field] != journal[field] for field in immutable)
        or record.expected_identity != tuple(journal["expected_identity"])
    ):
        return False
    ranks = {"complete": 0, "publishing": 1, "published": 2}
    if record.status not in ranks or journal["state"] not in ranks:
        return False
    if ranks[record.status] > ranks[journal["state"]]:
        return False
    if record.status == journal["state"] and record.journal_sha256 != journal_sha:
        return False
    return record.license_sha256 in {None, journal["license_sha256"]}


def _finish_hardlink_move(
    root: Any,
    parent: int,
    parent_parts: tuple[str, ...],
    parent_descriptors: list[int],
    *,
    source_name: str,
    destination_name: str,
    digest: str,
    size: int,
    raw: bytes | None = None,
    expected_identity: tuple[int, ...] | None = None,
) -> None:
    """Finish one journal-authorized hardlink move without deleting conflicts."""
    source = _checked_file_evidence(
        parent, source_name, digest=digest, size=size, raw=raw
    )
    destination = _checked_file_evidence(
        parent, destination_name, digest=digest, size=size, raw=raw
    )
    for evidence in (source, destination):
        if (
            evidence is not None
            and expected_identity is not None
            and evidence[0][: len(expected_identity)] != expected_identity
        ):
            raise _fail("published stock asset conflict")
    if source is None and destination is None:
        raise _fail("published stock asset conflict")
    if source is not None and destination is None:
        if source[0][3] != 1:
            raise _fail("published stock asset conflict")
        _verify_parent_chain(root, parent_parts, parent_descriptors)
        os.link(
            source_name,
            destination_name,
            src_dir_fd=parent,
            dst_dir_fd=parent,
            follow_symlinks=False,
        )
        os.fsync(parent)
        _verify_parent_chain(root, parent_parts, parent_descriptors)
        source = _checked_file_evidence(
            parent, source_name, digest=digest, size=size, raw=raw
        )
        destination = _checked_file_evidence(
            parent, destination_name, digest=digest, size=size, raw=raw
        )
    if source is not None:
        if (
            destination is None
            or source[0] != destination[0]
            or source[0][3] != 2
        ):
            raise _fail("published stock asset conflict")
        _verify_parent_chain(root, parent_parts, parent_descriptors)
        _remove_owned_name(
            parent,
            source_name,
            identity=source[0],
            digest=digest,
            size=size,
            raw=raw,
        )
        _verify_parent_chain(root, parent_parts, parent_descriptors)
    elif destination is not None and destination[0][3] == 2:
        # A previous attempt may have moved the source into its deterministic
        # cleanup stage and stopped before deleting the staged hardlink.
        _remove_owned_name(
            parent,
            source_name,
            identity=destination[0],
            digest=digest,
            size=size,
            raw=raw,
        )
        _verify_parent_chain(root, parent_parts, parent_descriptors)
    destination = _checked_file_evidence(
        parent, destination_name, digest=digest, size=size, raw=raw
    )
    if destination is None or destination[0][3] != 1:
        raise _fail("published stock asset conflict")


def publish_frozen_asset(
    frozen_snapshot: object,
    candidate_id: str,
    download_record: object | None,
    *,
    job_dir: os.PathLike[str] | str,
    idempotency_key: str,
) -> dict[str, object]:
    """Recoverably publish the asset described by the single durable journal."""
    snapshot = _checked_snapshot(frozen_snapshot)
    candidate = _find_candidate(snapshot, candidate_id)
    planned_path, license_path, journal_path = _planned_paths(
        idempotency_key, candidate["extension"]
    )
    planned_parts = _job_parts(planned_path, label="planned job_path")
    license_parts = _job_parts(license_path, label="license_snapshot")
    journal_parts = _job_parts(journal_path, label="journal_job_path")
    pinned = _pin_job(job_dir)
    parents: list[int] = []
    lock_descriptor: int | None = None
    try:
        parent, parents = _open_parent(pinned.descriptor, planned_parts[:-1], create=True)
        if not (
            planned_parts[:-1] == license_parts[:-1] == journal_parts[:-1]
        ):
            raise _fail("stock publication records must share a directory")
        _verify_parent_chain(pinned, planned_parts[:-1], parents)
        lock_descriptor = _open_lock(parent, idempotency_key)
        _verify_parent_chain(pinned, planned_parts[:-1], parents)
        _recover_json_install(parent, journal_parts[-1])
        if not _exists_nofollow(parent, journal_parts[-1]):
            raise _fail("download journal is required")
        raw_journal, journal_sha, journal_identity = _read_exact_json_record(
            pinned, journal_path
        )
        journal = _validate_journal(
            raw_journal, snapshot, candidate, idempotency_key,
            planned_path, license_path
        )
        _verify_parent_chain(pinned, planned_parts[:-1], parents)
        if journal["state"] == "published":
            if download_record is not None and not _download_record_matches(
                download_record, journal, journal_path, journal_sha
            ):
                raise _fail("download record does not match its journal")
            existing = _existing_publish(
                pinned, planned_path=planned_path, license_path=license_path,
                idempotency_key=idempotency_key, snapshot=snapshot,
                candidate=candidate,
            )
            if existing is None:
                raise _fail("published stock receipt conflicts with Job files")
            _validate_published_files(
                parent, journal, planned_parts[-1], license_parts[-1]
            )
            return existing

        if not _download_record_matches(
            download_record, journal, journal_path, journal_sha
        ):
            raise _fail("download record does not match its journal")
        if journal["state"] not in {"complete", "publishing"}:
            raise _fail("download journal is not ready for publication")

        if journal["state"] == "complete":
            license_record = _license_record(
                snapshot, candidate, journal, idempotency_key,
                planned_path, license_path,
            )
            license_raw = _canonical_bytes(license_record) + b"\n"
            publishing = _journal_value(
                snapshot, candidate, idempotency_key, journal["nonce"],
                journal["staging_job_path"], planned_path, license_path,
                state="publishing",
                expected_identity=tuple(journal["expected_identity"]),
                downloaded_at=journal["downloaded_at"],
                byte_count=journal["byte_count"], sha256=journal["sha256"],
                actual_width=journal["actual_width"],
                actual_height=journal["actual_height"],
                dimensions_source=journal["dimensions_source"],
                license_record=license_record,
                license_sha256=hashlib.sha256(license_raw).hexdigest(),
            )
            journal_sha, journal_identity = _install_json(
                parent, journal_parts[-1], publishing,
                replace_identity=journal_identity,
            )
            journal = _validate_journal(
                publishing, snapshot, candidate, idempotency_key,
                planned_path, license_path,
            )
            _verify_parent_chain(pinned, planned_parts[:-1], parents)

        license_record = journal["license_record"]
        license_raw = _canonical_bytes(license_record) + b"\n"
        license_sha = journal["license_sha256"]
        license_stage_parts = _job_parts(
            journal["license_staging_job_path"],
            label="license_staging_job_path",
        )
        staging_parts = _job_parts(
            journal["staging_job_path"], label="staging_job_path"
        )

        if journal["license_identity"] is None:
            try:
                license_stage = _checked_file_evidence(
                    parent, license_stage_parts[-1], digest=license_sha,
                    size=len(license_raw), raw=license_raw,
                )
            except StockMediaError:
                if not _exists_nofollow(parent, license_stage_parts[-1]):
                    raise
                _retire_torn_license_stage(
                    parent, license_stage_parts[-1], license_raw
                )
                license_stage = None
            license_final = _checked_file_evidence(
                parent, license_parts[-1], digest=license_sha,
                size=len(license_raw), raw=license_raw,
            )
            if license_final is not None:
                raise _fail("published stock asset conflict")
            if license_stage is None:
                _write_staged_json(
                    parent, license_parts[-1], license_record,
                    temporary_name=license_stage_parts[-1],
                )
                license_stage = _checked_file_evidence(
                    parent, license_stage_parts[-1], digest=license_sha,
                    size=len(license_raw), raw=license_raw,
                )
            if license_stage is None or license_stage[0][3] != 1:
                raise _fail("published stock asset conflict")
            identified = dict(journal)
            identified["license_identity"] = list(license_stage[0][:3])
            journal_sha, journal_identity = _install_json(
                parent, journal_parts[-1], identified,
                replace_identity=journal_identity,
            )
            journal = _validate_journal(
                identified, snapshot, candidate, idempotency_key,
                planned_path, license_path,
            )
            _verify_parent_chain(pinned, planned_parts[:-1], parents)

        _finish_hardlink_move(
            pinned, parent, planned_parts[:-1], parents,
            source_name=license_stage_parts[-1],
            destination_name=license_parts[-1], digest=license_sha,
            size=len(license_raw), raw=license_raw,
            expected_identity=tuple(journal["license_identity"]),
        )
        _finish_hardlink_move(
            pinned, parent, planned_parts[:-1], parents,
            source_name=staging_parts[-1],
            destination_name=planned_parts[-1], digest=journal["sha256"],
            size=journal["byte_count"],
            expected_identity=tuple(journal["expected_identity"][:3]),
        )

        result = _existing_publish(
            pinned, planned_path=planned_path, license_path=license_path,
            idempotency_key=idempotency_key, snapshot=snapshot,
            candidate=candidate,
        )
        if result is None:
            raise _fail("published stock asset verification failed")
        published = dict(journal)
        published["state"] = "published"
        _validate_journal(
            published, snapshot, candidate, idempotency_key,
            planned_path, license_path,
        )
        _validate_published_files(
            parent, published, planned_parts[-1], license_parts[-1]
        )
        _verify_parent_chain(pinned, planned_parts[:-1], parents)
        _install_json(
            parent, journal_parts[-1], published,
            replace_identity=journal_identity,
        )
        _verify_parent_chain(pinned, planned_parts[:-1], parents)
        return result
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(failure, StockMediaError):
            raise
        raise _fail("stock asset publication failed") from None
    finally:
        if lock_descriptor is not None:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(lock_descriptor)
        _broll_media._close_all(parents)
        pinned.close()


def _exists_nofollow(parent: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise _fail("publish destination is unavailable") from None


def _unlink_if_identity(
    parent: int,
    name: str,
    identity: tuple[int, ...] | None,
) -> bool:
    if identity is None:
        return False
    try:
        return _remove_owned_name(parent, name, identity=identity)
    except (OSError, StockMediaError):
        return False
