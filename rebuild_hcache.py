#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

HCACHE_NAME = "H.Cache.bin!E_---------------------w"
UNMANAGED_NAME = "UNMANAGED"
BCACHE_RE = re.compile(r"^(B\.Cache\..+?\.bin)!E_([A-Za-z0-9+\-]{22})$", re.IGNORECASE)

@dataclass(frozen=True)
class Manifest:
    path: Path
    logical_name: str
    encoded_hash: str
    size: int

class RebuildError(RuntimeError):
    pass

def b64m_decode(value: str) -> bytes:
    raw = base64.b64decode(value.replace("-", "/") + "==", validate=True)
    if len(raw) != 16:
        raise RebuildError(f"Invalid Warframe manifest hash: {value}")
    return raw

def b64m_encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii").rstrip("=").replace("/", "-")

def crc32c(data: bytes) -> int:
    polynomial = 0x82F63B78
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (polynomial if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF

def manifest_from_path(path: Path) -> Manifest:
    match = BCACHE_RE.fullmatch(path.name)
    if not match:
        raise RebuildError(
            f"Not a supported B.Cache manifest filename:\n  {path.name}\n\n"
            "Expected B.Cache.*.bin!E_<22-character-hash>."
        )
    return Manifest(
        path=path,
        logical_name=match.group(1),
        encoded_hash=match.group(2),
        size=path.stat().st_size,
    )

def collect_inputs(paths: list[Path]) -> list[Manifest]:
    manifests: list[Manifest] = []
    for raw_path in paths:
        path = raw_path.resolve()
        if path.is_dir():
            for child in sorted(path.iterdir(), key=lambda item: item.name.casefold()):
                if child.is_file() and BCACHE_RE.fullmatch(child.name):
                    manifests.append(manifest_from_path(child))
            continue
        if not path.is_file():
            raise RebuildError(f"Input does not exist:\n  {path}")
        manifests.append(manifest_from_path(path))
    if not manifests:
        raise RebuildError("No B.Cache.*.bin!E_<hash> files were provided.")
    return manifests

def validate_selection(manifests: list[Manifest]) -> list[Manifest]:
    grouped: dict[str, list[Manifest]] = defaultdict(list)
    for manifest in manifests:
        grouped[manifest.logical_name.casefold()].append(manifest)
    duplicates = [values for values in grouped.values() if len(values) > 1]
    if duplicates:
        lines = ["More than one hash was selected for the same logical manifest:"]
        for values in duplicates:
            lines.append("")
            lines.append(values[0].logical_name)
            for value in values:
                lines.append(f"  {value.encoded_hash}")
        lines.append("")
        lines.append("Select only the historically active file for each logical manifest.")
        raise RebuildError("\n".join(lines))
    selected = sorted(manifests, key=lambda item: item.logical_name.casefold())
    if not any(item.logical_name.casefold() == "b.cache.windows.bin" for item in selected):
        raise RebuildError("B.Cache.Windows.bin is required.")
    return selected

def build_hcache(manifests: list[Manifest]) -> bytes:
    payload = bytearray()
    payload += b"\x00" * 16
    payload += struct.pack("<I", 0x0D)
    payload += struct.pack("<I", 0)
    payload += struct.pack("<I", len(manifests))
    for manifest in manifests:
        logical_path = ("/" + manifest.logical_name).encode("utf-8")
        payload += struct.pack("<I", len(logical_path))
        payload += logical_path
        payload += b64m_decode(manifest.encoded_hash)
        payload += struct.pack("<I", manifest.size | 0x20000000)
    shcc_header = b"SHCC\x1f\x00\x00\x00"
    payload_hash = hashlib.md5(shcc_header + bytes(payload[16:])).digest()
    result = bytearray(shcc_header)
    result += b"\x00"
    result += struct.pack("<II", len(payload), len(payload))
    result += payload_hash
    result += payload[16:]
    result += b"\x00\xFF\xFF\xFF\xFF"
    result += b"\x00\x00\x00\x00\x00"
    result += b"\xFF\xFF\xFF\xFF"
    result += b"\x00\x00\x00\x00\x52"
    result += struct.pack("<I", crc32c(bytes(result)))
    return bytes(result)

def parse_hcache(raw: bytes) -> dict[str, tuple[str, int]]:
    if raw[:8] != b"SHCC\x1f\x00\x00\x00":
        raise RebuildError("Generated H.Cache has an invalid SHCC header.")
    position = 8
    chunk_type = raw[position]
    position += 1
    decompressed_size, compressed_size = struct.unpack_from("<II", raw, position)
    position += 8
    if chunk_type != 0 or decompressed_size != compressed_size:
        raise RebuildError("Generated H.Cache has an unexpected SHCC H chunk.")
    payload = raw[position:position + compressed_size]
    if len(payload) != compressed_size:
        raise RebuildError("Generated H.Cache is truncated.")
    expected_hash = hashlib.md5(raw[:8] + payload[16:]).digest()
    if payload[:16] != expected_hash:
        raise RebuildError("Generated H.Cache failed its MD5 self-check.")
    result: dict[str, tuple[str, int]] = {}
    position = 20
    remaining = 0
    while position < len(payload):
        while remaining == 0 and position < len(payload):
            remaining = struct.unpack_from("<I", payload, position)[0]
            position += 4
            if remaining == 0:
                continue
        if remaining == 0:
            break
        remaining -= 1
        path_length = struct.unpack_from("<I", payload, position)[0]
        position += 4
        logical_path = payload[position:position + path_length].decode("utf-8")
        position += path_length
        digest = payload[position:position + 16]
        position += 16
        metadata = struct.unpack_from("<I", payload, position)[0]
        position += 4
        result[logical_path] = (b64m_encode(digest), metadata)
    return result

def verify_hcache(raw: bytes, manifests: list[Manifest]) -> str:
    parsed = parse_hcache(raw)
    if len(parsed) != len(manifests):
        raise RebuildError(
            f"Generated H.Cache contains {len(parsed)} entries, expected {len(manifests)}."
        )
    for manifest in manifests:
        logical_path = "/" + manifest.logical_name
        expected = (manifest.encoded_hash, manifest.size | 0x20000000)
        if parsed.get(logical_path) != expected:
            raise RebuildError(f"Generated H.Cache verification failed for {logical_path}.")
    return parsed["/B.Cache.Windows.bin"][0]

def common_output_directory(manifests: list[Manifest]) -> Path:
    parents = {manifest.path.parent.resolve() for manifest in manifests}
    if len(parents) != 1:
        raise RebuildError(
            "All dragged B.Cache files must be in the same folder unless --output is used."
        )
    return next(iter(parents))

def write_outputs(output_directory: Path, hcache: bytes, force: bool) -> tuple[Path, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    hcache_path = output_directory / HCACHE_NAME
    unmanaged_path = output_directory / UNMANAGED_NAME
    if hcache_path.exists() and not force:
        raise RebuildError(
            f"H.Cache already exists:\n  {hcache_path}\n\n"
            "Use --force only if you intentionally want to replace it."
        )
    temporary_path = hcache_path.with_name(hcache_path.name + ".new")
    temporary_path.write_bytes(hcache)
    os.replace(temporary_path, hcache_path)
    unmanaged_path.write_bytes(b"")
    return hcache_path, unmanaged_path

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild an OpenWF H.Cache from selected B.Cache.* manifests. "
            "You can drag and drop the B.Cache files onto this script."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="B.Cache.* files or one folder containing them.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Directory where H.Cache.bin and UNMANAGED should be written.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing H.Cache.bin override.",
    )
    return parser.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        manifests = validate_selection(collect_inputs(args.inputs))
        output_directory = args.output.resolve() if args.output else common_output_directory(manifests)
        hcache = build_hcache(manifests)
        windows_hash = verify_hcache(hcache, manifests)
        hcache_path, unmanaged_path = write_outputs(output_directory, hcache, args.force)
    except (OSError, RebuildError, ValueError) as exc:
        print(f"\n[Error] {exc}", file=sys.stderr)
        return 1
    print(f"\n[Created] {hcache_path}")
    print(f"[Created] {unmanaged_path}")
    print(f"[Manifests] {len(manifests)}")
    print(f"[Cache hash] {windows_hash}")
    print(f"[Expected EE.log] Cache manifest hash {windows_hash}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
