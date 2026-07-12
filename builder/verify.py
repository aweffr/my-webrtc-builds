from __future__ import annotations

from pathlib import Path
from typing import Protocol


class VerificationError(RuntimeError):
    """A produced payload is incomplete or has the wrong architecture."""


class CaptureRunner(Protocol):
    def capture(self, argv, *, cwd=None, env=None) -> str: ...


COMMON_REQUIRED_PATHS = (
    "include/api/peer_connection_interface.h",
    "metadata.json",
    "LICENSE",
    "PATENTS",
    "AUTHORS",
    "NOTICE",
    "SHA256SUMS",
)


def verify_package_layout(target: str, root: Path) -> None:
    required = list(COMMON_REQUIRED_PATHS)
    if target == "android":
        required.extend(
            (
                "lib/arm64-v8a/libwebrtc.a",
                "jar/webrtc.jar",
                "include/api/cast_tuning/cast_tuning_config.h",
            )
        )
    elif target == "ios":
        required.extend(
            (
                "lib/device-arm64/libwebrtc.a",
                "lib/simulator-arm64/libwebrtc.a",
            )
        )
    elif target in {"macos-x64", "macos-arm64"}:
        required.extend(
            (
                "lib/libwebrtc.a",
                "Frameworks/WebRTC.framework",
                "Frameworks/WebRTC.framework/Headers/RTCVideoEncoderH265.h",
                "Frameworks/WebRTC.framework/Headers/RTCVideoDecoderH265.h",
                "include/api/cast_tuning/cast_tuning_config.h",
                "Frameworks/WebRTC.framework/Headers/RTCCastTuning.h",
            )
        )
    elif target == "windows-x64":
        required.extend(
            (
                "lib/webrtc.lib",
                "include/api/cast_tuning/cast_tuning_config.h",
            )
        )
    else:
        raise VerificationError(f"unsupported verification target {target!r}")
    for relative in required:
        path = root / relative
        if not path.exists() and not path.is_symlink():
            raise VerificationError(f"required package path is missing: {relative}")


def _expect_archive_members(runner: CaptureRunner, archiver: str, library: Path) -> None:
    members = runner.capture([archiver, "-t", library])
    if not members.strip():
        raise VerificationError(f"static archive has no members: {library}")


def _expect_architecture(runner: CaptureRunner, binary: Path, expected: str) -> None:
    actual = set(runner.capture(["lipo", "-archs", binary]).split())
    if actual != {expected}:
        raise VerificationError(
            f"unexpected architecture for {binary}: {sorted(actual)}; expected {expected}"
        )


def _expect_symbols(
    runner: CaptureRunner,
    binary: Path,
    required_symbols: tuple[str, ...],
    *,
    tool: Path | str = "nm",
) -> None:
    symbols = runner.capture([tool, "--demangle", binary] if str(tool).endswith("llvm-nm.exe") else [tool, binary])
    for symbol in required_symbols:
        if symbol not in symbols:
            raise VerificationError(f"required symbol {symbol!r} is missing from {binary}")


def _expect_windows_binary(
    runner: CaptureRunner,
    library: Path,
    *,
    tool_dir: Path | str | None,
) -> None:
    root = Path(tool_dir) if tool_dir is not None else Path(".")
    lib_tool = root / "llvm-lib.exe"
    readobj_tool = root / "llvm-readobj.exe"
    nm_tool = root / "llvm-nm.exe"
    members = runner.capture([lib_tool, "/list", library])
    if not members.strip():
        raise VerificationError(f"static library has no members: {library}")

    headers = runner.capture([readobj_tool, "--file-headers", library])
    machines = {
        line.split(":", 1)[1].strip().split()[0]
        for line in headers.splitlines()
        if line.strip().startswith("Machine:")
    }
    if machines != {"IMAGE_FILE_MACHINE_AMD64"}:
        raise VerificationError(
            f"unexpected COFF architecture for {library}: {sorted(machines)}; expected AMD64"
        )
    _expect_symbols(
        runner,
        library,
        (
            "H264EncoderImpl",
            "H264DecoderImpl",
            "webrtc::cast_tuning::CastTuningController",
        ),
        tool=nm_tool,
    )


def _framework_binary(root: Path) -> Path:
    framework = root / "Frameworks" / "WebRTC.framework"
    direct = framework / "WebRTC"
    if direct.exists() or direct.is_symlink():
        return direct
    versioned = framework / "Versions" / "A" / "WebRTC"
    if versioned.exists():
        return versioned
    raise VerificationError("WebRTC.framework binary is missing")


def verify_binaries(
    target: str,
    root: Path,
    runner: CaptureRunner,
    *,
    android_archiver: Path | str = "llvm-ar",
    windows_tool_dir: Path | str | None = None,
) -> None:
    if target == "android":
        library = root / "lib" / "arm64-v8a" / "libwebrtc.a"
        _expect_archive_members(runner, str(android_archiver), library)
        jar_entries = runner.capture(["jar", "tf", root / "jar" / "webrtc.jar"])
        for entry in (
            "org/webrtc/CastTuningAndroidConfig.class",
            "org/webrtc/CastTuningConfig.class",
            "org/webrtc/CastTuningController.class",
            "org/webrtc/CastTuningSnapshot.class",
            "org/webrtc/CastTuningVideoDecoderFactory.class",
            "org/webrtc/HardwareVideoEncoderFactory.class",
            "org/webrtc/VideoEncoder$CodecSpecificInfoH265.class",
        ):
            if entry not in jar_entries:
                raise VerificationError(f"required Android codec class is missing: {entry}")
        cast_api = runner.capture(
            [
                "javap",
                "-classpath",
                root / "jar" / "webrtc.jar",
                "org.webrtc.CastTuningController",
            ]
        )
        for method in (
            "configureFactory",
            "configurePeerConnection",
            "attachReceiver",
            "createVideoDecoderFactory",
            "snapshot",
        ):
            if method not in cast_api:
                raise VerificationError(
                    f"required Android CastTuning method is missing: {method}"
                )
        return

    if target == "ios":
        for environment in ("device-arm64", "simulator-arm64"):
            library = root / "lib" / environment / "libwebrtc.a"
            _expect_archive_members(runner, "/usr/bin/ar", library)
            _expect_architecture(runner, library, "arm64")
            _expect_symbols(
                runner,
                library,
                ("RTCVideoEncoderH265", "RTCVideoDecoderH265"),
            )
        return

    if target in {"macos-x64", "macos-arm64"}:
        expected = "x86_64" if target == "macos-x64" else "arm64"
        library = root / "lib" / "libwebrtc.a"
        framework_binary = _framework_binary(root)
        _expect_archive_members(runner, "/usr/bin/ar", library)
        _expect_architecture(runner, library, expected)
        _expect_architecture(runner, framework_binary, expected)
        _expect_symbols(runner, library, ("H264EncoderImpl", "H264DecoderImpl"))
        _expect_symbols(
            runner,
            framework_binary,
            (
                "RTCVideoEncoderH265",
                "RTCVideoDecoderH265",
                "RTCCastTuningController",
            ),
        )
        return
    if target == "windows-x64":
        _expect_windows_binary(runner, root / "lib" / "webrtc.lib", tool_dir=windows_tool_dir)
        return
    raise VerificationError(f"unsupported binary verification target {target!r}")
