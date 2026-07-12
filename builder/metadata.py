from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .config import SOURCE_VERSION, TargetConfig, get_target


SCHEMA_VERSION = 1


class MetadataError(ValueError):
    """Raised when artifact metadata violates the build contract."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def configuration_fingerprint(target: TargetConfig) -> str:
    payload = asdict(target)
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _source_dict() -> dict[str, int | str]:
    return {
        "milestone": SOURCE_VERSION.milestone,
        "branch_head": SOURCE_VERSION.branch_head,
        "commit_position": SOURCE_VERSION.commit_position,
        "commit": SOURCE_VERSION.commit,
    }


@dataclass(frozen=True)
class BuildMetadata:
    schema_version: int
    target: str
    source: Mapping[str, int | str]
    builder_commit: str
    configuration_fingerprint: str
    header_manifest: str
    patch_hashes: Mapping[str, str]
    gn_args: Mapping[str, tuple[str, ...]]
    toolchain: Mapping[str, str]

    @classmethod
    def create(
        cls,
        *,
        target: str,
        builder_commit: str,
        header_manifest: str,
        patch_hashes: Mapping[str, str],
        gn_args: Mapping[str, tuple[str, ...]],
        toolchain: Mapping[str, str],
    ) -> BuildMetadata:
        config = get_target(target)
        return cls(
            schema_version=SCHEMA_VERSION,
            target=target,
            source=_source_dict(),
            builder_commit=builder_commit,
            configuration_fingerprint=configuration_fingerprint(config),
            header_manifest=header_manifest,
            patch_hashes=dict(sorted(patch_hashes.items())),
            gn_args={key: tuple(value) for key, value in sorted(gn_args.items())},
            toolchain=dict(sorted(toolchain.items())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target": self.target,
            "source": dict(self.source),
            "builder_commit": self.builder_commit,
            "configuration_fingerprint": self.configuration_fingerprint,
            "header_manifest": self.header_manifest,
            "patch_hashes": dict(self.patch_hashes),
            "gn_args": {key: list(value) for key, value in self.gn_args.items()},
            "toolchain": dict(self.toolchain),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BuildMetadata:
        schema_version = payload.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise MetadataError(
                f"unsupported metadata schema version {schema_version!r}; expected {SCHEMA_VERSION}"
            )
        target_name = payload.get("target")
        try:
            target = get_target(str(target_name))
        except ValueError as exc:
            raise MetadataError(f"unknown metadata target {target_name!r}") from exc

        source = payload.get("source")
        if source != _source_dict():
            raise MetadataError("metadata source does not match pinned WebRTC M150")
        expected_fingerprint = configuration_fingerprint(target)
        actual_fingerprint = payload.get("configuration_fingerprint")
        if actual_fingerprint != expected_fingerprint:
            raise MetadataError("metadata configuration fingerprint does not match target")

        required_strings = ("builder_commit", "header_manifest")
        for field in required_strings:
            if not isinstance(payload.get(field), str) or not payload[field]:
                raise MetadataError(f"metadata field {field!r} must be a non-empty string")

        patch_hashes = payload.get("patch_hashes")
        gn_args = payload.get("gn_args")
        toolchain = payload.get("toolchain")
        if not isinstance(patch_hashes, dict):
            raise MetadataError("metadata patch_hashes must be an object")
        if not isinstance(gn_args, dict):
            raise MetadataError("metadata gn_args must be an object")
        if not isinstance(toolchain, dict):
            raise MetadataError("metadata toolchain must be an object")

        return cls(
            schema_version=SCHEMA_VERSION,
            target=target.name,
            source=dict(source),
            builder_commit=payload["builder_commit"],
            configuration_fingerprint=actual_fingerprint,
            header_manifest=payload["header_manifest"],
            patch_hashes={str(key): str(value) for key, value in patch_hashes.items()},
            gn_args={str(key): tuple(map(str, value)) for key, value in gn_args.items()},
            toolchain={str(key): str(value) for key, value in toolchain.items()},
        )


def save_metadata(path: Path, metadata: BuildMetadata) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata.to_dict(), indent=2, sort_keys=True) + "\n")


def load_metadata(path: Path) -> BuildMetadata:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataError(f"cannot read metadata from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MetadataError("metadata root must be an object")
    return BuildMetadata.from_dict(payload)


def validate_compatible(
    metadata: Iterable[BuildMetadata],
    *,
    require_same_headers: bool = False,
    require_same_patches: bool = False,
) -> None:
    items = tuple(metadata)
    if len(items) < 2:
        raise MetadataError("compatibility validation requires at least two packages")
    first = items[0]
    for candidate in items[1:]:
        if candidate.source != first.source:
            raise MetadataError("packages use different WebRTC source versions")
        if candidate.builder_commit != first.builder_commit:
            raise MetadataError("packages use different builder commits")
        if require_same_patches and candidate.patch_hashes != first.patch_hashes:
            raise MetadataError("packages use different patch sets")
        if require_same_headers and candidate.header_manifest != first.header_manifest:
            raise MetadataError("packages use different header manifests")


def release_tag(revision: int) -> str:
    if revision <= 0:
        raise ValueError("release revision must be positive")
    return f"{SOURCE_VERSION.release_base}-r{revision}"
