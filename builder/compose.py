from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .metadata import BuildMetadata, MetadataError, load_metadata, release_tag, validate_compatible
from .package import header_manifest, package_filename, safe_extract_archive
from .verify import VerificationError, verify_android_aar


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
    safe_extract_archive(x64_archive, x64_destination)
    safe_extract_archive(arm64_archive, arm64_destination)
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


def _load_json_object(path: Path, description: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CompositionError(f"cannot read {description}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CompositionError(f"{description} root must be an object")
    return payload


def _validate_preview_xcframework(
    metadata_path: Path,
    reference: BuildMetadata,
    macos_metadata: BuildMetadata,
) -> None:
    metadata = _load_xcframework_metadata(metadata_path)
    if metadata.get("schema_version") != 1 or metadata.get("target") != "macos-universal":
        raise CompositionError("invalid XCFramework metadata identity")
    if metadata.get("builder_commit") != reference.builder_commit:
        raise CompositionError("XCFramework uses a different builder commit")
    if metadata.get("source") != reference.source:
        raise CompositionError("XCFramework uses a different WebRTC source")
    if metadata.get("header_manifest") != macos_metadata.header_manifest:
        raise CompositionError("XCFramework uses a different header manifest")


def create_preview_release_manifest(
    *,
    android_package: Path,
    android_aar: Path,
    macos_x64_package: Path,
    macos_arm64_package: Path,
    xcframework: Path,
    xcframework_metadata: Path,
    android_smoke_evidence: Path,
    macos_probe_evidence: Path,
    output_dir: Path,
    builder_commit: str,
    android_workflow_run_id: int,
    android_artifact_digest: str,
    release_date: str,
    preview_revision: int,
) -> Path:
    if not isinstance(preview_revision, int) or preview_revision < 1:
        raise CompositionError("preview revision must be a positive integer")
    packages = {
        "android": android_package,
        "macos-x64": macos_x64_package,
        "macos-arm64": macos_arm64_package,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    validation_dir = output_dir / ".preview-validation"
    shutil.rmtree(validation_dir, ignore_errors=True)
    metadata: dict[str, BuildMetadata] = {}
    try:
        for target, archive in packages.items():
            expected_name = package_filename(target)
            if archive.name != expected_name:
                raise CompositionError(
                    f"unexpected package filename for {target}: {archive.name}; "
                    f"expected {expected_name}"
                )
            destination = validation_dir / target
            safe_extract_archive(archive, destination)
            item = load_metadata(destination / "webrtc" / "metadata.json")
            if item.target != target:
                raise CompositionError(
                    f"package key {target} contains metadata target {item.target}"
                )
            metadata[target] = item
        validate_compatible(metadata.values())
        try:
            verify_android_aar(android_aar, validation_dir / "android" / "webrtc")
        except (OSError, zipfile.BadZipFile, VerificationError) as exc:
            raise CompositionError(f"Android AAR validation failed: {exc}") from exc
    except MetadataError as exc:
        raise CompositionError(str(exc)) from exc
    finally:
        shutil.rmtree(validation_dir, ignore_errors=True)

    reference = metadata["android"]
    if reference.builder_commit != builder_commit:
        raise CompositionError(
            "workflow builder commit differs from preview package builder commit"
        )
    if android_aar.name != "webrtc-m150-android-arm64-v8a.aar":
        raise CompositionError(f"unexpected Android AAR filename: {android_aar.name}")
    if xcframework.name != "WebRTC-m150-macos-universal.xcframework.zip":
        raise CompositionError(f"unexpected XCFramework filename: {xcframework.name}")
    _validate_preview_xcframework(
        xcframework_metadata, reference, metadata["macos-x64"]
    )

    android_evidence = _load_json_object(
        android_smoke_evidence, "Android AAR smoke evidence"
    )
    if android_evidence.get("schema_version") != 1:
        raise CompositionError("Android smoke evidence schema_version must be 1")
    if android_evidence.get("builder_commit") != builder_commit:
        raise CompositionError("Android smoke evidence uses a different builder commit")
    if android_evidence.get("workflow_run_id") != android_workflow_run_id:
        raise CompositionError("Android smoke evidence uses a different workflow run")
    if android_evidence.get("artifact_digest") != android_artifact_digest:
        raise CompositionError(
            "Android smoke evidence uses a different artifact digest"
        )
    if (
        not isinstance(android_artifact_digest, str)
        or not android_artifact_digest.startswith("sha256:")
        or len(android_artifact_digest) != len("sha256:") + 64
    ):
        raise CompositionError("Android artifact digest must be a SHA-256 digest")
    if android_evidence.get("aar_sha256") != _sha256(android_aar):
        raise CompositionError("Android smoke evidence AAR SHA does not match preview asset")
    if (
        android_evidence.get("marker") != "AAR_SMOKE_OK"
        or android_evidence.get("android_api_level") != 31
        or android_evidence.get("abi") != "arm64-v8a"
    ):
        raise CompositionError("Android smoke evidence does not satisfy the runtime gate")

    macos_evidence = _load_json_object(
        macos_probe_evidence, "macOS VideoToolbox probe evidence"
    )
    if macos_evidence.get("schema_version") != 1:
        raise CompositionError("macOS probe evidence schema_version must be 1")
    if macos_evidence.get("xcframework_zip_sha256") != _sha256(xcframework):
        raise CompositionError(
            "macOS probe evidence XCFramework SHA does not match preview asset"
        )
    modes = macos_evidence.get("modes")
    if not isinstance(modes, list):
        raise CompositionError("macOS probe evidence modes must be an array")
    by_mode = {
        item.get("mode"): item for item in modes if isinstance(item, dict)
    }
    if set(by_mode) != {"normal", "low_latency"} or any(
        item.get("session_status") != "success" for item in by_mode.values()
    ):
        raise CompositionError("macOS probe evidence requires two successful modes")
    if any(item.get("profile_mismatch") is not False for item in by_mode.values()):
        raise CompositionError("macOS probe evidence reports an H264 profile mismatch")
    low_latency_encoder_id = by_mode["low_latency"].get("encoder_id")
    if not isinstance(low_latency_encoder_id, str) or ".rtvc" not in low_latency_encoder_id:
        raise CompositionError("macOS low-latency probe did not select an RTVC encoder")
    if macos_evidence.get("macos_x64_hardware_runtime_verified") is not False:
        raise CompositionError(
            "preview evidence must explicitly record missing x64 hardware runtime coverage"
        )

    assets = [android_package, android_aar, macos_x64_package, macos_arm64_package, xcframework]
    tag = release_tag(builder_commit, release_date, "macos-android")
    tag = f"{tag}-preview.{preview_revision}"
    payload = {
        "schema_version": 1,
        "tag": tag,
        "source": dict(reference.source),
        "builder_commit": reference.builder_commit,
        "release_date": release_date,
        "platform": "macos-android",
        "preview_revision": preview_revision,
        "assets": [
            {"name": path.name, "sha256": _sha256(path), "size": path.stat().st_size}
            for path in sorted(assets, key=lambda item: item.name)
        ],
        "verification": {
            "android_workflow_run_id": android_evidence["workflow_run_id"],
            "android_artifact_digest": android_evidence["artifact_digest"],
            "android_api_level": android_evidence["android_api_level"],
            "android_abi": android_evidence["abi"],
            "android_smoke_evidence_sha256": _sha256(android_smoke_evidence),
            "macos_hardware_model": macos_evidence.get("hardware_model"),
            "macos_os_version": macos_evidence.get("os_version"),
            "macos_probe_evidence_sha256": _sha256(macos_probe_evidence),
            "macos_x64_hardware_runtime_verified": False,
        },
    }
    manifest = output_dir / "release-manifest.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    checksum_entries = [
        *(f"{item['sha256']}  {item['name']}" for item in payload["assets"]),
        f"{_sha256(manifest)}  {manifest.name}",
    ]
    (output_dir / "SHA256SUMS").write_text("\n".join(checksum_entries) + "\n")
    return manifest


def create_release_manifest(
    *,
    packages: Mapping[str, Path],
    android_aar: Path,
    xcframework: Path,
    xcframework_metadata: Path,
    output_dir: Path,
    builder_commit: str,
    release_date: str,
    platform: str,
) -> Path:
    expected_targets = {"android", "ios", "macos-x64", "macos-arm64", "windows-x64"}
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
            safe_extract_archive(archive, destination)
            item = load_metadata(destination / "webrtc" / "metadata.json")
            if item.target != target:
                raise CompositionError(
                    f"package key {target} contains metadata target {item.target}"
                )
            metadata.append(item)
        validate_compatible(metadata)
        try:
            verify_android_aar(android_aar, validation_dir / "android" / "webrtc")
        except (OSError, zipfile.BadZipFile, VerificationError) as exc:
            raise CompositionError(f"Android AAR validation failed: {exc}") from exc
    except MetadataError as exc:
        raise CompositionError(str(exc)) from exc
    finally:
        shutil.rmtree(validation_dir, ignore_errors=True)

    expected_aar_name = "webrtc-m150-android-arm64-v8a.aar"
    if android_aar.name != expected_aar_name:
        raise CompositionError(
            f"unexpected Android AAR filename {android_aar.name}; expected {expected_aar_name}"
        )
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

    assets = [*packages.values(), android_aar, xcframework]
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
