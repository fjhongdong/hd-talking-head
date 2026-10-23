from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from edit.hd.tools import stock_media


REQUEST_ONLY_VALUE = "stock-request-only-canary-7b3d"
NOW = datetime(2026, 8, 31, 4, 5, 6, tzinfo=timezone.utc)
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


class FakeTransport:
    def __init__(self, *responses: stock_media.TransportResponse) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def request(self, url: str, *, headers: dict[str, str], timeout: float):
        self.calls.append((url, dict(headers)))
        if not self.responses:
            raise AssertionError("unexpected transport call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class ExplodingBody:
    def __iter__(self):
        yield MP4[:12]
        raise RuntimeError(f"stream failed with Cookie={REQUEST_ONLY_VALUE}")


class RequestOnlyValueStockErrorBody:
    def __iter__(self):
        raise stock_media.StockMediaError(
            f"Authorization: Bearer {REQUEST_ONLY_VALUE}"
        )
        yield b""  # pragma: no cover - keeps this an iterator


class CloseTrackingBody:
    def __init__(self, body: bytes = b"") -> None:
        self.body = body
        self.offset = 0
        self.close_calls = 0

    def read(self, size: int) -> bytes:
        chunk = self.body[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.close_calls += 1


class SimulatedCrash(SystemExit):
    pass


def response(
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "application/json",
    headers: dict[str, str] | None = None,
) -> stock_media.TransportResponse:
    resolved_headers = {"Content-Type": content_type}
    if headers:
        resolved_headers.update(headers)
    return stock_media.TransportResponse(status, resolved_headers, body)


def pexels_payload(*, candidate_id: int = 101, url: str | None = None) -> bytes:
    download_url = url or "https://videos.pexels.com/video-files/101/101-hd.mp4"
    return json.dumps(
        {
            "videos": [
                {
                    "id": candidate_id,
                    "duration": 12,
                    "url": f"https://www.pexels.com/video/example-{candidate_id}/",
                    "user": {"name": "Ada"},
                    "video_files": [
                        {
                            "id": 9,
                            "file_type": "video/mp4",
                            "width": 640,
                            "height": 360,
                            "link": "https://videos.pexels.com/video-files/101/low.mp4",
                        },
                        {
                            "id": 8,
                            "file_type": "video/mp4",
                            "width": 1080,
                            "height": 1920,
                            "link": download_url,
                        },
                    ],
                }
            ]
        },
        separators=(",", ":"),
    ).encode()


def pixabay_payload(*, candidate_id: int = 202) -> bytes:
    return json.dumps(
        {
            "hits": [
                {
                    "id": candidate_id,
                    "duration": 9,
                    "user": "Grace",
                    "pageURL": f"https://pixabay.com/videos/id-{candidate_id}/",
                    "videos": {
                        "small": {
                            "url": "https://cdn.pixabay.com/video/202/small.mp4",
                            "width": 640,
                            "height": 360,
                            "size": 20,
                        },
                        "large": {
                            "url": "",
                            "width": 0,
                            "height": 0,
                            "size": 0,
                        },
                        "medium": {
                            "url": "https://cdn.pixabay.com/video/202/medium.mp4",
                            "width": 1080,
                            "height": 1920,
                            "size": 40,
                        },
                    },
                }
            ]
        },
        separators=(",", ":"),
    ).encode()


def pexels_photo_payload(*, candidate_id: int = 303, url: str | None = None) -> bytes:
    return json.dumps(
        {
            "photos": [
                {
                    "id": candidate_id,
                    "url": f"https://www.pexels.com/photo/example-{candidate_id}/",
                    "photographer": "Lin",
                    "width": 1600,
                    "height": 2400,
                    "src": {
                        "original": url
                        or "https://images.pexels.com/photos/303/example.jpeg?fit=crop&h=1920&w=1080"
                    },
                }
            ]
        },
        separators=(",", ":"),
    ).encode()


def pixabay_image_payload(*, candidate_id: int = 404) -> bytes:
    return json.dumps(
        {
            "hits": [
                {
                    "id": candidate_id,
                    "user": "Katherine",
                    "pageURL": f"https://pixabay.com/photos/id-{candidate_id}/",
                    "imageWidth": 1920,
                    "imageHeight": 1080,
                    "largeImageURL": "https://pixabay.com/get/original.jpg",
                    "webformatURL": "https://cdn.pixabay.com/photo/2026/web.jpg",
                    "webformatWidth": 640,
                    "webformatHeight": 360,
                }
            ]
        },
        separators=(",", ":"),
    ).encode()


def freeze_pexels(
    transport: FakeTransport,
    *,
    query: str = "robot laboratory",
    media_type: str = "video",
) -> dict[str, object]:
    return stock_media.freeze_search_snapshot(
        "pexels",
        query,
        media_type=media_type,
        api_key=REQUEST_ONLY_VALUE,
        transport=transport,
        clock=lambda: NOW,
    )


def good_probe(_path: str, _media_type: str) -> dict[str, object]:
    return {
        "media_type": "video", "format": "mp4",
        "width": 1080, "height": 1920,
    }


class ProviderSnapshotTests(unittest.TestCase):
    def test_provider_adapter_uses_connection_value_api(self) -> None:
        pexels = stock_media.PexelsAdapter()
        pixabay = stock_media.PixabayAdapter()

        for adapter in (pexels, pixabay):
            self.assertTrue(hasattr(adapter, "connection_environment"))
            parameters = inspect.signature(adapter.search_request).parameters
            self.assertIn("connection_value", parameters)

        self.assertTrue(hasattr(stock_media, "_connection_value"))

    def test_registered_provider_hosts_are_explicit_and_exact(self) -> None:
        self.assertEqual(stock_media.PEXELS_API_HOSTS, frozenset({"api.pexels.com"}))
        self.assertEqual(
            stock_media.PEXELS_CDN_HOSTS,
            frozenset({"videos.pexels.com", "images.pexels.com"}),
        )
        self.assertEqual(stock_media.PIXABAY_API_HOSTS, frozenset({"pixabay.com"}))
        self.assertEqual(
            stock_media.PIXABAY_CDN_HOSTS,
            frozenset({"cdn.pixabay.com", "pixabay.com"}),
        )

    def test_pexels_freezes_order_hash_and_deterministic_best_variant(self) -> None:
        raw = pexels_payload()
        transport = FakeTransport(response(raw))

        frozen = freeze_pexels(transport)

        self.assertEqual(frozen["provider"], "pexels")
        self.assertEqual(frozen["query"], "robot laboratory")
        self.assertEqual(frozen["media_type"], "video")
        self.assertEqual(frozen["searched_at"], "2026-08-31T04:05:06+00:00")
        self.assertEqual(frozen["candidate_ids"], ["101"])
        self.assertEqual(frozen["result_order"], ["101"])
        self.assertEqual(frozen["response_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(
            frozen["candidates"][0]["download_url"],
            "https://videos.pexels.com/video-files/101/101-hd.mp4",
        )
        self.assertEqual(frozen["candidates"][0]["format"], "mp4")
        self.assertEqual(frozen["candidates"][0]["width"], 1080)
        self.assertEqual(frozen["candidates"][0]["height"], 1920)
        self.assertEqual(frozen["candidates"][0]["duration"], 12)
        self.assertEqual(
            transport.calls[0][0],
            "https://api.pexels.com/v1/videos/search?per_page=40&query=robot+laboratory",
        )
        self.assertNotIn(REQUEST_ONLY_VALUE, json.dumps(frozen, sort_keys=True))

    def test_pexels_filters_bad_variants_but_requires_one_usable_mp4(self) -> None:
        payload = json.loads(pexels_payload())
        payload["videos"][0]["video_files"].extend(
            (
                {
                    "file_type": "application/x-mpegURL",
                    "width": 3840,
                    "height": 2160,
                    "link": "https://videos.pexels.com/stream.m3u8",
                },
                {
                    "file_type": None,
                    "width": 1920,
                    "height": 1080,
                    "link": None,
                },
            )
        )

        frozen = freeze_pexels(
            FakeTransport(response(json.dumps(payload).encode()))
        )

        self.assertEqual(frozen["candidates"][0]["format"], "mp4")

        payload["videos"][0]["video_files"] = payload["videos"][0][
            "video_files"
        ][-2:]
        with self.assertRaises(stock_media.StockMediaError):
            freeze_pexels(FakeTransport(response(json.dumps(payload).encode())))

    def test_pexels_and_pixabay_support_image_search(self) -> None:
        pexels = freeze_pexels(
            FakeTransport(response(pexels_photo_payload())), media_type="image"
        )
        pixabay = stock_media.freeze_search_snapshot(
            "pixabay",
            "city skyline",
            media_type="image",
            api_key=REQUEST_ONLY_VALUE,
            transport=FakeTransport(response(pixabay_image_payload())),
            clock=lambda: NOW,
        )

        self.assertEqual(pexels["candidates"][0]["media_type"], "image")
        self.assertEqual(pexels["candidates"][0]["format"], "jpeg")
        self.assertEqual(
            pexels["candidates"][0]["download_url"],
            "https://images.pexels.com/photos/303/example.jpeg?fit=crop&h=1920&w=1080",
        )
        self.assertEqual(pixabay["candidates"][0]["media_type"], "image")
        self.assertEqual(pixabay["candidates"][0]["width"], 640)
        self.assertEqual(pixabay["candidates"][0]["height"], 360)
        self.assertEqual(pixabay["candidates"][0]["dimensions_source"], "provider_variant")
        self.assertEqual(pixabay["candidates"][0]["format"], "jpeg")
        self.assertEqual(pexels["candidates"][0]["width"], 1080)
        self.assertEqual(pexels["candidates"][0]["height"], 1920)
        self.assertEqual(pexels["candidates"][0]["dimensions_source"], "url_variant")
        self.assertNotEqual(pexels["query_sha256"], self._video_query_sha())

    def _video_query_sha(self) -> str:
        frozen = freeze_pexels(FakeTransport(response(pexels_payload())))
        return frozen["query_sha256"]

    def test_cdn_query_is_canonicalized_and_non_record_or_unknown_keys_stop(self) -> None:
        reordered = freeze_pexels(
            FakeTransport(
                response(
                    pexels_photo_payload(
                        url="https://images.pexels.com/photos/303/example.jpeg?w=1080&fit=crop&h=1920"
                    )
                )
            ),
            media_type="image",
        )
        self.assertEqual(
            reordered["candidates"][0]["download_url"],
            "https://images.pexels.com/photos/303/example.jpeg?fit=crop&h=1920&w=1080",
        )

        for query in (
            "token=abc",
            "signature=abc",
            "key=abc",
            "expires=123",
            "unknown=1",
            "w=1&w=2",
            "=value",
            "w=%00",
        ):
            with self.subTest(query=query):
                with self.assertRaises(stock_media.StockMediaError):
                    freeze_pexels(
                        FakeTransport(
                            response(
                                pexels_photo_payload(
                                    url=f"https://images.pexels.com/photos/303/example.jpeg?{query}"
                                )
                            )
                        ),
                        media_type="image",
                    )

    def test_pixabay_adapter_uses_key_without_persisting_it(self) -> None:
        transport = FakeTransport(response(pixabay_payload()))

        frozen = stock_media.freeze_search_snapshot(
            "pixabay",
            "vertical city",
            media_type="video",
            api_key=REQUEST_ONLY_VALUE,
            transport=transport,
            clock=lambda: NOW,
        )

        self.assertEqual(frozen["provider"], "pixabay")
        self.assertEqual(frozen["result_order"], ["202"])
        self.assertIn(REQUEST_ONLY_VALUE, transport.calls[0][0])
        self.assertNotIn(REQUEST_ONLY_VALUE, json.dumps(frozen, sort_keys=True))
        self.assertEqual(
            frozen["candidates"][0]["download_url"],
            "https://cdn.pixabay.com/video/202/medium.mp4",
        )

    def test_replaying_a_frozen_snapshot_does_not_touch_transport(self) -> None:
        frozen = freeze_pexels(FakeTransport(response(pexels_payload())))
        transport = FakeTransport()

        replayed = stock_media.freeze_search_snapshot(
            "pexels",
            "robot laboratory",
            media_type="video",
            frozen_snapshot=frozen,
            transport=transport,
        )

        self.assertEqual(replayed, frozen)
        self.assertIsNot(replayed, frozen)
        self.assertEqual(transport.calls, [])

    def test_snapshot_replay_requires_canonical_rfc3339_searched_at(self) -> None:
        frozen = freeze_pexels(FakeTransport(response(pexels_payload())))
        invalid = copy.deepcopy(frozen)
        invalid["searched_at"] = "2026-08-31 04:05:06+00:00"
        invalid["snapshot_sha256"] = stock_media._digest({
            key: value for key, value in invalid.items()
            if key != "snapshot_sha256"
        })
        transport = FakeTransport()

        with self.assertRaises(stock_media.StockMediaError):
            stock_media.freeze_search_snapshot(
                "pexels",
                "robot laboratory",
                media_type="video",
                frozen_snapshot=invalid,
                transport=transport,
            )

        self.assertEqual(transport.calls, [])
        canonical_z = copy.deepcopy(frozen)
        canonical_z["searched_at"] = "2026-08-31T04:05:06Z"
        canonical_z["snapshot_sha256"] = stock_media._digest({
            key: value for key, value in canonical_z.items()
            if key != "snapshot_sha256"
        })
        replayed = stock_media.freeze_search_snapshot(
            "pexels",
            "robot laboratory",
            media_type="video",
            frozen_snapshot=canonical_z,
            transport=transport,
        )
        self.assertEqual(replayed["searched_at"], "2026-08-31T04:05:06Z")
        self.assertEqual(transport.calls, [])

    def test_duplicate_or_malformed_provider_results_stop_explicitly(self) -> None:
        duplicate = json.loads(pexels_payload())
        duplicate["videos"].append(copy.deepcopy(duplicate["videos"][0]))
        malformed = json.loads(pexels_payload())
        del malformed["videos"][0]["user"]
        duplicate_key_json = b'{"videos":[],"videos":[]}'

        for raw in (
            json.dumps(duplicate).encode(),
            json.dumps(malformed).encode(),
            duplicate_key_json,
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(stock_media.StockMediaError):
                    freeze_pexels(FakeTransport(response(raw)))

        for nonfinite in (b'{"videos":NaN}', b'{"videos":Infinity}', b'{"videos":-Infinity}'):
            with self.subTest(nonfinite=nonfinite):
                with self.assertRaises(stock_media.StockMediaError):
                    freeze_pexels(FakeTransport(response(nonfinite)))

    def test_provider_failure_never_falls_back_to_another_provider(self) -> None:
        transport = FakeTransport(response(b"nope", status=503, content_type="text/plain"))

        with self.assertRaisesRegex(stock_media.StockMediaError, "search failed") as caught:
            freeze_pexels(transport)

        self.assertEqual(len(transport.calls), 1)
        self.assertIn("api.pexels.com", transport.calls[0][0])
        self.assertNotIn("pixabay", str(caught.exception).lower())

    def test_snapshot_record_changes_are_rejected_before_replay(self) -> None:
        frozen = freeze_pexels(FakeTransport(response(pexels_payload())))
        frozen["result_order"] = ["other"]
        transport = FakeTransport()

        with self.assertRaises(stock_media.StockMediaError):
            stock_media.freeze_search_snapshot(
                "pexels",
                "robot laboratory",
                media_type="video",
                frozen_snapshot=frozen,
                transport=transport,
            )

        self.assertEqual(transport.calls, [])

    def test_transport_exception_does_not_record_request_only_values(self) -> None:
        for failure in (
            RuntimeError(f"bad Authorization Bearer {REQUEST_ONLY_VALUE}"),
            stock_media.StockMediaError(f"api_key={REQUEST_ONLY_VALUE}"),
        ):
            with self.subTest(failure=type(failure).__name__):
                with self.assertRaises(stock_media.StockMediaError) as caught:
                    freeze_pexels(FakeTransport(failure))
                self.assertNotIn(REQUEST_ONLY_VALUE, str(caught.exception))

    def test_search_body_exception_and_provider_echo_do_not_record_connection_value(self) -> None:
        exploding = stock_media.TransportResponse(
            200, {"Content-Type": "application/json"}, ExplodingBody()
        )
        with self.assertRaises(stock_media.StockMediaError) as caught:
            freeze_pexels(FakeTransport(exploding))
        self.assertNotIn(REQUEST_ONLY_VALUE, str(caught.exception))

        request_value_stock_error = stock_media.TransportResponse(
            200,
            {"Content-Type": "application/json"},
            RequestOnlyValueStockErrorBody(),
        )
        with self.assertRaises(stock_media.StockMediaError) as caught:
            freeze_pexels(FakeTransport(request_value_stock_error))
        self.assertNotIn(REQUEST_ONLY_VALUE, str(caught.exception))

        echoed = json.loads(pexels_payload())
        echoed["videos"][0]["user"]["name"] = REQUEST_ONLY_VALUE
        with self.assertRaises(stock_media.StockMediaError):
            freeze_pexels(FakeTransport(response(json.dumps(echoed).encode())))

        non_record_field = json.loads(pexels_payload())
        non_record_field["authorization"] = "request-only-field-value"
        with self.assertRaises(stock_media.StockMediaError):
            freeze_pexels(
                FakeTransport(response(json.dumps(non_record_field).encode()))
            )

    def test_invalid_response_status_and_headers_close_body(self) -> None:
        bodies = (CloseTrackingBody(), CloseTrackingBody())
        responses = (
            stock_media.TransportResponse(True, {}, bodies[0]),
            stock_media.TransportResponse(
                200, {"Content-Type": object()}, bodies[1]
            ),
        )
        for provider_response, body in zip(responses, bodies):
            with self.subTest(status=provider_response.status):
                with self.assertRaises(stock_media.StockMediaError):
                    freeze_pexels(FakeTransport(provider_response))
                self.assertEqual(body.close_calls, 1)

    def test_adapter_exception_is_bounded_and_snapshot_types_are_exact(self) -> None:
        with mock.patch.object(
            stock_media.PexelsAdapter,
            "parse",
            side_effect=RuntimeError(
                f"parse failed Authorization={REQUEST_ONLY_VALUE}"
            ),
        ):
            with self.assertRaises(stock_media.StockMediaError) as caught:
                freeze_pexels(FakeTransport(response(pexels_payload())))
        self.assertNotIn(REQUEST_ONLY_VALUE, str(caught.exception))

        frozen = freeze_pexels(FakeTransport(response(pexels_payload())))
        for path, value in (
            (("schema_version",), True),
            (("candidate_ids",), ("101",)),
            (("candidates", 0, "width"), True),
        ):
            with self.subTest(path=path):
                changed = copy.deepcopy(frozen)
                target = changed
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                with self.assertRaises(stock_media.StockMediaError):
                    stock_media.freeze_search_snapshot(
                        "pexels",
                        "robot laboratory",
                        media_type="video",
                        frozen_snapshot=changed,
                        transport=FakeTransport(),
                    )

    def test_query_and_connection_value_must_be_bounded_utf8_before_transport(self) -> None:
        for query, connection_value in (
            ("\ud800", REQUEST_ONLY_VALUE),
            ("q" * 1025, REQUEST_ONLY_VALUE),
            ("robot", "\ud800"),
            ("robot", "k" * 4097),
        ):
            with self.subTest(
                query_length=len(query),
                connection_value_length=len(connection_value),
            ):
                transport = FakeTransport(response(pexels_payload()))
                with self.assertRaises(stock_media.StockMediaError):
                    stock_media.freeze_search_snapshot(
                        "pexels",
                        query,
                        media_type="video",
                        api_key=connection_value,
                        transport=transport,
                        clock=lambda: NOW,
                    )
                self.assertEqual(transport.calls, [])

    def test_adapter_request_construction_failure_is_bounded(self) -> None:
        transport = FakeTransport()
        with mock.patch.object(
            stock_media.PexelsAdapter,
            "search_request",
            side_effect=RuntimeError(f"Authorization={REQUEST_ONLY_VALUE}"),
        ):
            with self.assertRaises(stock_media.StockMediaError) as caught:
                freeze_pexels(transport)

        self.assertEqual(transport.calls, [])
        self.assertNotIn(REQUEST_ONLY_VALUE, str(caught.exception))


class IdempotencyTests(unittest.TestCase):
    def test_key_uses_only_six_canonical_fields(self) -> None:
        query_sha = hashlib.sha256(b"query").hexdigest()
        args = ("job-1", "seg-1", "component-1", 3, "pexels", query_sha)

        first = stock_media.stable_idempotency_key(*args)
        second = stock_media.stable_idempotency_key(*args)

        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        for index, replacement in ((3, 4), (4, "pixabay"), (5, "b" * 64)):
            changed = list(args)
            changed[index] = replacement
            self.assertNotEqual(first, stock_media.stable_idempotency_key(*changed))

    def test_key_rejects_bool_revision_and_noncanonical_types(self) -> None:
        query_sha = hashlib.sha256(b"query").hexdigest()
        invalid_args = (
            ("job", "seg", "component", True, "pexels", query_sha),
            ("job", "seg", "component", 1, "Pexels", query_sha),
            ("job", "seg", "component", 1, "pexels", "A" * 64),
            (1, "seg", "component", 1, "pexels", query_sha),
        )
        for args in invalid_args:
            with self.subTest(args=args):
                with self.assertRaises(stock_media.StockMediaError):
                    stock_media.stable_idempotency_key(*args)

    def test_media_type_changes_normalized_query_hash_and_therefore_key(self) -> None:
        video = freeze_pexels(FakeTransport(response(pexels_payload())))
        image = freeze_pexels(
            FakeTransport(response(pexels_photo_payload())), media_type="image"
        )
        video_key = stock_media.stable_idempotency_key(
            "job", "seg", "component", 1, "pexels", video["query_sha256"]
        )
        image_key = stock_media.stable_idempotency_key(
            "job", "seg", "component", 1, "pexels", image["query_sha256"]
        )
        self.assertNotEqual(video_key, image_key)


class JsonInstallTests(unittest.TestCase):
    def test_lock_fd_is_closed_when_flock_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
            captured: list[int] = []

            def fail_flock(lock_fd: int, _operation: int) -> None:
                captured.append(lock_fd)
                raise OSError("flock failed")

            try:
                with mock.patch.object(
                    stock_media.fcntl, "flock", side_effect=fail_flock
                ):
                    with self.assertRaises(stock_media.StockMediaError):
                        stock_media._open_lock(descriptor, "a" * 64)
                self.assertEqual(len(captured), 1)
                with self.assertRaises(OSError):
                    os.fstat(captured[0])
            finally:
                os.close(descriptor)

    def test_json_cas_dir_fd_is_closed_when_fstat_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            descriptor = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
            original_fstat = stock_media.os.fstat
            captured: list[int] = []

            def fail_cas_fstat(opened: int):
                if opened != descriptor:
                    captured.append(opened)
                    raise OSError("fstat failed")
                return original_fstat(opened)

            try:
                with mock.patch.object(
                    stock_media.os, "fstat", side_effect=fail_cas_fstat
                ):
                    with self.assertRaises(stock_media.StockMediaError):
                        stock_media._open_json_cas(
                            descriptor, "journal.json", create=True
                        )
                self.assertEqual(len(captured), 1)
                with self.assertRaises(OSError):
                    os.fstat(captured[0])
            finally:
                os.close(descriptor)

    def test_initial_install_never_overwrites_concurrent_destination(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            name = "journal.json"
            original_link = stock_media.os.link
            injected = False

            def inject_before_no_replace(source, destination, *args, **kwargs):
                nonlocal injected
                if destination == name and not injected:
                    injected = True
                    (directory / name).write_bytes(b"concurrent-initial")
                return original_link(source, destination, *args, **kwargs)

            try:
                with mock.patch.object(
                    stock_media.os, "link", side_effect=inject_before_no_replace,
                ):
                    with self.assertRaises(stock_media.StockMediaError):
                        stock_media._install_json(
                            descriptor, name, {"schema_version": 1}
                        )
                self.assertEqual(
                    (directory / name).read_bytes(), b"concurrent-initial"
                )
            finally:
                os.close(descriptor)

    def test_update_cas_never_overwrites_concurrent_inode_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            name = "journal.json"
            try:
                _, identity = stock_media._install_json(
                    descriptor, name, {"state": "old"}
                )
                original_rename = stock_media.os.rename
                injected = False

                def replace_before_cas(path, destination, *args, **kwargs):
                    nonlocal injected
                    if path == name and destination == "old" and not injected:
                        injected = True
                        replacement = directory / "concurrent-update"
                        replacement.write_bytes(b"concurrent-update")
                        replacement.replace(directory / name)
                    return original_rename(path, destination, *args, **kwargs)

                with mock.patch.object(
                    stock_media.os, "rename", side_effect=replace_before_cas
                ):
                    with self.assertRaises(stock_media.StockMediaError):
                        stock_media._install_json(
                            descriptor,
                            name,
                            {"state": "new"},
                            replace_identity=identity,
                        )
                self.assertEqual(
                    (directory / name).read_bytes(), b"concurrent-update"
                )
            finally:
                os.close(descriptor)

    def test_every_update_cas_checkpoint_recovers_old_or_new_record(self) -> None:
        operations = ("mkdir", "rename", "link", "unlink", "rmdir", "fsync")
        with tempfile.TemporaryDirectory() as raw:
            descriptor = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
            try:
                _, identity = stock_media._install_json(
                    descriptor, "journal.json", {"state": "old"}
                )
                originals = {
                    operation: getattr(stock_media.os, operation)
                    for operation in operations
                }
                events: list[str] = []

                def recorder(operation):
                    def record(*args, **kwargs):
                        result = originals[operation](*args, **kwargs)
                        events.append(operation)
                        return result
                    return record

                patches = [
                    mock.patch.object(
                        stock_media.os, operation, side_effect=recorder(operation)
                    )
                    for operation in operations
                ]
                for patcher in patches:
                    patcher.start()
                try:
                    stock_media._install_json(
                        descriptor,
                        "journal.json",
                        {"state": "new"},
                        replace_identity=identity,
                    )
                finally:
                    for patcher in reversed(patches):
                        patcher.stop()
            finally:
                os.close(descriptor)

        self.assertTrue(events)
        for crash_index in range(1, len(events) + 1):
            with self.subTest(checkpoint=crash_index), tempfile.TemporaryDirectory() as raw:
                directory = Path(raw)
                descriptor = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    _, identity = stock_media._install_json(
                        descriptor, "journal.json", {"state": "old"}
                    )
                    originals = {
                        operation: getattr(stock_media.os, operation)
                        for operation in operations
                    }
                    calls = 0

                    def crashing(operation):
                        def crash(*args, **kwargs):
                            nonlocal calls
                            result = originals[operation](*args, **kwargs)
                            calls += 1
                            if calls == crash_index:
                                raise SimulatedCrash()
                            return result
                        return crash

                    patches = [
                        mock.patch.object(
                            stock_media.os,
                            operation,
                            side_effect=crashing(operation),
                        )
                        for operation in operations
                    ]
                    for patcher in patches:
                        patcher.start()
                    try:
                        with self.assertRaises(SimulatedCrash):
                            stock_media._install_json(
                                descriptor,
                                "journal.json",
                                {"state": "new"},
                                replace_identity=identity,
                            )
                    finally:
                        for patcher in reversed(patches):
                            patcher.stop()

                    stock_media._recover_json_install(descriptor, "journal.json")
                    current = json.loads(
                        (directory / "journal.json").read_text()
                    )
                    if current == {"state": "old"}:
                        visible = os.stat(
                            "journal.json", dir_fd=descriptor,
                            follow_symlinks=False,
                        )
                        stock_media._install_json(
                            descriptor,
                            "journal.json",
                            {"state": "new"},
                            replace_identity=stock_media._file_identity(visible),
                        )
                    self.assertEqual(
                        json.loads((directory / "journal.json").read_text()),
                        {"state": "new"},
                    )
                    self.assertEqual(
                        list(directory.glob(".stock-json-*.cas")), []
                    )
                finally:
                    os.close(descriptor)

    def test_real_process_exit_recovers_torn_staged_cas_new_only(self) -> None:
        script = r'''
import os
import sys
from edit.hd.tools import stock_media

descriptor = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY)
_, identity = stock_media._install_json(
    descriptor, "journal.json", {"state": "old"}
)
original_write = stock_media.os.write
mode = sys.argv[2]

def hard_exit_after_torn_write(target, data):
    if mode == "half":
        original_write(target, bytes(data)[:5])
        os.fsync(target)
    os._exit(86)

stock_media.os.write = hard_exit_after_torn_write
stock_media._install_json(
    descriptor,
    "journal.json",
    {"state": "new"},
    replace_identity=identity,
)
'''
        for mode in ("open", "half"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as raw:
                completed = subprocess.run(
                    [sys.executable, "-c", script, raw, mode],
                    cwd=Path(__file__).resolve().parents[3],
                    check=False,
                )
                self.assertEqual(completed.returncode, 86)
                directory = Path(raw)
                descriptor = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    stock_media._recover_json_install(
                        descriptor, "journal.json"
                    )
                    self.assertEqual(
                        json.loads((directory / "journal.json").read_text()),
                        {"state": "old"},
                    )
                    visible = os.stat(
                        "journal.json", dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                    stock_media._install_json(
                        descriptor,
                        "journal.json",
                        {"state": "new"},
                        replace_identity=stock_media._file_identity(visible),
                    )
                finally:
                    os.close(descriptor)
                self.assertEqual(
                    json.loads((directory / "journal.json").read_text()),
                    {"state": "new"},
                )
                self.assertEqual(
                    [path for path in directory.rglob("*")
                     if path.name.endswith((".cleanup-stage", ".cas"))],
                    [],
                )

    def test_noncanonical_cas_old_is_preserved_as_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            descriptor = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
            try:
                _, identity = stock_media._install_json(
                    descriptor, "journal.json", {"state": "old"}
                )
                opened = stock_media._open_json_cas(
                    descriptor, "journal.json", create=True
                )
                self.assertIsNotNone(opened)
                cas_descriptor, _ = opened
                os.rename(
                    "journal.json", "old",
                    src_dir_fd=descriptor, dst_dir_fd=cas_descriptor,
                )
                os.close(cas_descriptor)
                cas_directory = next(directory.glob(".stock-json-*.cas"))
                old = cas_directory / "old"
                old.write_bytes(b"unrelated-noncanonical-old")
                unrelated_inode = old.stat().st_ino

                with self.assertRaises(stock_media.StockMediaError):
                    stock_media._recover_json_install(
                        descriptor, "journal.json"
                    )

                self.assertEqual(old.stat().st_ino, unrelated_inode)
                self.assertEqual(old.read_bytes(), b"unrelated-noncanonical-old")
            finally:
                os.close(descriptor)


class DownloadContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp.name).resolve()
        self.snapshot = freeze_pexels(FakeTransport(response(pexels_payload())))
        self.query_sha = self.snapshot["query_sha256"]
        self.key = stock_media.stable_idempotency_key(
            "job", "seg", "component", 1, "pexels", self.query_sha
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def download(
        self,
        transport: FakeTransport,
        *,
        snapshot: dict[str, object] | None = None,
        probe=good_probe,
        max_bytes: int = 1024,
    ) -> dict[str, object]:
        return stock_media.download_to_staging(
            self.snapshot if snapshot is None else snapshot,
            "101",
            job_dir=self.job_dir,
            idempotency_key=self.key,
            transport=transport,
            probe=probe,
            max_bytes=max_bytes,
            clock=lambda: NOW,
        )

    def test_download_streams_valid_media_into_same_directory_staging(self) -> None:
        record = self.download(
            FakeTransport(response(MP4, content_type="video/mp4"))
        )

        staging = self.job_dir / record["staging_job_path"]
        final = self.job_dir / record["planned_job_path"]
        self.assertTrue(staging.is_file())
        self.assertFalse(final.exists())
        self.assertEqual(staging.parent, final.parent)
        self.assertTrue(staging.name.startswith("."))
        self.assertEqual(record["sha256"], hashlib.sha256(MP4).hexdigest())
        self.assertEqual(record["byte_count"], len(MP4))
        self.assertEqual(oct(staging.stat().st_mode & 0o777), "0o600")
        self.assertIsInstance(record, stock_media.DownloadRecord)
        journal = self.job_dir / record["journal_job_path"]
        self.assertTrue(journal.is_file())
        journal_record = json.loads(journal.read_text())
        self.assertEqual(journal_record["state"], "complete")
        self.assertEqual(journal_record["staging_job_path"], record["staging_job_path"])
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            record.sha256 = "b" * 64

    def test_download_timestamp_is_sampled_after_probe_and_rehash(self) -> None:
        phase = "before-request"
        before = "2026-08-31T04:00:00+00:00"
        after = "2026-08-31T04:05:06+00:00"

        class PhaseTransport:
            def request(inner_self, _url, *, headers, timeout):
                nonlocal phase
                phase = "downloaded"
                return response(MP4, content_type="video/mp4")

        def phase_probe(_path: str, _kind: str) -> dict[str, object]:
            nonlocal phase
            phase = "validated"
            return {
                "media_type": "video", "format": "mp4",
                "width": 1080, "height": 1920,
            }

        record = stock_media.download_to_staging(
            self.snapshot,
            "101",
            job_dir=self.job_dir,
            idempotency_key=self.key,
            transport=PhaseTransport(),
            probe=phase_probe,
            max_bytes=1024,
            clock=lambda: after if phase == "validated" else before,
        )

        self.assertEqual(record["downloaded_at"], after)

    def test_noncanonical_clock_timestamp_leaves_only_retryable_tombstone(self) -> None:
        with self.assertRaises(stock_media.StockMediaError):
            stock_media.download_to_staging(
                self.snapshot,
                "101",
                job_dir=self.job_dir,
                idempotency_key=self.key,
                transport=FakeTransport(
                    response(MP4, content_type="video/mp4")
                ),
                probe=good_probe,
                max_bytes=1024,
                clock=lambda: "2026-08-31 04:05:06+00:00",
            )

        journals = list(self.job_dir.rglob("*.download.json"))
        self.assertEqual(len(journals), 1)
        self.assertEqual(json.loads(journals[0].read_text())["state"], "planned")
        self.assertEqual(list(self.job_dir.rglob("*.staging.mp4")), [])

    def test_complete_journal_survives_final_parent_fsync_failure(self) -> None:
        original_fsync = stock_media.os.fsync
        failed = False

        def fail_after_complete_parent_fsync(descriptor):
            nonlocal failed
            result = original_fsync(descriptor)
            if not failed:
                for path in self.job_dir.rglob("*.download.json"):
                    try:
                        state = json.loads(path.read_text())["state"]
                    except (OSError, KeyError, json.JSONDecodeError):
                        continue
                    if state == "complete":
                        failed = True
                        raise OSError("complete parent fsync failed")
            return result

        with mock.patch.object(
            stock_media.os, "fsync", side_effect=fail_after_complete_parent_fsync
        ):
            with self.assertRaises(stock_media.StockMediaError):
                self.download(
                    FakeTransport(response(MP4, content_type="video/mp4"))
                )

        replay_transport = FakeTransport()
        recovered = self.download(replay_transport)
        self.assertEqual(recovered["status"], "complete")
        self.assertEqual(replay_transport.calls, [])

    def test_complete_evidence_survives_transient_recovery_inspection_failure(self) -> None:
        original_fsync = stock_media.os.fsync
        original_read = stock_media._read_exact_json_record
        complete_fsync_failed = False
        recovery_read_failed = False

        def fail_after_complete_parent_fsync(descriptor):
            nonlocal complete_fsync_failed
            result = original_fsync(descriptor)
            if not complete_fsync_failed:
                for path in self.job_dir.rglob("*.download.json"):
                    try:
                        state = json.loads(path.read_text())["state"]
                    except (OSError, KeyError, json.JSONDecodeError):
                        continue
                    if state == "complete":
                        complete_fsync_failed = True
                        raise OSError("complete parent fsync failed")
            return result

        def fail_first_recovery_read(*args, **kwargs):
            nonlocal recovery_read_failed
            if complete_fsync_failed and not recovery_read_failed:
                recovery_read_failed = True
                raise OSError("transient recovery inspection failed")
            return original_read(*args, **kwargs)

        with mock.patch.object(
            stock_media.os, "fsync", side_effect=fail_after_complete_parent_fsync
        ), mock.patch.object(
            stock_media, "_read_exact_json_record",
            side_effect=fail_first_recovery_read,
        ):
            with self.assertRaises(stock_media.StockMediaError):
                self.download(
                    FakeTransport(response(MP4, content_type="video/mp4"))
                )

        journals = list(self.job_dir.rglob("*.download.json"))
        self.assertEqual(len(journals), 1)
        complete = json.loads(journals[0].read_text())
        self.assertEqual(complete["state"], "complete")
        self.assertTrue((self.job_dir / complete["staging_job_path"]).is_file())

        replay_transport = FakeTransport()
        recovered = self.download(replay_transport)
        self.assertEqual(recovered["status"], "complete")
        self.assertEqual(replay_transport.calls, [])

    def test_every_download_fsync_failure_recovers_on_direct_same_key_retry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            job_dir = Path(raw).resolve()
            original_fsync = stock_media.os.fsync
            clean_fsync_count = 0

            def count_fsync(descriptor):
                nonlocal clean_fsync_count
                result = original_fsync(descriptor)
                clean_fsync_count += 1
                return result

            with mock.patch.object(
                stock_media.os, "fsync", side_effect=count_fsync
            ):
                stock_media.download_to_staging(
                    self.snapshot,
                    "101",
                    job_dir=job_dir,
                    idempotency_key=self.key,
                    transport=FakeTransport(
                        response(MP4, content_type="video/mp4")
                    ),
                    probe=good_probe,
                    max_bytes=1024,
                    clock=lambda: NOW,
                )

        self.assertEqual(clean_fsync_count, 19)
        for crash_index in range(1, clean_fsync_count + 1):
            with self.subTest(fsync=crash_index), tempfile.TemporaryDirectory() as raw:
                job_dir = Path(raw).resolve()
                stock_parent = job_dir / "stock" / self.key[:2]
                stock_parent.mkdir(parents=True)
                unrelated = stock_parent / "unrelated-evidence.keep"
                unrelated.write_bytes(b"unrelated-evidence")
                original_fsync = stock_media.os.fsync
                calls = 0

                def crash_after_fsync(descriptor):
                    nonlocal calls
                    result = original_fsync(descriptor)
                    calls += 1
                    if calls == crash_index:
                        raise OSError("download fsync checkpoint")
                    return result

                with mock.patch.object(
                    stock_media.os, "fsync", side_effect=crash_after_fsync
                ):
                    with self.assertRaises(stock_media.StockMediaError):
                        stock_media.download_to_staging(
                            self.snapshot,
                            "101",
                            job_dir=job_dir,
                            idempotency_key=self.key,
                            transport=FakeTransport(
                                response(MP4, content_type="video/mp4")
                            ),
                            probe=good_probe,
                            max_bytes=1024,
                            clock=lambda: NOW,
                        )

                recovered = stock_media.download_to_staging(
                    self.snapshot,
                    "101",
                    job_dir=job_dir,
                    idempotency_key=self.key,
                    transport=FakeTransport(
                        response(MP4, content_type="video/mp4")
                    ),
                    probe=good_probe,
                    max_bytes=1024,
                    clock=lambda: NOW,
                )
                self.assertEqual(recovered["status"], "complete")
                self.assertEqual(
                    unrelated.read_bytes(), b"unrelated-evidence"
                )
                residual = [
                    path for path in job_dir.rglob("*")
                    if path.name.endswith((".cleanup-stage", ".cas"))
                ]
                self.assertEqual(residual, [])

    def test_partial_stage_retirement_failure_keeps_journal_for_retry(self) -> None:
        original_rename = stock_media.os.rename
        injected = False
        evidence_parent = self.job_dir / "stock" / self.key[:2]
        evidence_parent.mkdir(parents=True)
        unrelated = evidence_parent / "unrelated-evidence.keep"
        unrelated.write_bytes(b"unrelated-evidence")

        def fail_stage_retirement(source, destination, *args, **kwargs):
            nonlocal injected
            if (
                not injected
                and type(source) is str
                and source.endswith(".staging.mp4")
                and destination == "payload"
            ):
                injected = True
                raise OSError("cleanup stage rename failed")
            return original_rename(source, destination, *args, **kwargs)

        with mock.patch.object(
            stock_media.os, "rename", side_effect=fail_stage_retirement
        ):
            with self.assertRaises(stock_media.StockMediaError):
                self.download(FakeTransport(response(b"", status=503)))

        journal_path = next(self.job_dir.rglob("*.download.json"))
        partial = json.loads(journal_path.read_text())
        self.assertEqual(partial["state"], "partial")
        old_stage = self.job_dir / partial["staging_job_path"]
        self.assertTrue(old_stage.is_file())

        recovered = self.download(
            FakeTransport(response(MP4, content_type="video/mp4"))
        )

        self.assertFalse(old_stage.exists())
        self.assertTrue((self.job_dir / recovered["staging_job_path"]).is_file())
        self.assertEqual(unrelated.read_bytes(), b"unrelated-evidence")
        self.assertEqual(
            [path for path in self.job_dir.rglob("*")
             if path.name.endswith((".cleanup-stage", ".cas"))],
            [],
        )

    def test_partial_recovery_never_physically_retires_journal_root(self) -> None:
        old_checkpoints = (
            "journal-rename-after",
            "payload-unlink-before",
            "payload-unlink-after",
            "cleanup-stage-fsync-after",
        )
        original_remove = stock_media._remove_owned_name
        for checkpoint in old_checkpoints:
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as raw:
                job_dir = Path(raw).resolve()
                evidence_parent = job_dir / "stock" / self.key[:2]
                evidence_parent.mkdir(parents=True)
                unrelated = evidence_parent / "unrelated-evidence.keep"
                unrelated.write_bytes(b"unrelated-evidence")
                journal_retire_calls = 0

                def reject_physical_journal_retirement(parent, name, **kwargs):
                    nonlocal journal_retire_calls
                    if name.endswith(".download.json"):
                        journal_retire_calls += 1
                        raise AssertionError(
                            f"legacy journal retirement reached {checkpoint}"
                        )
                    return original_remove(parent, name, **kwargs)

                failed_transport = FakeTransport(response(b"", status=503))
                with mock.patch.object(
                    stock_media,
                    "_remove_owned_name",
                    side_effect=reject_physical_journal_retirement,
                ):
                    with self.assertRaises(stock_media.StockMediaError):
                        stock_media.download_to_staging(
                            self.snapshot,
                            "101",
                            job_dir=job_dir,
                            idempotency_key=self.key,
                            transport=failed_transport,
                            probe=good_probe,
                            max_bytes=1024,
                            clock=lambda: NOW,
                        )

                journal_path = next(job_dir.rglob("*.download.json"))
                planned = json.loads(journal_path.read_text())
                self.assertEqual(planned["state"], "planned")
                old_stage = job_dir / planned["staging_job_path"]
                self.assertFalse(old_stage.exists())
                self.assertEqual(journal_retire_calls, 0)

                retry_transport = FakeTransport(
                    response(MP4, content_type="video/mp4")
                )
                recovered = stock_media.download_to_staging(
                    self.snapshot,
                    "101",
                    job_dir=job_dir,
                    idempotency_key=self.key,
                    transport=retry_transport,
                    probe=good_probe,
                    max_bytes=1024,
                    clock=lambda: NOW,
                )

                self.assertEqual(len(failed_transport.calls), 1)
                self.assertEqual(len(retry_transport.calls), 1)
                self.assertFalse(old_stage.exists())
                self.assertTrue(
                    (job_dir / recovered["staging_job_path"]).is_file()
                )
                self.assertEqual(
                    unrelated.read_bytes(), b"unrelated-evidence"
                )
                self.assertEqual(
                    [path for path in job_dir.rglob("*")
                     if path.name.endswith((".cleanup-stage", ".cas"))],
                    [],
                )

    def test_planned_empty_stage_created_before_partial_cas_is_recovered(self) -> None:
        original_open = stock_media.os.open

        def crash_after_stage_create(path, *args, **kwargs):
            descriptor = original_open(path, *args, **kwargs)
            if type(path) is str and path.endswith(".staging.mp4"):
                os.close(descriptor)
                raise SimulatedCrash()
            return descriptor

        with mock.patch.object(
            stock_media.os, "open", side_effect=crash_after_stage_create
        ):
            with self.assertRaises(SimulatedCrash):
                self.download(
                    FakeTransport(response(MP4, content_type="video/mp4"))
                )

        journal = json.loads(next(self.job_dir.rglob("*.download.json")).read_text())
        self.assertEqual(journal["state"], "planned")
        old_stage = self.job_dir / journal["staging_job_path"]
        self.assertTrue(old_stage.is_file())
        self.assertEqual(old_stage.stat().st_size, 0)

        recovered = self.download(
            FakeTransport(response(MP4, content_type="video/mp4"))
        )

        self.assertFalse(old_stage.exists())
        self.assertTrue((self.job_dir / recovered["staging_job_path"]).is_file())
        self.assertEqual(
            [path for path in self.job_dir.rglob("*")
             if path.name.endswith((".cleanup-stage", ".cas"))],
            [],
        )

    def test_planned_stage_unrelated_variants_are_preserved_as_conflicts(self) -> None:
        variants = ("nonempty", "permissions", "hardlink", "fifo")
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as raw:
                job_dir = Path(raw).resolve()
                original_open = stock_media.os.open

                def crash_after_stage_create(path, *args, **kwargs):
                    descriptor = original_open(path, *args, **kwargs)
                    if type(path) is str and path.endswith(".staging.mp4"):
                        os.close(descriptor)
                        raise SimulatedCrash()
                    return descriptor

                with mock.patch.object(
                    stock_media.os, "open", side_effect=crash_after_stage_create
                ):
                    with self.assertRaises(SimulatedCrash):
                        stock_media.download_to_staging(
                            self.snapshot,
                            "101",
                            job_dir=job_dir,
                            idempotency_key=self.key,
                            transport=FakeTransport(
                                response(MP4, content_type="video/mp4")
                            ),
                            probe=good_probe,
                            max_bytes=1024,
                            clock=lambda: NOW,
                        )
                journal = json.loads(
                    next(job_dir.rglob("*.download.json")).read_text()
                )
                stage = job_dir / journal["staging_job_path"]
                if variant == "nonempty":
                    stage.write_bytes(b"unrelated")
                elif variant == "permissions":
                    stage.chmod(0o644)
                elif variant == "hardlink":
                    os.link(stage, stage.with_name("additional-hardlink"))
                else:
                    stage.unlink()
                    os.mkfifo(stage)
                transport = FakeTransport()

                with self.assertRaises(stock_media.StockMediaError):
                    stock_media.download_to_staging(
                        self.snapshot,
                        "101",
                        job_dir=job_dir,
                        idempotency_key=self.key,
                        transport=transport,
                        probe=good_probe,
                        max_bytes=1024,
                        clock=lambda: NOW,
                    )

                self.assertEqual(transport.calls, [])
                self.assertTrue(stage.exists())

    def test_planned_empty_stage_concurrent_replacement_preserves_replacement_inode(self) -> None:
        original_open = stock_media.os.open

        def crash_after_stage_create(path, *args, **kwargs):
            descriptor = original_open(path, *args, **kwargs)
            if type(path) is str and path.endswith(".staging.mp4"):
                os.close(descriptor)
                raise SimulatedCrash()
            return descriptor

        with mock.patch.object(
            stock_media.os, "open", side_effect=crash_after_stage_create
        ):
            with self.assertRaises(SimulatedCrash):
                self.download(
                    FakeTransport(response(MP4, content_type="video/mp4"))
                )
        journal = json.loads(next(self.job_dir.rglob("*.download.json")).read_text())
        stage = self.job_dir / journal["staging_job_path"]
        stage_name = stage.name
        original_rename = stock_media.os.rename
        replacement_inode = None

        def replace_before_cleanup(source, destination, *args, **kwargs):
            nonlocal replacement_inode
            if source == stage_name and destination == "payload":
                parent = kwargs["src_dir_fd"]
                original_rename(
                    source, ".owned-planned-away",
                    src_dir_fd=parent, dst_dir_fd=parent,
                )
                descriptor = os.open(
                    source, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600, dir_fd=parent,
                )
                os.close(descriptor)
                replacement_inode = os.stat(
                    source, dir_fd=parent, follow_symlinks=False
                ).st_ino
            return original_rename(source, destination, *args, **kwargs)

        with mock.patch.object(
            stock_media.os, "rename", side_effect=replace_before_cleanup
        ):
            with self.assertRaises(stock_media.StockMediaError):
                self.download(FakeTransport())

        self.assertIsNotNone(replacement_inode)
        evidence_inodes = {
            path.stat().st_ino for path in stage.parent.rglob("*")
            if path.is_file()
        }
        self.assertIn(replacement_inode, evidence_inodes)

    def test_probe_is_validated_before_any_transport_or_staging(self) -> None:
        transport = FakeTransport(response(MP4, content_type="video/mp4"))

        with self.assertRaises(stock_media.StockMediaError):
            stock_media.download_to_staging(
                self.snapshot,
                "101",
                job_dir=self.job_dir,
                idempotency_key=self.key,
                transport=transport,
                probe=None,
                max_bytes=1024,
                clock=lambda: NOW,
            )

        self.assertEqual(transport.calls, [])
        self.assertFalse((self.job_dir / "stock").exists())

    def test_all_local_parameters_are_rejected_before_transport(self) -> None:
        cases = (
            {"idempotency_key": "bad"},
            {"max_bytes": True},
            {"max_redirects": True},
            {"clock": object()},
            {"transport": object()},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                transport = FakeTransport(
                    response(MP4, content_type="video/mp4")
                )
                arguments = {
                    "job_dir": self.job_dir,
                    "idempotency_key": self.key,
                    "transport": transport,
                    "probe": good_probe,
                    "max_bytes": 1024,
                    "max_redirects": 2,
                    "clock": lambda: NOW,
                }
                arguments.update(changes)
                with self.assertRaises(stock_media.StockMediaError):
                    stock_media.download_to_staging(
                        self.snapshot, "101", **arguments
                    )
                self.assertEqual(transport.calls, [])

    def test_rejects_initial_urls_outside_provider_contract_before_transport(self) -> None:
        mismatched_urls = (
            "http://videos.pexels.com/a.mp4",
            "https://evil.example/a.mp4",
            "https://user@videos.pexels.com/a.mp4",
            "https://127.0.0.1/a.mp4",
            "https://videos.pexels.com:444/a.mp4",
            "https://videos%2epexels.com/a.mp4",
            "https://videos.pexels.com/a%2f..%2fb.mp4",
            "https://videos.pexels.com\\@evil.example/a.mp4",
        )
        for mismatched_url in mismatched_urls:
            with self.subTest(url=mismatched_url):
                raw = json.loads(pexels_payload(url=mismatched_url))
                raw["videos"][0]["video_files"] = raw["videos"][0][
                    "video_files"
                ][-1:]
                with self.assertRaises(stock_media.StockMediaError):
                    freeze_pexels(
                        FakeTransport(response(json.dumps(raw).encode()))
                    )

    def test_rejects_scheme_relative_or_unapproved_provider_redirects(self) -> None:
        for location in ("//videos.pexels.com/next.mp4", "https://evil.example/next.mp4"):
            with self.subTest(location=location):
                transport = FakeTransport(
                    response(
                        b"",
                        status=302,
                        content_type="text/plain",
                        headers={"Location": location},
                    )
                )
                with self.assertRaises(stock_media.StockMediaError):
                    self.download(transport)
                self.assertEqual(len(transport.calls), 1)

    def test_rejects_too_many_redirects(self) -> None:
        redirect = response(
            b"",
            status=302,
            content_type="text/plain",
            headers={"Location": "https://videos.pexels.com/next.mp4"},
        )
        transport = FakeTransport(redirect, redirect, redirect)
        with self.assertRaises(stock_media.StockMediaError):
            self.download(transport)

    def test_redirect_loop_is_bounded_and_rejected(self) -> None:
        first = response(
            b"",
            status=302,
            content_type="text/plain",
            headers={"Location": "https://videos.pexels.com/two.mp4"},
        )
        second = response(
            b"",
            status=302,
            content_type="text/plain",
            headers={"Location": "https://videos.pexels.com/one.mp4"},
        )
        transport = FakeTransport(first, second, first)

        with self.assertRaises(stock_media.StockMediaError):
            self.download(transport)

        self.assertLessEqual(len(transport.calls), 3)

    def test_content_length_must_match_stream_but_may_be_absent(self) -> None:
        lying = response(
            MP4,
            content_type="video/mp4",
            headers={"Content-Length": "1"},
        )
        with self.assertRaises(stock_media.StockMediaError):
            self.download(FakeTransport(lying))

        record = self.download(
            FakeTransport(response(MP4, content_type="video/mp4"))
        )
        self.assertEqual(record["byte_count"], len(MP4))

    def test_chunk_exception_is_bounded_and_removes_staging(self) -> None:
        exploding = stock_media.TransportResponse(
            200, {"Content-Type": "video/mp4"}, ExplodingBody()
        )

        with self.assertRaises(stock_media.StockMediaError) as caught:
            self.download(FakeTransport(exploding))

        self.assertNotIn(REQUEST_ONLY_VALUE, str(caught.exception))
        self.assertEqual(list(self.job_dir.rglob("*.staging.mp4")), [])
        journals = list(self.job_dir.rglob("*.download.json"))
        self.assertEqual(len(journals), 1)
        self.assertEqual(json.loads(journals[0].read_text())["state"], "planned")

    def test_mime_extension_size_magic_and_probe_stop_explicitly(self) -> None:
        cases = (
            (response(MP4, content_type="image/jpeg"), good_probe, 1024),
            (response(MP4, content_type="video/mp4"), good_probe, len(MP4) - 1),
            (response(b"not-media", content_type="video/mp4"), good_probe, 1024),
            (
                response(MP4, content_type="video/mp4"),
                lambda _path, _kind: (_ for _ in ()).throw(RuntimeError("ffprobe failed")),
                1024,
            ),
            (
                response(MP4, content_type="video/mp4"),
                lambda _path, _kind: {
                    "media_type": "image", "format": "jpeg",
                    "width": 1080, "height": 1920,
                },
                1024,
            ),
        )
        for provider_response, probe, limit in cases:
            with self.subTest(response=provider_response, limit=limit):
                with self.assertRaises(stock_media.StockMediaError):
                    self.download(FakeTransport(provider_response), probe=probe, max_bytes=limit)
                self.assertEqual(list(self.job_dir.rglob("*.mp4")), [])

    def test_extension_must_match_declared_mime(self) -> None:
        raw = json.loads(
            pexels_payload(
                url="https://videos.pexels.com/video-files/101/not-video.jpg"
            )
        )
        raw["videos"][0]["video_files"] = raw["videos"][0]["video_files"][-1:]
        with self.assertRaises(stock_media.StockMediaError):
            freeze_pexels(
                FakeTransport(
                    response(
                        json.dumps(raw).encode()
                    )
                )
            )

    def test_image_download_uses_image_mime_magic_and_probe_contract(self) -> None:
        snapshot = freeze_pexels(
            FakeTransport(response(pexels_photo_payload())), media_type="image"
        )
        key = stock_media.stable_idempotency_key(
            "job", "seg", "image-component", 1, "pexels", snapshot["query_sha256"]
        )

        record = stock_media.download_to_staging(
            snapshot,
            "303",
            job_dir=self.job_dir,
            idempotency_key=key,
            transport=FakeTransport(response(JPEG, content_type="image/jpeg")),
            probe=lambda _path, _kind: {
                "media_type": "image", "format": "jpeg",
                "width": 1080, "height": 1920,
            },
            max_bytes=1024,
            clock=lambda: NOW,
        )

        self.assertEqual(record["media_type"], "image")
        self.assertEqual(record["format"], "jpeg")
        self.assertTrue((self.job_dir / record["staging_job_path"]).is_file())

    def test_exact_video_and_image_variants_reject_probed_dimension_mismatch(self) -> None:
        with self.assertRaises(stock_media.StockMediaError):
            self.download(
                FakeTransport(response(MP4, content_type="video/mp4")),
                probe=lambda _path, _kind: {
                    "media_type": "video", "format": "mp4",
                    "width": 640, "height": 360,
                },
            )

        image_snapshot = freeze_pexels(
            FakeTransport(response(pexels_photo_payload())), media_type="image"
        )
        image_key = stock_media.stable_idempotency_key(
            "job", "seg", "low-resolution-image", 1, "pexels",
            image_snapshot["query_sha256"],
        )
        with self.assertRaises(stock_media.StockMediaError):
            stock_media.download_to_staging(
                image_snapshot,
                "303",
                job_dir=self.job_dir,
                idempotency_key=image_key,
                transport=FakeTransport(
                    response(JPEG, content_type="image/jpeg")
                ),
                probe=lambda _path, _kind: {
                    "media_type": "image", "format": "jpeg",
                    "width": 640, "height": 360,
                },
                max_bytes=1024,
                clock=lambda: NOW,
            )

    def test_declared_pixabay_large_dimensions_are_frozen_from_probe(self) -> None:
        payload = json.loads(pixabay_image_payload())
        hit = payload["hits"][0]
        for field in ("webformatURL", "webformatWidth", "webformatHeight"):
            hit.pop(field)
        hit["largeImageURL"] = "https://pixabay.com/get/photo_1280.jpg"
        snapshot = stock_media.freeze_search_snapshot(
            "pixabay",
            "city skyline",
            media_type="image",
            api_key=REQUEST_ONLY_VALUE,
            transport=FakeTransport(
                response(json.dumps(payload, separators=(",", ":")).encode())
            ),
            clock=lambda: NOW,
        )
        self.assertEqual(
            snapshot["candidates"][0]["dimensions_source"],
            "provider_declared",
        )
        key = stock_media.stable_idempotency_key(
            "job", "seg", "pixabay-large", 1, "pixabay",
            snapshot["query_sha256"],
        )

        record = stock_media.download_to_staging(
            snapshot,
            "404",
            job_dir=self.job_dir,
            idempotency_key=key,
            transport=FakeTransport(response(JPEG, content_type="image/jpeg")),
            probe=lambda _path, _kind: {
                "media_type": "image", "format": "jpeg",
                "width": 1280, "height": 720,
            },
            max_bytes=1024,
            clock=lambda: NOW,
        )

        self.assertEqual(record["actual_width"], 1280)
        self.assertEqual(record["actual_height"], 720)
        self.assertEqual(record["dimensions_source"], "probe")
        journal = json.loads(
            (self.job_dir / record["journal_job_path"]).read_text()
        )
        self.assertEqual(journal["actual_width"], 1280)
        self.assertEqual(journal["actual_height"], 720)
        self.assertEqual(journal["dimensions_source"], "probe")

    def test_declared_pixabay_large_requires_probe_dimensions(self) -> None:
        payload = json.loads(pixabay_image_payload())
        hit = payload["hits"][0]
        for field in ("webformatURL", "webformatWidth", "webformatHeight"):
            hit.pop(field)
        snapshot = stock_media.freeze_search_snapshot(
            "pixabay",
            "city skyline",
            media_type="image",
            api_key=REQUEST_ONLY_VALUE,
            transport=FakeTransport(response(json.dumps(payload).encode())),
            clock=lambda: NOW,
        )
        key = stock_media.stable_idempotency_key(
            "job", "seg", "pixabay-large-missing", 1, "pixabay",
            snapshot["query_sha256"],
        )

        with self.assertRaises(stock_media.StockMediaError):
            stock_media.download_to_staging(
                snapshot,
                "404",
                job_dir=self.job_dir,
                idempotency_key=key,
                transport=FakeTransport(
                    response(JPEG, content_type="image/jpeg")
                ),
                probe=lambda _path, _kind: {
                    "media_type": "image", "format": "jpeg"
                },
                max_bytes=1024,
                clock=lambda: NOW,
            )

        journals = list(self.job_dir.rglob("*.download.json"))
        self.assertEqual(len(journals), 1)
        self.assertEqual(json.loads(journals[0].read_text())["state"], "planned")

    def test_staging_never_follows_symlinked_job_components(self) -> None:
        outside = self.job_dir / "outside"
        outside.mkdir()
        (self.job_dir / "stock").symlink_to(outside, target_is_directory=True)

        with self.assertRaises(stock_media.StockMediaError):
            self.download(FakeTransport(response(MP4, content_type="video/mp4")))

        self.assertEqual(list(outside.iterdir()), [])

    def test_probe_same_inode_mutation_is_rejected_even_if_content_and_mtime_restore(self) -> None:
        original_mtime: int | None = None

        def mutate_and_restore(path: str, _kind: str) -> dict[str, object]:
            nonlocal original_mtime
            media = Path(path)
            original_mtime = media.stat().st_mtime_ns
            original = media.read_bytes()
            media.write_bytes(MP4 + b"temporary mutation")
            media.write_bytes(original)
            os.utime(media, ns=(original_mtime, original_mtime))
            return good_probe(path, _kind)

        with self.assertRaises(stock_media.StockMediaError):
            self.download(
                FakeTransport(response(MP4, content_type="video/mp4")),
                probe=mutate_and_restore,
            )

        self.assertIsNotNone(original_mtime)

    def test_root_detach_during_probe_is_rejected_without_returning_record(self) -> None:
        original = self.job_dir.with_name(self.job_dir.name + "-original")
        outside = self.job_dir.with_name(self.job_dir.name + "-outside")

        def detach(_path: str, _kind: str) -> dict[str, object]:
            self.job_dir.rename(original)
            outside.mkdir()
            self.job_dir.symlink_to(outside, target_is_directory=True)
            return good_probe(_path, _kind)

        try:
            with self.assertRaises(stock_media.StockMediaError):
                self.download(
                    FakeTransport(response(MP4, content_type="video/mp4")),
                    probe=detach,
                )
        finally:
            if self.job_dir.is_symlink():
                self.job_dir.unlink()
            if original.exists():
                original.rename(self.job_dir)
            if outside.exists():
                outside.rmdir()

    def test_root_detach_during_external_request_is_rejected(self) -> None:
        original = self.job_dir.with_name(self.job_dir.name + "-original")
        outside = self.job_dir.with_name(self.job_dir.name + "-outside")

        class DetachingTransport:
            def request(inner_self, _url, *, headers, timeout):
                self.job_dir.rename(original)
                outside.mkdir()
                self.job_dir.symlink_to(outside, target_is_directory=True)
                return response(MP4, content_type="video/mp4")

        try:
            with self.assertRaises(stock_media.StockMediaError):
                self.download(DetachingTransport())
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            if self.job_dir.is_symlink():
                self.job_dir.unlink()
            if original.exists():
                original.rename(self.job_dir)
            if outside.exists():
                outside.rmdir()

    def test_probe_path_replacement_is_rejected_and_replacement_is_preserved(self) -> None:
        replacement_bytes = MP4 + b"replacement"
        captured: list[Path] = []

        def replace(path: str, _kind: str) -> dict[str, object]:
            media = Path(path)
            owned = media.with_name("owned-detached.mp4")
            media.rename(owned)
            media.write_bytes(replacement_bytes)
            captured.extend((owned, media))
            return good_probe(path, _kind)

        with self.assertRaises(stock_media.StockMediaError):
            self.download(
                FakeTransport(response(MP4, content_type="video/mp4")),
                probe=replace,
            )

        self.assertEqual(captured[1].read_bytes(), replacement_bytes)
        self.assertEqual(captured[0].read_bytes(), MP4)

    def test_complete_journal_replay_is_zero_network_and_deterministic(self) -> None:
        first = self.download(
            FakeTransport(response(MP4, content_type="video/mp4"))
        )
        replay_transport = FakeTransport()

        second = stock_media.download_to_staging(
            self.snapshot,
            "101",
            job_dir=self.job_dir,
            idempotency_key=self.key,
            transport=replay_transport,
            probe=good_probe,
            max_bytes=1024,
            clock=lambda: (_ for _ in ()).throw(
                RuntimeError("replay clock must not run")
            ),
        )

        self.assertEqual(second, first)
        self.assertEqual(replay_transport.calls, [])

    def test_equivalent_noncanonical_complete_journal_is_rejected(self) -> None:
        first = self.download(
            FakeTransport(response(MP4, content_type="video/mp4"))
        )
        journal = self.job_dir / first["journal_job_path"]
        parsed = json.loads(journal.read_text())
        journal.write_text(json.dumps(parsed, indent=2) + "\n")
        transport = FakeTransport()

        with self.assertRaises(stock_media.StockMediaError):
            self.download(transport)

        self.assertEqual(transport.calls, [])
        self.assertTrue(journal.is_file())

    def test_fifo_journal_and_staging_are_rejected_before_open(self) -> None:
        journal = self.job_dir / f"stock/{self.key[:2]}/{self.key}.download.json"
        journal.parent.mkdir(parents=True)
        os.mkfifo(journal)
        original_open = stock_media.os.open
        opened_fifo = False
        blocked_names = {journal.name}

        def reject_fifo_open(path, *args, **kwargs):
            nonlocal opened_fifo
            if path in blocked_names:
                opened_fifo = True
                raise AssertionError("FIFO must be rejected before open")
            return original_open(path, *args, **kwargs)

        with mock.patch.object(stock_media.os, "open", side_effect=reject_fifo_open):
            with self.assertRaises(stock_media.StockMediaError):
                self.download(FakeTransport())
        self.assertFalse(opened_fifo)

        journal.unlink()
        staged = self.download(
            FakeTransport(response(MP4, content_type="video/mp4"))
        )
        stage = self.job_dir / staged["staging_job_path"]
        stage.unlink()
        os.mkfifo(stage)
        blocked_names = {stage.name}
        opened_fifo = False
        with mock.patch.object(stock_media.os, "open", side_effect=reject_fifo_open):
            with self.assertRaises(stock_media.StockMediaError):
                stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=self.job_dir,
                    idempotency_key=self.key,
                )
        self.assertFalse(opened_fifo)

    def test_planned_and_partial_crash_journals_recover_without_scanning(self) -> None:
        original_open = stock_media.os.open

        def crash_before_stage(path, *args, **kwargs):
            if type(path) is str and path.endswith(".staging.mp4"):
                raise SimulatedCrash()
            return original_open(path, *args, **kwargs)

        with mock.patch.object(stock_media.os, "open", side_effect=crash_before_stage):
            with self.assertRaises(SimulatedCrash):
                self.download(
                    FakeTransport(response(MP4, content_type="video/mp4"))
                )
        planned = next(self.job_dir.rglob("*.download.json"))
        self.assertEqual(json.loads(planned.read_text())["state"], "planned")

        recovered = self.download(
            FakeTransport(response(MP4, content_type="video/mp4"))
        )
        self.assertTrue((self.job_dir / recovered["staging_job_path"]).is_file())

        second_dir = Path(tempfile.mkdtemp(dir=self.temp.name)).resolve()
        second_key = stock_media.stable_idempotency_key(
            "job-2", "seg", "component", 1, "pexels", self.query_sha
        )
        with self.assertRaises(SimulatedCrash):
            stock_media.download_to_staging(
                self.snapshot,
                "101",
                job_dir=second_dir,
                idempotency_key=second_key,
                transport=FakeTransport(SimulatedCrash()),
                probe=good_probe,
                max_bytes=1024,
                clock=lambda: NOW,
            )
        partial = next(second_dir.rglob("*.download.json"))
        self.assertEqual(json.loads(partial.read_text())["state"], "partial")
        retried = stock_media.download_to_staging(
            self.snapshot,
            "101",
            job_dir=second_dir,
            idempotency_key=second_key,
            transport=FakeTransport(response(MP4, content_type="video/mp4")),
            probe=good_probe,
            max_bytes=1024,
            clock=lambda: NOW,
        )
        self.assertTrue((second_dir / retried["staging_job_path"]).is_file())


class PublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp.name).resolve()
        self.snapshot = freeze_pexels(FakeTransport(response(pexels_payload())))
        self.key = stock_media.stable_idempotency_key(
            "job", "seg", "component", 1, "pexels", self.snapshot["query_sha256"]
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def staged(self) -> dict[str, object]:
        return stock_media.download_to_staging(
            self.snapshot,
            "101",
            job_dir=self.job_dir,
            idempotency_key=self.key,
            transport=FakeTransport(response(MP4, content_type="video/mp4")),
            probe=good_probe,
            max_bytes=1024,
            clock=lambda: NOW,
        )

    def hard_exit_during_license_stage(self, job_dir: Path, mode: str) -> None:
        script = r'''
import os
import sys
from edit.hd.tools import stock_media
from edit.hd.tests.test_stock_media import (
    FakeTransport, MP4, NOW, freeze_pexels, good_probe,
    pexels_payload, response,
)

job_dir = sys.argv[1]
mode = sys.argv[2]
snapshot = freeze_pexels(FakeTransport(response(pexels_payload())))
key = stock_media.stable_idempotency_key(
    "job", "seg", "component", 1, "pexels", snapshot["query_sha256"]
)
record = stock_media.download_to_staging(
    snapshot,
    "101",
    job_dir=job_dir,
    idempotency_key=key,
    transport=FakeTransport(response(MP4, content_type="video/mp4")),
    probe=good_probe,
    max_bytes=1024,
    clock=lambda: NOW,
)
original = stock_media._write_staged_json

def hard_exit_staged_write(parent, name, value, *, temporary_name=None):
    if temporary_name and temporary_name.endswith(".license.staging.json"):
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
        if mode == "half":
            data = stock_media._canonical_bytes(value) + b"\n"
            os.write(descriptor, data[: len(data) // 2])
            os.fsync(descriptor)
        os._exit(87)
    return original(
        parent, name, value, temporary_name=temporary_name
    )

stock_media._write_staged_json = hard_exit_staged_write
stock_media.publish_frozen_asset(
    snapshot,
    "101",
    record,
    job_dir=job_dir,
    idempotency_key=key,
)
'''
        completed = subprocess.run(
            [sys.executable, "-c", script, str(job_dir), mode],
            cwd=Path(__file__).resolve().parents[3],
            check=False,
        )
        self.assertEqual(completed.returncode, 87)

    def replay_download_record(self, job_dir: Path) -> stock_media.DownloadRecord:
        transport = FakeTransport()
        record = stock_media.download_to_staging(
            self.snapshot,
            "101",
            job_dir=job_dir,
            idempotency_key=self.key,
            transport=transport,
            probe=good_probe,
            max_bytes=1024,
            clock=lambda: (_ for _ in ()).throw(
                AssertionError("published replay must not call clock")
            ),
        )
        self.assertEqual(transport.calls, [])
        return record

    def test_real_process_exit_recovers_empty_or_prefix_license_stage(self) -> None:
        for mode in ("open", "half"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as raw:
                job_dir = Path(raw).resolve()
                self.hard_exit_during_license_stage(job_dir, mode)
                partial = next(job_dir.rglob("*.license.staging.json"))
                self.assertTrue(partial.is_file())

                binding = stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    self.replay_download_record(job_dir),
                    job_dir=job_dir,
                    idempotency_key=self.key,
                )

                self.assertTrue((job_dir / binding["job_path"]).is_file())
                self.assertFalse(partial.exists())
                self.assertEqual(
                    [path for path in job_dir.rglob("*")
                     if path.name.endswith((".cleanup-stage", ".cas"))],
                    [],
                )

    def test_torn_license_unrelated_variants_are_preserved(self) -> None:
        for variant in ("nonprefix", "permissions", "hardlink", "fifo"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as raw:
                job_dir = Path(raw).resolve()
                self.hard_exit_during_license_stage(job_dir, "half")
                partial = next(job_dir.rglob("*.license.staging.json"))
                linked = partial.with_name("additional-license-hardlink")
                if variant == "nonprefix":
                    partial.write_bytes(b"unrelated-nonprefix-license")
                elif variant == "permissions":
                    partial.chmod(0o644)
                elif variant == "hardlink":
                    os.link(partial, linked)
                else:
                    partial.unlink()
                    os.mkfifo(partial)
                unrelated_inode = partial.stat().st_ino

                with self.assertRaises(stock_media.StockMediaError):
                    stock_media.publish_frozen_asset(
                        self.snapshot,
                        "101",
                        self.replay_download_record(job_dir),
                        job_dir=job_dir,
                        idempotency_key=self.key,
                    )

                self.assertEqual(partial.stat().st_ino, unrelated_inode)
                if variant == "nonprefix":
                    self.assertEqual(
                        partial.read_bytes(), b"unrelated-nonprefix-license"
                    )
                elif variant == "permissions":
                    self.assertEqual(stat.S_IMODE(partial.stat().st_mode), 0o644)
                elif variant == "hardlink":
                    self.assertTrue(linked.is_file())
                else:
                    self.assertTrue(stat.S_ISFIFO(partial.lstat().st_mode))

    def test_publish_writes_asset_and_independent_filtered_license_snapshot(self) -> None:
        record = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            self.staged(),
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )

        expected = {
            "provider",
            "provider_asset_id",
            "author",
            "asset_page",
            "job_path",
            "license_snapshot",
            "downloaded_at",
            "sha256",
        }
        self.assertEqual(set(record), expected)
        media_path = self.job_dir / record["job_path"]
        license_path = self.job_dir / record["license_snapshot"]
        self.assertTrue(media_path.is_file())
        self.assertTrue(license_path.is_file())
        self.assertNotEqual(media_path, license_path)
        license_record = json.loads(license_path.read_text())
        self.assertEqual(license_record["license_version"], "pexels-license-v1")
        self.assertEqual(license_record["byte_count"], len(MP4))
        self.assertEqual(license_record["sha256"], hashlib.sha256(MP4).hexdigest())
        serialized = json.dumps(record, sort_keys=True) + license_path.read_text()
        for forbidden in (
            REQUEST_ONLY_VALUE,
            "Authorization",
            "Cookie",
            "download_url",
            "headers",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn("?", license_record["asset_page"])
        receipt = json.loads(
            (self.job_dir / self.staged_path_for_key()).read_text()
        )
        self.assertEqual(receipt["state"], "published")
        self.assertEqual(receipt["sha256"], record["sha256"])
        self.assertRegex(receipt["license_sha256"], r"^[0-9a-f]{64}$")

    def staged_path_for_key(self) -> str:
        return f"stock/{self.key[:2]}/{self.key}.download.json"

    def test_identical_publish_replays_without_overwrite(self) -> None:
        first = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            self.staged(),
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )
        before = (self.job_dir / first["job_path"]).stat()

        second = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            None,
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )

        after = (self.job_dir / first["job_path"]).stat()
        self.assertEqual(second, first)
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))

    def test_full_acquire_replays_published_receipt_with_zero_network(self) -> None:
        first_download = self.staged()
        first_binding = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            first_download,
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )
        before = {
            path.relative_to(self.job_dir).as_posix(): (
                path.stat().st_ino,
                path.read_bytes(),
            )
            for path in self.job_dir.rglob("*")
            if path.is_file()
        }
        replay_transport = FakeTransport()

        replay_download = stock_media.download_to_staging(
            self.snapshot,
            "101",
            job_dir=self.job_dir,
            idempotency_key=self.key,
            transport=replay_transport,
            probe=good_probe,
            max_bytes=1024,
            clock=lambda: (_ for _ in ()).throw(
                RuntimeError("published replay clock must not run")
            ),
        )
        replay_binding = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            replay_download,
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )

        after = {
            path.relative_to(self.job_dir).as_posix(): (
                path.stat().st_ino,
                path.read_bytes(),
            )
            for path in self.job_dir.rglob("*")
            if path.is_file()
        }
        self.assertEqual(replay_download["status"], "published")
        self.assertEqual(replay_transport.calls, [])
        self.assertEqual(replay_binding, first_binding)
        self.assertEqual(after, before)

    def test_published_receipt_conflicts_with_changed_snapshot_before_network(self) -> None:
        stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            self.staged(),
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )
        changed = freeze_pexels(
            FakeTransport(response(pexels_payload(candidate_id=102)))
        )
        changed_query = freeze_pexels(
            FakeTransport(response(pexels_payload())), query="different query"
        )
        for frozen, candidate_id in ((changed, "102"), (changed_query, "101")):
            with self.subTest(candidate_id=candidate_id, query=frozen["query"]):
                transport = FakeTransport()
                with self.assertRaisesRegex(
                    stock_media.StockMediaError, "conflict"
                ):
                    stock_media.download_to_staging(
                        frozen,
                        candidate_id,
                        job_dir=self.job_dir,
                        idempotency_key=self.key,
                        transport=transport,
                        probe=good_probe,
                        max_bytes=1024,
                        clock=lambda: NOW,
                    )
                self.assertEqual(transport.calls, [])

    def test_equivalent_noncanonical_receipt_or_license_bytes_are_rejected(self) -> None:
        published = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            self.staged(),
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )
        receipt_path = self.job_dir / self.staged_path_for_key()
        receipt = json.loads(receipt_path.read_text())
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        transport = FakeTransport()
        with self.assertRaises(stock_media.StockMediaError):
            stock_media.download_to_staging(
                self.snapshot,
                "101",
                job_dir=self.job_dir,
                idempotency_key=self.key,
                transport=transport,
                probe=good_probe,
                max_bytes=1024,
                clock=lambda: NOW,
            )
        self.assertEqual(transport.calls, [])

        receipt_path.write_bytes(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )
        license_path = self.job_dir / published["license_snapshot"]
        license_record = json.loads(license_path.read_text())
        license_path.write_text(json.dumps(license_record, indent=2) + "\n")
        with self.assertRaises(stock_media.StockMediaError):
            stock_media.publish_frozen_asset(
                self.snapshot,
                "101",
                None,
                job_dir=self.job_dir,
                idempotency_key=self.key,
            )

    def test_changed_candidate_under_same_key_conflicts_instead_of_reusing_asset(self) -> None:
        stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            self.staged(),
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )
        changed = freeze_pexels(
            FakeTransport(response(pexels_payload(candidate_id=102)))
        )

        with self.assertRaisesRegex(stock_media.StockMediaError, "conflict"):
            stock_media.publish_frozen_asset(
                changed,
                "102",
                None,
                job_dir=self.job_dir,
                idempotency_key=self.key,
            )

    def test_existing_destination_is_never_overwritten(self) -> None:
        staged = self.staged()
        final = self.job_dir / staged["planned_job_path"]
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"existing")

        with self.assertRaises(stock_media.StockMediaError):
            stock_media.publish_frozen_asset(
                self.snapshot,
                "101",
                staged,
                job_dir=self.job_dir,
                idempotency_key=self.key,
            )

        self.assertEqual(final.read_bytes(), b"existing")

    def test_hardlinked_staging_is_rejected_without_partial_publish(self) -> None:
        staged = self.staged()
        staging_path = self.job_dir / staged["staging_job_path"]
        os.link(staging_path, self.job_dir / "additional-link")

        with self.assertRaises(stock_media.StockMediaError):
            stock_media.publish_frozen_asset(
                self.snapshot,
                "101",
                staged,
                job_dir=self.job_dir,
                idempotency_key=self.key,
            )

        self.assertFalse((self.job_dir / staged["planned_job_path"]).exists())

    def test_missing_or_modified_journal_rejects_record_and_preserves_staging(self) -> None:
        for mode in ("missing", "nonconforming"):
            with self.subTest(mode=mode):
                if mode == "nonconforming":
                    self.tearDown()
                    self.setUp()
                staged = self.staged()
                staging_path = self.job_dir / staged["staging_job_path"]
                journal_path = self.job_dir / staged["journal_job_path"]
                if mode == "missing":
                    journal_path.unlink()
                else:
                    journal = json.loads(journal_path.read_text())
                    journal["Authorization"] = REQUEST_ONLY_VALUE
                    journal_path.write_text(json.dumps(journal))

                with self.assertRaises(stock_media.StockMediaError) as caught:
                    stock_media.publish_frozen_asset(
                        self.snapshot,
                        "101",
                        staged,
                        job_dir=self.job_dir,
                        idempotency_key=self.key,
                    )

                self.assertNotIn(REQUEST_ONLY_VALUE, str(caught.exception))
                self.assertTrue(staging_path.exists())

    def test_nonconforming_license_is_not_accepted_as_idempotent_replay(self) -> None:
        published = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            self.staged(),
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )
        license_path = self.job_dir / published["license_snapshot"]
        nonconforming = json.loads(license_path.read_text())
        nonconforming["Authorization"] = REQUEST_ONLY_VALUE
        license_path.write_text(json.dumps(nonconforming))

        with self.assertRaises(stock_media.StockMediaError) as caught:
            stock_media.publish_frozen_asset(
                self.snapshot,
                "101",
                None,
                job_dir=self.job_dir,
                idempotency_key=self.key,
            )

        self.assertNotIn(REQUEST_ONLY_VALUE, str(caught.exception))
        self.assertIn(REQUEST_ONLY_VALUE, license_path.read_text())

    def test_same_key_concurrent_publish_is_idempotent_and_cleans_loser_staging(self) -> None:
        records = [self.staged(), self.staged()]
        barrier = threading.Barrier(2)
        results: list[dict[str, object]] = []
        failures: list[BaseException] = []

        def run(record: dict[str, object]) -> None:
            try:
                barrier.wait()
                results.append(
                    stock_media.publish_frozen_asset(
                        self.snapshot,
                        "101",
                        record,
                        job_dir=self.job_dir,
                        idempotency_key=self.key,
                    )
                )
            except BaseException as failure:
                failures.append(failure)

        threads = [threading.Thread(target=run, args=(record,)) for record in records]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(list(self.job_dir.rglob("*.staging.mp4")), [])

    def test_different_candidate_under_same_key_is_rejected_before_second_download(self) -> None:
        changed = freeze_pexels(
            FakeTransport(response(pexels_payload(candidate_id=102)))
        )
        first = self.staged()
        second_transport = FakeTransport(
            response(MP4 + b"different", content_type="video/mp4")
        )

        with self.assertRaises(stock_media.StockMediaError):
            stock_media.download_to_staging(
                changed,
                "102",
                job_dir=self.job_dir,
                idempotency_key=self.key,
                transport=second_transport,
                probe=good_probe,
                max_bytes=1024,
                clock=lambda: NOW,
            )

        self.assertEqual(second_transport.calls, [])
        self.assertTrue((self.job_dir / first["staging_job_path"]).is_file())

    def test_asset_link_failure_leaves_recoverable_publishing_state(self) -> None:
        staged = self.staged()
        original_link = stock_media.os.link
        asset_name = Path(staged["planned_job_path"]).name

        def fail_second_link(*args, **kwargs):
            if args[1] == asset_name:
                raise OSError("simulated crash boundary")
            return original_link(*args, **kwargs)

        with mock.patch.object(stock_media.os, "link", side_effect=fail_second_link):
            with self.assertRaises(stock_media.StockMediaError):
                stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=self.job_dir,
                    idempotency_key=self.key,
                )

        self.assertFalse((self.job_dir / staged["planned_job_path"]).exists())
        self.assertTrue((self.job_dir / staged["planned_license_snapshot"]).exists())
        journal = json.loads(
            (self.job_dir / staged["journal_job_path"]).read_text()
        )
        self.assertEqual(journal["state"], "publishing")
        recovered = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            staged,
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )
        self.assertTrue((self.job_dir / recovered["job_path"]).is_file())

    def test_actual_dimensions_survive_receipt_states_and_guard_replay(self) -> None:
        staged = self.staged()
        journal_path = self.job_dir / staged["journal_job_path"]
        complete = json.loads(journal_path.read_text())
        self.assertEqual(complete["state"], "complete")
        self.assertEqual(
            (complete["actual_width"], complete["actual_height"]),
            (1080, 1920),
        )

        original_link = stock_media.os.link
        asset_name = Path(staged["planned_job_path"]).name

        def fail_asset_link(*args, **kwargs):
            if args[1] == asset_name:
                raise OSError("hold publishing receipt")
            return original_link(*args, **kwargs)

        with mock.patch.object(
            stock_media.os, "link", side_effect=fail_asset_link
        ):
            with self.assertRaises(stock_media.StockMediaError):
                stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=self.job_dir,
                    idempotency_key=self.key,
                )

        publishing = json.loads(journal_path.read_text())
        self.assertEqual(publishing["state"], "publishing")
        self.assertEqual(
            (publishing["actual_width"], publishing["actual_height"]),
            (1080, 1920),
        )

        binding = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            staged,
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )
        published = json.loads(journal_path.read_text())
        self.assertEqual(published["state"], "published")
        self.assertEqual(
            (published["actual_width"], published["actual_height"]),
            (1080, 1920),
        )
        self.assertNotIn("actual_width", binding)
        self.assertNotIn("actual_height", binding)

        published["actual_width"] = 640
        journal_path.write_bytes(stock_media._canonical_bytes(published) + b"\n")
        transport = FakeTransport()
        with self.assertRaises(stock_media.StockMediaError):
            stock_media.download_to_staging(
                self.snapshot,
                "101",
                job_dir=self.job_dir,
                idempotency_key=self.key,
                transport=transport,
                probe=good_probe,
                max_bytes=1024,
                clock=lambda: NOW,
            )
        self.assertEqual(transport.calls, [])

    def test_retry_recovers_owned_license_orphan_after_process_crash(self) -> None:
        staged = self.staged()
        original_link = stock_media.os.link
        asset_name = Path(staged["planned_job_path"]).name

        def crash_before_asset_link(*args, **kwargs):
            if args[1] == asset_name:
                raise SimulatedCrash()
            return original_link(*args, **kwargs)

        with mock.patch.object(stock_media.os, "link", side_effect=crash_before_asset_link):
            with self.assertRaises(SimulatedCrash):
                stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=self.job_dir,
                    idempotency_key=self.key,
                )

        self.assertTrue((self.job_dir / staged["planned_license_snapshot"]).is_file())
        self.assertFalse((self.job_dir / staged["planned_job_path"]).exists())
        recovered = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            staged,
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )
        self.assertTrue((self.job_dir / recovered["job_path"]).is_file())

    def test_every_publish_link_and_unlink_crash_recovers_from_journal(self) -> None:
        checkpoints = (
            ("license-link", "link", ".license.json"),
            ("asset-link", "link", ".mp4"),
            ("license-unlink", "rename", ".license.staging.json"),
            ("stage-unlink", "rename", ".staging.mp4"),
        )
        for label, operation, suffix in checkpoints:
            with self.subTest(checkpoint=label), tempfile.TemporaryDirectory() as raw:
                job_dir = Path(raw).resolve()
                staged = stock_media.download_to_staging(
                    self.snapshot,
                    "101",
                    job_dir=job_dir,
                    idempotency_key=self.key,
                    transport=FakeTransport(
                        response(MP4, content_type="video/mp4")
                    ),
                    probe=good_probe,
                    max_bytes=1024,
                    clock=lambda: NOW,
                )
                original = getattr(stock_media.os, operation)
                crashed = False

                def crash_after(*args, **kwargs):
                    nonlocal crashed
                    result = original(*args, **kwargs)
                    target = args[1] if operation == "link" else args[0]
                    if not crashed and type(target) is str and target.endswith(suffix):
                        crashed = True
                        raise SimulatedCrash()
                    return result

                with mock.patch.object(
                    stock_media.os, operation, side_effect=crash_after
                ):
                    with self.assertRaises(SimulatedCrash):
                        stock_media.publish_frozen_asset(
                            self.snapshot,
                            "101",
                            staged,
                            job_dir=job_dir,
                            idempotency_key=self.key,
                        )

                recovered = stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=job_dir,
                    idempotency_key=self.key,
                )
                receipt = json.loads(
                    (job_dir / staged["journal_job_path"]).read_text()
                )
                self.assertEqual(receipt["state"], "published")
                self.assertTrue((job_dir / recovered["job_path"]).is_file())
                self.assertFalse((job_dir / staged["staging_job_path"]).exists())
                self.assertFalse(
                    (job_dir / staged["license_staging_job_path"]).exists()
                )

    def test_every_publish_fsync_crash_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            job_dir = Path(raw).resolve()
            staged = stock_media.download_to_staging(
                self.snapshot,
                "101",
                job_dir=job_dir,
                idempotency_key=self.key,
                transport=FakeTransport(
                    response(MP4, content_type="video/mp4")
                ),
                probe=good_probe,
                max_bytes=1024,
                clock=lambda: NOW,
            )
            original_fsync = stock_media.os.fsync
            clean_fsync_count = 0

            def count_fsync(descriptor):
                nonlocal clean_fsync_count
                result = original_fsync(descriptor)
                clean_fsync_count += 1
                return result

            with mock.patch.object(
                stock_media.os, "fsync", side_effect=count_fsync
            ):
                stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=job_dir,
                    idempotency_key=self.key,
                )

        self.assertGreaterEqual(clean_fsync_count, 1)
        for crash_index in range(1, clean_fsync_count + 1):
            with self.subTest(fsync=crash_index), tempfile.TemporaryDirectory() as raw:
                job_dir = Path(raw).resolve()
                staged = stock_media.download_to_staging(
                    self.snapshot,
                    "101",
                    job_dir=job_dir,
                    idempotency_key=self.key,
                    transport=FakeTransport(
                        response(MP4, content_type="video/mp4")
                    ),
                    probe=good_probe,
                    max_bytes=1024,
                    clock=lambda: NOW,
                )
                original_fsync = stock_media.os.fsync
                calls = 0

                def crash_after_fsync(descriptor):
                    nonlocal calls
                    result = original_fsync(descriptor)
                    calls += 1
                    if calls == crash_index:
                        raise SimulatedCrash()
                    return result

                with mock.patch.object(
                    stock_media.os, "fsync", side_effect=crash_after_fsync
                ):
                    with self.assertRaises(SimulatedCrash):
                        stock_media.publish_frozen_asset(
                            self.snapshot,
                            "101",
                            staged,
                            job_dir=job_dir,
                            idempotency_key=self.key,
                        )

                recovered = stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=job_dir,
                    idempotency_key=self.key,
                )
                receipt = json.loads(
                    (job_dir / staged["journal_job_path"]).read_text()
                )
                self.assertEqual(receipt["state"], "published")
                self.assertTrue((job_dir / recovered["job_path"]).is_file())

    def test_unlink_failure_preserves_recoverable_state(self) -> None:
        for field in ("license_staging_job_path", "staging_job_path"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as raw:
                job_dir = Path(raw).resolve()
                staged = stock_media.download_to_staging(
                    self.snapshot,
                    "101",
                    job_dir=job_dir,
                    idempotency_key=self.key,
                    transport=FakeTransport(
                        response(MP4, content_type="video/mp4")
                    ),
                    probe=good_probe,
                    max_bytes=1024,
                    clock=lambda: NOW,
                )
                target = Path(staged[field]).name
                original_rename = stock_media.os.rename
                failed = False

                def fail_before_unlink(path, *args, **kwargs):
                    nonlocal failed
                    if path == target and not failed:
                        failed = True
                        raise OSError("simulated unlink failure")
                    return original_rename(path, *args, **kwargs)

                with mock.patch.object(
                    stock_media.os, "rename", side_effect=fail_before_unlink
                ):
                    with self.assertRaises(stock_media.StockMediaError):
                        stock_media.publish_frozen_asset(
                            self.snapshot,
                            "101",
                            staged,
                            job_dir=job_dir,
                            idempotency_key=self.key,
                        )

                recovered = stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=job_dir,
                    idempotency_key=self.key,
                )
                self.assertTrue((job_dir / recovered["job_path"]).is_file())

    def test_byte_identical_concurrent_replacement_is_never_accepted_on_retry(self) -> None:
        checkpoints = (
            ("license_staging_job_path", "planned_license_snapshot"),
            ("staging_job_path", "planned_job_path"),
        )
        for unlink_field, final_field in checkpoints:
            with self.subTest(field=final_field), tempfile.TemporaryDirectory() as raw:
                job_dir = Path(raw).resolve()
                staged = stock_media.download_to_staging(
                    self.snapshot,
                    "101",
                    job_dir=job_dir,
                    idempotency_key=self.key,
                    transport=FakeTransport(
                        response(MP4, content_type="video/mp4")
                    ),
                    probe=good_probe,
                    max_bytes=1024,
                    clock=lambda: NOW,
                )
                unlink_name = Path(staged[unlink_field]).name
                original_rename = stock_media.os.rename
                crashed = False

                def crash_after_unlink(path, destination, *args, **kwargs):
                    nonlocal crashed
                    result = original_rename(path, destination, *args, **kwargs)
                    if path == unlink_name and not crashed:
                        crashed = True
                        raise SimulatedCrash()
                    return result

                with mock.patch.object(
                    stock_media.os, "rename", side_effect=crash_after_unlink
                ):
                    with self.assertRaises(SimulatedCrash):
                        stock_media.publish_frozen_asset(
                            self.snapshot,
                            "101",
                            staged,
                            job_dir=job_dir,
                            idempotency_key=self.key,
                        )

                final_path = job_dir / staged[final_field]
                original = final_path.read_bytes()
                replacement = final_path.with_name("replacement-identical")
                replacement.write_bytes(original)
                replacement.replace(final_path)
                replacement_inode = final_path.stat().st_ino

                with self.assertRaisesRegex(
                    stock_media.StockMediaError, "conflict"
                ):
                    stock_media.publish_frozen_asset(
                        self.snapshot,
                        "101",
                        staged,
                        job_dir=job_dir,
                        idempotency_key=self.key,
                    )
                self.assertEqual(final_path.stat().st_ino, replacement_inode)
                self.assertEqual(final_path.read_bytes(), original)

    def test_published_fifo_asset_or_license_is_rejected_before_open(self) -> None:
        for binding_field in ("job_path", "license_snapshot"):
            with self.subTest(field=binding_field), tempfile.TemporaryDirectory() as raw:
                job_dir = Path(raw).resolve()
                staged = stock_media.download_to_staging(
                    self.snapshot,
                    "101",
                    job_dir=job_dir,
                    idempotency_key=self.key,
                    transport=FakeTransport(
                        response(MP4, content_type="video/mp4")
                    ),
                    probe=good_probe,
                    max_bytes=1024,
                    clock=lambda: NOW,
                )
                binding = stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=job_dir,
                    idempotency_key=self.key,
                )
                target = job_dir / binding[binding_field]
                target.unlink()
                os.mkfifo(target)
                original_open = stock_media.os.open
                attempted = False

                def reject_fifo_open(path, *args, **kwargs):
                    nonlocal attempted
                    if path == target.name:
                        attempted = True
                        raise AssertionError("FIFO must be rejected before open")
                    return original_open(path, *args, **kwargs)

                transport = FakeTransport()
                with mock.patch.object(
                    stock_media.os, "open", side_effect=reject_fifo_open
                ):
                    with self.assertRaises(stock_media.StockMediaError):
                        stock_media.download_to_staging(
                            self.snapshot,
                            "101",
                            job_dir=job_dir,
                            idempotency_key=self.key,
                            transport=transport,
                            probe=good_probe,
                            max_bytes=1024,
                            clock=lambda: NOW,
                        )
                self.assertFalse(attempted)
                self.assertEqual(transport.calls, [])

    def test_published_receipt_rejects_byte_identical_replacement_inode(self) -> None:
        staged = self.staged()
        binding = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            staged,
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )
        asset = self.job_dir / binding["job_path"]
        replacement = asset.with_name("replacement-identical")
        replacement.write_bytes(asset.read_bytes())
        replacement.replace(asset)
        replacement_inode = asset.stat().st_ino
        transport = FakeTransport()

        with self.assertRaisesRegex(stock_media.StockMediaError, "conflict"):
            stock_media.download_to_staging(
                self.snapshot,
                "101",
                job_dir=self.job_dir,
                idempotency_key=self.key,
                transport=transport,
                probe=good_probe,
                max_bytes=1024,
                clock=lambda: NOW,
            )

        self.assertEqual(transport.calls, [])
        self.assertEqual(asset.stat().st_ino, replacement_inode)

    def test_license_write_failure_cleans_only_its_temporary_file(self) -> None:
        staged = self.staged()

        def fail_write(descriptor, data):
            raise OSError(
                f"write failed Authorization={REQUEST_ONLY_VALUE}"
            )

        with mock.patch.object(stock_media.os, "write", side_effect=fail_write):
            with self.assertRaises(stock_media.StockMediaError) as caught:
                stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=self.job_dir,
                    idempotency_key=self.key,
                )

        self.assertNotIn(REQUEST_ONLY_VALUE, str(caught.exception))
        parent = (self.job_dir / staged["planned_job_path"]).parent
        self.assertEqual(list(parent.glob("*.license.json.*.staging")), [])
        self.assertTrue((self.job_dir / staged["staging_job_path"]).is_file())
        self.assertTrue((self.job_dir / staged["journal_job_path"]).is_file())

    def test_orphan_read_then_concurrent_replace_preserves_replacement_evidence(self) -> None:
        staged = self.staged()
        original_link = stock_media.os.link
        calls = 0

        def crash_before_asset_link(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise SimulatedCrash()
            return original_link(*args, **kwargs)

        with mock.patch.object(stock_media.os, "link", side_effect=crash_before_asset_link):
            with self.assertRaises(SimulatedCrash):
                stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=self.job_dir,
                    idempotency_key=self.key,
                )

        license_path = self.job_dir / staged["planned_license_snapshot"]
        original_evidence = stock_media._checked_file_evidence
        replaced = False

        def replace_after_read(parent, name, **kwargs):
            nonlocal replaced
            result = original_evidence(parent, name, **kwargs)
            if name == license_path.name and result is not None and not replaced:
                replaced = True
                replacement = license_path.with_name("replacement-license.json")
                replacement.write_text(
                    json.dumps({"Authorization": REQUEST_ONLY_VALUE}),
                    encoding="utf-8",
                )
                replacement.replace(license_path)
            return result

        with mock.patch.object(
            stock_media,
            "_checked_file_evidence",
            side_effect=replace_after_read,
        ):
            with self.assertRaises(stock_media.StockMediaError) as caught:
                stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=self.job_dir,
                    idempotency_key=self.key,
                )

        self.assertNotIn(REQUEST_ONLY_VALUE, str(caught.exception))
        self.assertIn(REQUEST_ONLY_VALUE, license_path.read_text())

    def test_license_timestamp_and_schema_are_exact_on_replay(self) -> None:
        published = stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            self.staged(),
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )
        license_path = self.job_dir / published["license_snapshot"]
        record = json.loads(license_path.read_text())
        record["downloaded_at"] = "2026-08-31 04:05:06+00:00"
        license_path.write_text(json.dumps(record), encoding="utf-8")

        with self.assertRaises(stock_media.StockMediaError):
            stock_media.publish_frozen_asset(
                self.snapshot,
                "101",
                None,
                job_dir=self.job_dir,
                idempotency_key=self.key,
            )

    def test_request_only_value_is_absent_from_entire_successful_job_tree(self) -> None:
        stock_media.publish_frozen_asset(
            self.snapshot,
            "101",
            self.staged(),
            job_dir=self.job_dir,
            idempotency_key=self.key,
        )

        for path in self.job_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(
                    REQUEST_ONLY_VALUE.encode(), path.read_bytes(), path
                )

    def test_legal_provenance_containing_cookie_word_is_not_rejected(self) -> None:
        payload = json.loads(pexels_payload())
        payload["videos"][0]["user"]["name"] = "Cookie Monster"
        snapshot = freeze_pexels(
            FakeTransport(response(json.dumps(payload).encode()))
        )
        key = stock_media.stable_idempotency_key(
            "job", "seg", "cookie-author", 1, "pexels",
            snapshot["query_sha256"],
        )
        staged = stock_media.download_to_staging(
            snapshot,
            "101",
            job_dir=self.job_dir,
            idempotency_key=key,
            transport=FakeTransport(response(MP4, content_type="video/mp4")),
            probe=good_probe,
            max_bytes=1024,
            clock=lambda: NOW,
        )

        binding = stock_media.publish_frozen_asset(
            snapshot,
            "101",
            staged,
            job_dir=self.job_dir,
            idempotency_key=key,
        )

        self.assertEqual(binding["author"], "Cookie Monster")

    def test_one_shot_replacement_before_source_unlink_preserves_replacement(self) -> None:
        staged = self.staged()
        stage_name = Path(staged["staging_job_path"]).name
        parent_path = (self.job_dir / staged["staging_job_path"]).parent
        original_rename = stock_media.os.rename
        injected = False
        replacement_bytes = b"concurrent-replacement-evidence"

        def replace_before_unlink(path, destination, *args, **kwargs):
            nonlocal injected
            if path == stage_name and not injected:
                injected = True
                parent = kwargs["src_dir_fd"]
                original_rename(
                    path,
                    ".owned-stage-away",
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                )
                descriptor = os.open(
                    path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                    dir_fd=parent,
                )
                try:
                    os.write(descriptor, replacement_bytes)
                finally:
                    os.close(descriptor)
            return original_rename(path, destination, *args, **kwargs)

        with mock.patch.object(
            stock_media.os, "rename", side_effect=replace_before_unlink
        ):
            with self.assertRaises(stock_media.StockMediaError):
                stock_media.publish_frozen_asset(
                    self.snapshot,
                    "101",
                    staged,
                    job_dir=self.job_dir,
                    idempotency_key=self.key,
                )

        evidence = [
            path.read_bytes() for path in parent_path.rglob("*") if path.is_file()
        ]
        self.assertIn(replacement_bytes, evidence)


if __name__ == "__main__":
    unittest.main()
