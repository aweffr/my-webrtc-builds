from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .metadata import BuildMetadata, MetadataError, load_metadata, release_tag, validate_compatible
from .package import header_manifest, package_filename, safe_extract_tar


class CompositionError(RuntimeError):
    """Input artifacts cannot safely be merged or released together."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class MacOSInputs:
    x64_root: Path
    arm64_root: Path
    x64_metadata: BuildMetadata
    arm64_metadata: BuildMetadata


def prepare_macos_inputs(
    x64_archive: Path,
    arm64_archive: Path,
    work_dir: Path,
) -> MacOSInputs:
    shutil.rmtree(work_dir, ignore_errors=True)
    x64_destination = work_dir / "x64"
    arm64_destination = work_dir / "arm64"
    safe_extract_tar(x64_archive, x64_destination)
    safe_extract_tar(arm64_archive, arm64_destination)
    x64_root = x64_destination / "webrtc"
    arm64_root = arm64_destination / "webrtc"
    try:
        x64_metadata = load_metadata(x64_root / "metadata.json")
        arm64_metadata = load_metadata(arm64_root / "metadata.json")
        if x64_metadata.target != "macos-x64" or arm64_metadata.target != "macos-arm64":
            raise CompositionError(
                "macOS merge requires macos-x64 followed by macos-arm64 packages"
            )
        validate_compatible(
            (x64_metadata, arm64_metadata),
            require_same_patches=True,
        )
    except MetadataError as exc:
        raise CompositionError(str(exc)) from exc
    return MacOSInputs(
        x64_root=x64_root,
        arm64_root=arm64_root,
        x64_metadata=x64_metadata,
        arm64_metadata=arm64_metadata,
    )


def _framework(root: Path) -> Path:
    framework = root / "Frameworks" / "WebRTC.framework"
    if not framework.is_dir():
        raise CompositionError(f"WebRTC.framework is missing from {root}")
    return framework


def _framework_binary(framework: Path) -> Path:
    direct = framework / "WebRTC"
    if direct.exists() or direct.is_symlink():
        return direct
    versioned = framework / "Versions" / "A" / "WebRTC"
    if versioned.exists():
        return versioned
    raise CompositionError(f"framework binary is missing from {framework}")


def _framework_headers(framework: Path) -> Path:
    direct = framework / "Headers"
    if direct.exists() or direct.is_symlink():
        return direct.resolve()
    versioned = framework / "Versions" / "A" / "Headers"
    if versioned.is_dir():
        return versioned
    raise CompositionError(f"framework headers are missing from {framework}")


def compose_macos_xcframework(
    *,
    x64_archive: Path,
    arm64_archive: Path,
    work_dir: Path,
    output_dir: Path,
    builder_commit: str,
    runner,
) -> tuple[Path, Path]:
    inputs = prepare_macos_inputs(x64_archive, arm64_archive, work_dir / "inputs")
    if inputs.x64_metadata.builder_commit != builder_commit:
        raise CompositionError("workflow builder commit differs from thin package builder commit")
    x64_framework = _framework(inputs.x64_root)
    arm64_framework = _framework(inputs.arm64_root)
    if header_manifest(_framework_headers(x64_framework)) != header_manifest(
        _framework_headers(arm64_framework)
    ):
        raise CompositionError("thin frameworks contain different public headers")

    universal_parent = work_dir / "universal"
    shutil.rmtree(universal_parent, ignore_errors=True)
    universal_parent.mkdir(parents=True)
    universal_framework = universal_parent / "WebRTC.framework"
    shutil.copytree(x64_framework, universal_framework, symlinks=True)
    universal_binary = _framework_binary(universal_framework)
    runner.run(
        [
            "lipo",
            _framework_binary(x64_framework),
            _framework_binary(arm64_framework),
            "-create",
            "-output",
            universal_binary,
        ]
    )
    architectures = set(runner.capture(["lipo", "-archs", universal_binary]).split())
    if architectures != {"x86_64", "arm64"}:
        raise CompositionError(
            f"universal framework has architectures {sorted(architectures)} instead of x86_64/arm64"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    xcframework = output_dir / "WebRTC.xcframework"
    shutil.rmtree(xcframework, ignore_errors=True)
    runner.run(
        [
            "xcodebuild",
            "-create-xcframework",
            "-framework",
            universal_framework,
            "-output",
            xcframework,
        ]
    )
    if not xcframework.is_dir():
        raise CompositionError("xcodebuild did not create WebRTC.xcframework")

    metadata_payload = {
        "schema_version": 1,
        "target": "macos-universal",
        "source": dict(inputs.x64_metadata.source),
        "builder_commit": inputs.x64_metadata.builder_commit,
        "header_manifest": inputs.x64_metadata.header_manifest,
        "input_configuration_fingerprints": {
            "macos-x64": inputs.x64_metadata.configuration_fingerprint,
            "macos-arm64": inputs.arm64_metadata.configuration_fingerprint,
        },
    }
    metadata = output_dir / "xcframework-metadata.json"
    metadata.write_text(json.dumps(metadata_payload, indent=2, sort_keys=True) + "\n")
    shutil.copy2(metadata, xcframework / "metadata.json")
    for name in ("LICENSE", "PATENTS", "AUTHORS", "NOTICE"):
        shutil.copy2(inputs.x64_root / name, xcframework / name)

    archive = output_dir / "WebRTC-m150-macos-universal.xcframework.zip"
    archive.unlink(missing_ok=True)
    runner.run(
        ["zip", "--symlinks", "-r", archive, xcframework.name],
        cwd=output_dir,
    )
    if not archive.is_file():
        raise CompositionError("zip did not create the XCFramework archive")
    return archive, metadata


def _load_xcframework_metadata(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CompositionError(f"cannot read XCFramework metadata: {exc}") from exc
    if not isinstance(payload, dict):
        raise CompositionError("XCFramework metadata root must be an object")
    return payload


def create_release_manifest(
    *,
    packages: Mapping[str, Path],
    xcframework: Path,
    xcframework_metadata: Path,
    output_dir: Path,
    builder_commit: str,
    release_date: str,
    platform: str,
) -> Path:
    expected_targets = {"android", "ios", "macos-x64", "macos-arm64"}
    if set(packages) != expected_targets:
        raise CompositionError(
            f"release requires exact platform set {sorted(expected_targets)}; got {sorted(packages)}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    validation_dir = output_dir / ".metadata-validation"
    shutil.rmtree(validation_dir, ignore_errors=True)
    metadata: list[BuildMetadata] = []
    try:
        for target, archive in sorted(packages.items()):
            expected_name = package_filename(target)
            if archive.name != expected_name:
                raise CompositionError(
                    f"unexpected package filename for {target}: {archive.name}; expected {expected_name}"
                )
            destination = validation_dir / target
            safe_extract_tar(archive, destination)
            item = load_metadata(destination / "webrtc" / "metadata.json")
            if item.target != target:
                raise CompositionError(
                    f"package key {target} contains metadata target {item.target}"
                )
            metadata.append(item)
        validate_compatible(metadata)
    except MetadataError as exc:
        raise CompositionError(str(exc)) from exc
    finally:
        shutil.rmtree(validation_dir, ignore_errors=True)

    expected_xcframework_name = "WebRTC-m150-macos-universal.xcframework.zip"
    if xcframework.name != expected_xcframework_name:
        raise CompositionError(
            f"unexpected XCFramework filename {xcframework.name}; expected {expected_xcframework_name}"
        )
    xc_metadata = _load_xcframework_metadata(xcframework_metadata)
    reference = metadata[0]
    if reference.builder_commit != builder_commit:
        raise CompositionError(
            "workflow builder commit differs from release package builder commit"
        )
    if xc_metadata.get("schema_version") != 1 or xc_metadata.get("target") != "macos-universal":
        raise CompositionError("invalid XCFramework metadata identity")
    if xc_metadata.get("builder_commit") != reference.builder_commit:
        raise CompositionError("XCFramework uses a different builder commit")
    if xc_metadata.get("source") != reference.source:
        raise CompositionError("XCFramework uses a different WebRTC source")
    mac_metadata = next(item for item in metadata if item.target == "macos-x64")
    if xc_metadata.get("header_manifest") != mac_metadata.header_manifest:
        raise CompositionError("XCFramework uses a different header manifest")

    assets = [*packages.values(), xcframework]
    payload = {
        "schema_version": 1,
        "tag": release_tag(builder_commit, release_date, platform),
        "source": dict(reference.source),
        "builder_commit": reference.builder_commit,
        "release_date": release_date,
        "platform": platform,
        "assets": [
            {"name": path.name, "sha256": _sha256(path), "size": path.stat().st_size}
            for path in sorted(assets, key=lambda item: item.name)
        ],
    }
    manifest = output_dir / "release-manifest.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    checksums = output_dir / "SHA256SUMS"
    checksums.write_text(
        "\n".join(f"{item['sha256']}  {item['name']}" for item in payload["assets"]) + "\n"
    )
    return manifest
