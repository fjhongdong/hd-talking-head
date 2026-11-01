#!/usr/bin/env python3
"""Minimal, fail-closed OpenLux image client for V5 concept assets."""

from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
import math
import os
import secrets
import stat
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import warnings
from pathlib import Path

from PIL import Image, UnidentifiedImageError


MODEL = "gpt-image-2-c"
SIZE = "1024x1536"
QUALITY = "low"
EXPECTED_SIZE = (1024, 1536)
DEFAULT_BASE_URL = "https://api.openlux.ai"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_JSON_BYTES = ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 1024 * 1024
MAX_IMAGE_PIXELS = EXPECTED_SIZE[0] * EXPECTED_SIZE[1]
MAX_ENV_BYTES = 64 * 1024
_SAFE_SERVICE_DETAILS = {
    "quota denied retry after 5 seconds": "quota denied retry after 5 seconds",
    "rate_limit_exceeded": "rate_limit_exceeded",
    "model_not_found": "model_not_found",
}


class OpenLuxError(RuntimeError):
    pass


def _reject_json_constant(value: str):
    raise ValueError(f"non-finite JSON constant: {value}")


def _reject_duplicate_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _parse_finite_json_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


def _strict_json_loads(source: str | bytes) -> object:
    return json.loads(
        source,
        parse_constant=_reject_json_constant,
        parse_float=_parse_finite_json_float,
        object_pairs_hook=_reject_duplicate_json_object,
    )


def _open_system_request(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener()
    return opener.open(request, timeout=timeout)


def _open_generation_request(request: urllib.request.Request, timeout: float):
    return _open_system_request(request, timeout)


def _open_download_request(request: urllib.request.Request, timeout: float):
    return _open_system_request(request, timeout)


def build_request(prompt: str) -> dict:
    if not isinstance(prompt, str):
        raise OpenLuxError("prompt must be a string")
    prompt = prompt.strip()
    if not prompt:
        raise OpenLuxError("prompt must not be empty")
    if len(prompt) > 1000:
        raise OpenLuxError("prompt must not exceed 1000 characters")
    return {
        "model": MODEL,
        "prompt": prompt,
        "size": SIZE,
        "quality": QUALITY,
        "n": 1,
        "response_format": "b64_json",
    }


def _safe_http_url(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenLuxError(f"{label} must be an HTTP(S) URL")
    value = value.strip()
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        raise OpenLuxError(f"{label} must be a safe HTTP(S) URL") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OpenLuxError(f"{label} must be a safe HTTP(S) URL")
    try:
        parsed.port
    except ValueError:
        raise OpenLuxError(f"{label} must be a safe HTTP(S) URL") from None
    return value


def _read_limited_response(response, *, limit: int | None = None) -> bytes:
    limit = MAX_IMAGE_BYTES if limit is None else limit
    headers = getattr(response, "headers", None)
    if headers is None and hasattr(response, "info"):
        headers = response.info()
    content_length = headers.get("Content-Length") if headers is not None else None
    if content_length is not None:
        try:
            declared = int(content_length)
        except (TypeError, ValueError):
            raise OpenLuxError("response Content-Length is invalid") from None
        if declared < 0 or declared > limit:
            raise OpenLuxError("response is too large")
    chunks = []
    total = 0
    while True:
        chunk = response.read(min(64 * 1024, limit + 1 - total))
        if not isinstance(chunk, (bytes, bytearray)):
            raise OpenLuxError("response stream returned invalid data")
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise OpenLuxError("response is too large")
        chunks.append(bytes(chunk))
    return b"".join(chunks)


def _safe_service_detail(value: object, api_key: str) -> str | None:
    if type(value) is not str:
        return None
    if api_key and api_key in value:
        return "[redacted]"
    if any(character.isspace() and character != " " for character in value):
        return "[redacted]"
    normalized = " ".join(value.split()).casefold()
    if not normalized:
        return None
    return _SAFE_SERVICE_DETAILS.get(normalized, "[redacted]")


def request_image(
    prompt: str, *, api_key: str, base_url: str, timeout: float = 300
) -> dict:
    if not isinstance(api_key, str) or not api_key.strip():
        raise OpenLuxError("OPENLUX_API_KEY is required")
    api_key = api_key.strip()
    if type(base_url) is not str or "?" in base_url or "#" in base_url:
        raise OpenLuxError("base URL must be a safe HTTP(S) URL")
    base_url = _safe_http_url(base_url, "base URL")
    body = json.dumps(build_request(prompt), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/images/generations",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "AI-Lecturer-V5/1.0",
        },
    )
    try:
        with _open_generation_request(request, timeout) as response:
            try:
                payload = _strict_json_loads(
                    _read_limited_response(
                        response, limit=MAX_JSON_BYTES
                    ).decode("utf-8")
                )
            except (UnicodeError, json.JSONDecodeError, ValueError):
                raise OpenLuxError("OpenLux response is malformed") from None
        if not isinstance(payload, dict):
            raise OpenLuxError("OpenLux response is malformed")
        return payload
    except urllib.error.HTTPError as error:
        message = f"OpenLux HTTP {error.code}"
        try:
            try:
                payload = _strict_json_loads(
                    _read_limited_response(error, limit=MAX_JSON_BYTES).decode("utf-8")
                )
                detail = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(detail, dict):
                    detail = detail.get("message") or detail.get("code")
                safe_detail = _safe_service_detail(detail, api_key)
                if safe_detail:
                    message += f": {safe_detail}"
            except Exception:
                pass
        finally:
            try:
                error.close()
            except Exception:
                pass
        raise OpenLuxError(message) from None
    except OpenLuxError:
        raise
    except Exception as error:
        raise OpenLuxError(f"OpenLux request failed: {type(error).__name__}") from None


def _download_item(item: dict) -> bytes:
    encoded = item.get("b64_json")
    if isinstance(encoded, str):
        maximum_encoded = ((MAX_IMAGE_BYTES + 2) // 3) * 4
        if len(encoded) > maximum_encoded:
            raise OpenLuxError("base64 image response is too large")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise OpenLuxError("invalid base64 image response") from None
        if len(decoded) > MAX_IMAGE_BYTES:
            raise OpenLuxError("base64 image response is too large")
        return decoded
    url = item.get("url")
    if isinstance(url, str):
        url = _safe_http_url(url, "image URL")
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "AI-Lecturer-V5/1.0"}
            )
            with _open_download_request(request, timeout=120) as response:
                return _read_limited_response(response)
        except OpenLuxError:
            raise
        except Exception as error:
            raise OpenLuxError(
                f"cannot download generated image: {type(error).__name__}"
            ) from None
    raise OpenLuxError("response contains no image data")


def detect_extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    raise OpenLuxError("unsupported image format")


def validate_image_bytes(data: bytes) -> tuple[str, int, int]:
    extension = detect_extension(data)
    expected_format = {".png": "PNG", ".jpg": "JPEG", ".webp": "WEBP"}[extension]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                actual_format = image.format
                width, height = image.size
                if (
                    (width, height) != EXPECTED_SIZE
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise OpenLuxError(
                        f"image must be 1024x1536, received {width}x{height}"
                    )
                image.load()
    except OpenLuxError:
        raise
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ):
        raise OpenLuxError("image cannot be decoded") from None
    if actual_format != expected_format:
        raise OpenLuxError("image signature and decoded format disagree")
    return extension, width, height


class StableDirectory:
    def __init__(self, path: Path, descriptor: int):
        self.path = Path(path).absolute()
        self.descriptor = descriptor
        status = os.fstat(descriptor)
        self.identity = (status.st_dev, status.st_ino)
        self.closed = False

    def verify(self) -> None:
        if self.closed:
            raise OpenLuxError("stable output directory is closed")
        try:
            logical = os.lstat(self.path)
            descriptor_status = os.fstat(self.descriptor)
        except OSError:
            raise OpenLuxError("output directory identity changed") from None
        if (
            stat.S_ISLNK(logical.st_mode)
            or not stat.S_ISDIR(logical.st_mode)
            or (logical.st_dev, logical.st_ino) != self.identity
            or (descriptor_status.st_dev, descriptor_status.st_ino) != self.identity
        ):
            raise OpenLuxError("output directory identity changed")

    def close(self) -> None:
        if not self.closed:
            os.close(self.descriptor)
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def open_stable_directory(path: Path, *, create: bool = False) -> StableDirectory:
    path = Path(path).absolute()
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError:
            raise OpenLuxError("cannot create output directory safely") from None
    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            raise OpenLuxError("output directory must be a real directory")
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OpenLuxError:
        raise
    except OSError:
        raise OpenLuxError("cannot open output directory safely") from None
    handle = StableDirectory(path, descriptor)
    try:
        handle.verify()
    except BaseException:
        handle.close()
        raise
    return handle


def _validate_component_case(directory_fd: int, component: str) -> None:
    try:
        aliases = [
            entry for entry in os.listdir(directory_fd)
            if entry.casefold() == component.casefold()
        ]
    except OSError:
        raise OpenLuxError("cannot inspect stable directory safely") from None
    if aliases and aliases != [component]:
        raise OpenLuxError("case-folded directory alias is not allowed")


def open_stable_subdirectory(
    root: StableDirectory,
    parts,
    *,
    create: bool = False,
) -> StableDirectory:
    if isinstance(parts, (str, bytes)):
        raise OpenLuxError("stable directory parts must be separate components")
    try:
        components = tuple(parts)
    except TypeError:
        raise OpenLuxError("stable directory parts are invalid") from None
    for component in components:
        if (
            not isinstance(component, str)
            or not component
            or component in {".", ".."}
            or "/" in component
            or "\\" in component
            or "\0" in component
        ):
            raise OpenLuxError("stable directory component is unsafe")
    root.verify()
    descriptor = os.dup(root.descriptor)
    logical = root.path
    try:
        for component in components:
            _validate_component_case(descriptor, component)
            try:
                child = os.open(
                    component,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                if not create:
                    raise OpenLuxError("stable subdirectory does not exist") from None
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                    child = os.open(
                        component,
                        os.O_RDONLY
                        | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=descriptor,
                    )
                except OSError:
                    raise OpenLuxError(
                        "cannot create stable subdirectory safely"
                    ) from None
            except OSError:
                raise OpenLuxError("cannot open stable subdirectory safely") from None
            _validate_component_case(descriptor, component)
            os.close(descriptor)
            descriptor = child
            logical /= component
        root.verify()
        handle = StableDirectory(logical, descriptor)
        descriptor = -1
        handle.verify()
        return handle
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _read_at(directory_fd: int, name: str, *, limit: int = MAX_IMAGE_BYTES) -> bytes:
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
    except OSError:
        raise OpenLuxError("cannot read staged image safely") from None
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_size > limit:
            raise OpenLuxError("staged image is not a safe regular file")
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, limit + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise OpenLuxError("staged image is too large")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _write_exclusive_at(directory_fd: int, name: str, data: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short image write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _exists_at(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _unlink_at(directory_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=directory_fd)
    except FileNotFoundError:
        pass


def save_image_response(
    response: dict,
    output_stem: Path,
    *,
    stable_directory: StableDirectory | None = None,
) -> Path:
    items = response.get("data") if isinstance(response, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise OpenLuxError("response contains no image item")
    data = _download_item(items[0])
    extension, _, _ = validate_image_bytes(data)
    output_stem = Path(output_stem)
    output = output_stem.with_suffix(extension)
    owned_handle = stable_directory is None
    handle = stable_directory or open_stable_directory(output.parent, create=True)
    if output.parent.absolute() != handle.path:
        if owned_handle:
            handle.close()
        raise OpenLuxError("output path does not match the stable directory")
    generation = secrets.token_hex(8)
    temporary = f".{output.name}.{generation}.tmp"
    backup = f".{output.name}.{generation}.bak"
    old_exists = False
    published = False
    preserve_backup = False
    try:
        handle.verify()
        if _exists_at(handle.descriptor, output.name):
            status = os.stat(
                output.name, dir_fd=handle.descriptor, follow_symlinks=False
            )
            if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
                raise OpenLuxError("existing output must be one regular unaliased file")
            old_exists = True
        _write_exclusive_at(handle.descriptor, temporary, data)
        staged = _read_at(handle.descriptor, temporary)
        staged_extension, _, _ = validate_image_bytes(staged)
        if staged_extension != extension:
            raise OpenLuxError("staged image format mismatch")
        if old_exists:
            _write_exclusive_at(
                handle.descriptor,
                backup,
                _read_at(handle.descriptor, output.name),
            )
        handle.verify()
        os.replace(
            temporary,
            output.name,
            src_dir_fd=handle.descriptor,
            dst_dir_fd=handle.descriptor,
        )
        published = True
        os.fsync(handle.descriptor)
        validate_image_bytes(_read_at(handle.descriptor, output.name))
        handle.verify()
        _unlink_at(handle.descriptor, backup)
        os.fsync(handle.descriptor)
    except BaseException as failure:
        rollback_error = None
        if published:
            try:
                if old_exists:
                    os.replace(
                        backup,
                        output.name,
                        src_dir_fd=handle.descriptor,
                        dst_dir_fd=handle.descriptor,
                    )
                else:
                    _unlink_at(handle.descriptor, output.name)
                os.fsync(handle.descriptor)
            except BaseException as error:
                rollback_error = error
                preserve_backup = old_exists and _exists_at(handle.descriptor, backup)
        if rollback_error is not None:
            raise OpenLuxError(
                "image rollback failed; manual recovery backup preserved"
            ) from failure
        raise
    finally:
        _unlink_at(handle.descriptor, temporary)
        if not preserve_backup:
            _unlink_at(handle.descriptor, backup)
        if owned_handle:
            handle.close()
    return output


def load_env_file(
    path: Path, *, project_root: Path | None = None
) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        path = Path(path).absolute()
        status = os.lstat(path)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_nlink != 1
            or status.st_mode & 0o077
        ):
            raise OpenLuxError(
                "environment file must be private, regular, and unaliased"
            )
        if project_root is not None:
            root = Path(project_root).absolute()
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                relative = None
            if relative is not None:
                tracked = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(root),
                        "ls-files",
                        "--error-unmatch",
                        "--",
                        relative,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if tracked.returncode == 0:
                    raise OpenLuxError("environment file must not be tracked")
                if tracked.returncode not in {1}:
                    raise OpenLuxError("cannot verify environment file tracking")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened = os.fstat(descriptor)
            if (
                (opened.st_dev, opened.st_ino) != (status.st_dev, status.st_ino)
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_mode & 0o077
                or opened.st_size > MAX_ENV_BYTES
            ):
                raise OpenLuxError("environment file identity or permissions changed")
            chunks = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(8192, MAX_ENV_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ENV_BYTES:
                    raise OpenLuxError("environment file is too large")
                chunks.append(chunk)
        finally:
            os.close(descriptor)
        lines = b"".join(chunks).decode("utf-8").splitlines()
    except OpenLuxError:
        raise
    except (OSError, UnicodeError):
        raise OpenLuxError("cannot read the explicit environment file") from None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() in {"OPENLUX_API_KEY", "OPENLUX_BASE_URL"}:
            values[key.strip()] = value.strip().strip("'\"")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        values = (
            load_env_file(args.env_file, project_root=args.project_root)
            if args.env_file
            else {}
        )
        output_stem = Path(args.output)
        with open_stable_directory(output_stem.parent, create=True) as stable:
            response = request_image(
                args.prompt_file.read_text(encoding="utf-8"),
                api_key=os.environ.get("OPENLUX_API_KEY")
                or values.get("OPENLUX_API_KEY", ""),
                base_url=os.environ.get("OPENLUX_BASE_URL")
                or values.get("OPENLUX_BASE_URL", DEFAULT_BASE_URL),
            )
            print(
                save_image_response(
                    response, output_stem, stable_directory=stable
                ).name
            )
        return 0
    except (OSError, UnicodeError, OpenLuxError) as error:
        print(f"错误: {error}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
