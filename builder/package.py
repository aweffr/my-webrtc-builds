from __future__ import annotations

import hashlib
import os
import posixpath
import shutil
import tarfile
from pathlib import Path, PurePosixPath

from .build import BuildUnit
from .config import TargetConfig
from .metadata import BuildMetadata, save_metadata
from .source import Runner, Workspace


class PackageError(RuntimeError):
    """An archive or staged package violates the package contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def header_manifest(include_dir: Path) -> str:
    digest = hashlib.sha256()
    headers = sorted(path for path in include_dir.rglob("*") if path.is_file())
    if not headers:
        raise PackageError(f"no headers found in {include_dir}")
    for path in headers:
        relative = path.relative_to(include_dir).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(_sha256(path).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def package_filename(target: str) -> str:
    filenames = {
        "android": "webrtc-m150-android-arm64-v8a.tar.gz",
        "ios": "webrtc-m150-ios.tar.gz",
        "macos-x64": "webrtc-m150-macos-x64.tar.gz",
        "macos-arm64": "webrtc-m150-macos-arm64.tar.gz",
    }
    try:
        return filenames[target]
    except KeyError as exc:
        raise PackageError(f"unsupported package target {target!r}") from exc


def write_checksums(root: Path) -> Path:
    output = root / "SHA256SUMS"
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path != output
    )
    lines = [f"{_sha256(path)}  {path.relative_to(root).as_posix()}" for path in files]
    output.write_text("\n".join(lines) + "\n")
    return output


def create_tar_gz(source: Path, archive: Path, *, arcname: str) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz", dereference=False) as stream:
        stream.add(source, arcname=arcname, recursive=True)


def _validate_member(member: tarfile.TarInfo) -> None:
    name = PurePosixPath(member.name)
    if name.is_absolute() or ".." in name.parts:
        raise PackageError(f"unsafe archive path: {member.name}")
    if member.issym() or member.islnk():
        if PurePosixPath(member.linkname).is_absolute():
            raise PackageError(f"unsafe archive link: {member.name} -> {member.linkname}")
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
        if resolved == ".." or resolved.startswith("../"):
            raise PackageError(f"unsafe archive link: {member.name} -> {member.linkname}")


def safe_extract_tar(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as stream:
        members = stream.getmembers()
        for member in members:
            _validate_member(member)
        stream.extractall(destination, members=members)


def _copy_headers(source: Path, destination: Path) -> None:
    extensions = {".h", ".hpp", ".inc"}
    excluded = {".git", "out", "out_aar", "build-workspace"}
    for root, directories, files in os.walk(source):
        directories[:] = [directory for directory in directories if directory not in excluded]
        root_path = Path(root)
        for filename in files:
            source_file = root_path / filename
            if source_file.suffix not in extensions:
                continue
            relative = source_file.relative_to(source)
            destination_file = destination / relative
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination_file)


def _copy_generated_headers(unit: BuildUnit, destination: Path) -> None:
    generated = unit.output_dir / "gen"
    if generated.exists():
        _copy_headers(generated, destination)


def _patch_hashes(target: TargetConfig, patch_dir: Path) -> dict[str, str]:
    return {name: _sha256(patch_dir / name) for name in target.patches}


def _copy_payload(target: TargetConfig, units: tuple[BuildUnit, ...], stage: Path) -> None:
    unit_by_arch = {unit.architecture: unit for unit in units}
    if target.name == "android":
        unit = unit_by_arch["arm64-v8a"]
        library = stage / "lib" / "arm64-v8a" / "libwebrtc.a"
        library.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(unit.output_dir / "libwebrtc.a", library)
        jar = stage / "jar" / "webrtc.jar"
        jar.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(unit.output_dir / "lib.java/sdk/android/libwebrtc.jar", jar)
    elif target.name == "ios":
        for architecture, unit in unit_by_arch.items():
            destination = stage / "lib" / architecture.replace(":", "-") / "libwebrtc.a"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(unit.output_dir / "libwebrtc.a", destination)
    else:
        unit = units[0]
        library = stage / "lib" / "libwebrtc.a"
        library.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(unit.output_dir / "libwebrtc.a", library)
        framework = unit.output_dir / "WebRTC.framework"
        shutil.copytree(
            framework,
            stage / "Frameworks" / "WebRTC.framework",
            symlinks=True,
        )


def stage_and_package(
    target: TargetConfig,
    workspace: Workspace,
    units: tuple[BuildUnit, ...],
    dist_dir: Path,
    patch_dir: Path,
    builder_commit: str,
    toolchain: dict[str, str],
    runner: Runner,
) -> Path:
    stage = workspace.stage / target.name / "webrtc"
    shutil.rmtree(stage.parent, ignore_errors=True)
    stage.mkdir(parents=True)
    include = stage / "include"
    _copy_headers(workspace.src, include)
    for unit in units:
        _copy_generated_headers(unit, include)
    for name in ("LICENSE", "PATENTS", "AUTHORS"):
        shutil.copy2(workspace.src / name, stage / name)

    license_command = [
        "python3",
        workspace.src / "tools_webrtc/libs/generate_licenses.py",
    ]
    for ninja_target in target.ninja_targets:
        license_command.extend(("--target", ninja_target))
    license_command.extend((stage, *(unit.output_dir for unit in units)))
    runner.run(license_command, cwd=workspace.src, env=workspace.environment())
    generated_license = stage / "LICENSE.md"
    if not generated_license.is_file():
        raise PackageError("WebRTC license generator did not create LICENSE.md")
    generated_license.replace(stage / "NOTICE")

    _copy_payload(target, units, stage)
    build_info = stage / "build"
    build_info.mkdir()
    for unit in units:
        shutil.copy2(
            unit.output_dir / "gn-args.txt",
            build_info / f"gn-args-{unit.architecture.replace(':', '-')}.txt",
        )

    manifest = header_manifest(include)
    metadata = BuildMetadata.create(
        target=target.name,
        builder_commit=builder_commit,
        header_manifest=manifest,
        patch_hashes=_patch_hashes(target, patch_dir),
        gn_args={unit.architecture: unit.gn_args for unit in units},
        toolchain=toolchain,
    )
    save_metadata(stage / "metadata.json", metadata)
    write_checksums(stage)

    from .verify import verify_binaries, verify_package_layout

    verify_package_layout(target.name, stage)
    verify_binaries(target.name, stage, runner)
    archive = dist_dir / package_filename(target.name)
    create_tar_gz(stage, archive, arcname="webrtc")
    return archive
