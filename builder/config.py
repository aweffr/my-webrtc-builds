from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


class UnknownTargetError(ValueError):
    """Raised when a CLI target is not part of the fixed build matrix."""


@dataclass(frozen=True)
class SnapshotPart:
    name: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class SnapshotSpec:
    repository: str
    release_tag: str
    name: str
    manifest_name: str
    manifest_size_bytes: int
    manifest_sha256: str
    archive_size_bytes: int
    archive_sha256: str
    target_os: str
    runner_os: str
    runner_arch: str
    xcode_version: str
    parts: tuple[SnapshotPart, ...]

    def asset_url(self, name: str) -> str:
        return f"https://github.com/{self.repository}/releases/download/{self.release_tag}/{name}"


@dataclass(frozen=True)
class SourceVersion:
    milestone: int
    branch_head: int
    commit_position: int
    commit: str

    @property
    def release_base(self) -> str:
        return f"m{self.milestone}.{self.branch_head}.{self.commit_position}"


SOURCE_VERSION = SourceVersion(
    milestone=150,
    branch_head=7871,
    commit_position=3,
    commit="1f975dfd761af6e5d76d28333191973b258d82a8",
)

# Revision embedded in every published source snapshot.
DEPOT_TOOLS_COMMIT = "2f9bc10799af5aeb4a0ed903742ad69bb1d0ef75"

COMMON_GN_ARGS = (
    "is_debug=false",
    "is_component_build=false",
    "rtc_include_tests=false",
    "rtc_build_examples=false",
    "rtc_build_tools=false",
    "use_rtti=true",
    "rtc_use_perfetto=false",
    "libyuv_include_tests=false",
    "libyuv_use_sme=false",
    "enable_rust=false",
    "enable_rust_cxx=false",
    "enable_chromium_prelude=false",
    "rtc_rust=false",
    "use_debug_fission=false",
    "rtc_libvpx_build_vp9=true",
    "treat_warnings_as_errors=false",
)


@dataclass(frozen=True)
class TargetConfig:
    name: str
    runner: str
    architectures: tuple[str, ...]
    deployment_target: str | None
    patches: tuple[str, ...]
    overlays: tuple[str, ...]
    ninja_targets: tuple[str, ...]
    validation_targets: tuple[str, ...]
    snapshot: SnapshotSpec

    def gn_args_for(self, architecture: str) -> tuple[str, ...]:
        if architecture not in self.architectures:
            raise ValueError(f"unsupported architecture {architecture!r} for {self.name}")

        if self.name == "android":
            platform_args = (
                'target_os="android"',
                'target_cpu="arm64"',
                'android_static_analysis="off"',
                "is_java_debug=false",
                "rtc_use_h264=false",
                "rtc_use_h265=true",
            )
        elif self.name == "ios":
            environment, cpu = architecture.split(":", maxsplit=1)
            platform_args = (
                'target_os="ios"',
                f'target_cpu="{cpu}"',
                f'target_environment="{environment}"',
                f'ios_deployment_target="{self.deployment_target}"',
                "ios_enable_code_signing=false",
                "enable_stripping=true",
                "enable_dsyms=false",
                "use_lld=false",
                "rtc_enable_objc_symbol_export=true",
                "rtc_use_h264=false",
                "rtc_use_h265=true",
            )
        elif self.name == "windows-x64":
            platform_args = (
                'target_os="win"',
                'target_cpu="x64"',
                "use_custom_libcxx=false",
                "use_custom_libcxx_for_host=false",
                "proprietary_codecs=true",
                "rtc_use_h264=true",
                "rtc_system_openh264=false",
                'ffmpeg_branding="Chrome"',
                "rtc_use_h265=true",
            )
        else:
            cpu = architecture
            platform_args = (
                'target_os="mac"',
                f'target_cpu="{cpu}"',
                f'mac_deployment_target="{self.deployment_target}"',
                "enable_stripping=true",
                "enable_dsyms=false",
                "use_lld=false",
                "rtc_enable_symbol_export=true",
                "rtc_enable_objc_symbol_export=true",
                "proprietary_codecs=true",
                "rtc_use_h264=true",
                "rtc_system_openh264=false",
                'ffmpeg_branding="Chrome"',
                "rtc_use_h265=true",
            )
        return COMMON_GN_ARGS + platform_args


_APPLE_TARGETS = (
    ":default",
    "buildtools/third_party/libc++",
    "api/audio_codecs:builtin_audio_decoder_factory",
    "api/task_queue:default_task_queue_factory",
    "sdk:native_api",
    "sdk:default_codec_factory_objc",
    "pc:peer_connection",
    "sdk:videocapture_objc",
)


_SNAPSHOT_REPOSITORY = "aweffr/webrtc-source-snapshots"
_COMMON_SNAPSHOT_TAG = "m150.7871.3-source-poc1"


def _part(name: str, size_bytes: int, sha256: str) -> SnapshotPart:
    return SnapshotPart(name=name, size_bytes=size_bytes, sha256=sha256)


SNAPSHOTS: Mapping[str, SnapshotSpec] = MappingProxyType(
    {
        "android": SnapshotSpec(
            repository=_SNAPSHOT_REPOSITORY,
            release_tag=_COMMON_SNAPSHOT_TAG,
            name="webrtc-src-m150-android",
            manifest_name="webrtc-src-m150-android.manifest.json",
            manifest_size_bytes=556,
            manifest_sha256="c41249db84fbdbb0c3ac96fbf25553dda4f50b3ac3d685213245d0ca6dadda4c",
            archive_size_bytes=9189147504,
            archive_sha256="296bc53ec884627d0b73953b6ed46451d04271af1aec89cd999c110cc987ed39",
            target_os="android",
            runner_os="Linux",
            runner_arch="x64",
            xcode_version="none",
            parts=(
                _part(
                    "webrtc-src-m150-android.tar.zst.part-000",
                    1900000000,
                    "0181f84110486f0596c23f4681ce0fce024cfa5ca908ac9a7eeeed726299408f",
                ),
                _part(
                    "webrtc-src-m150-android.tar.zst.part-001",
                    1900000000,
                    "cd6b659d085605cf78b505c338ccf672e0b849ca775e1ebd3e945adee5324398",
                ),
                _part(
                    "webrtc-src-m150-android.tar.zst.part-002",
                    1900000000,
                    "fcc5695f952d3a06c84ae9c15f8e8250938af10673faa0ea5ee8528bc39c6698",
                ),
                _part(
                    "webrtc-src-m150-android.tar.zst.part-003",
                    1900000000,
                    "87ad36ff9731c8af980095f8803e45fe191070f2b0c267dbde1b6b7708a983ad",
                ),
                _part(
                    "webrtc-src-m150-android.tar.zst.part-004",
                    1589147504,
                    "d04f417fbcb402dd7649f1cfc55eb86dc118f0667113b75af8430c77de50a46a",
                ),
            ),
        ),
        "ios": SnapshotSpec(
            repository=_SNAPSHOT_REPOSITORY,
            release_tag=_COMMON_SNAPSHOT_TAG,
            name="webrtc-src-m150-ios",
            manifest_name="webrtc-src-m150-ios.manifest.json",
            manifest_size_bytes=552,
            manifest_sha256="1e6dc50a6d96b0801650aa08c01c06ff7f71c28dd58ce812f3a7b03edee20a59",
            archive_size_bytes=3321000407,
            archive_sha256="ad37db58fbdba7f6d98b8081376944df7b12e82fe433646a639bbb6a517c7ac1",
            target_os="ios",
            runner_os="macOS",
            runner_arch="arm64",
            xcode_version="26.0.1",
            parts=(
                _part(
                    "webrtc-src-m150-ios.tar.zst.part-000",
                    1900000000,
                    "84be22c5b164f9198bfb056d8417acf6a63cab98374e8c28b91b04c127ed34b7",
                ),
                _part(
                    "webrtc-src-m150-ios.tar.zst.part-001",
                    1421000407,
                    "82e04e5fa0593058b0554e4064bd0a43a9be365b55ef851e6fb8e97341bfae08",
                ),
            ),
        ),
        "macos-x64": SnapshotSpec(
            repository=_SNAPSHOT_REPOSITORY,
            release_tag=_COMMON_SNAPSHOT_TAG,
            name="webrtc-src-m150-macos-x64",
            manifest_name="webrtc-src-m150-macos-x64.manifest.json",
            manifest_size_bytes=556,
            manifest_sha256="79ea1e952d79f1d4b99f1bd2447757b33806995bffcabf84b63e632d8ec7b0ab",
            archive_size_bytes=3365419868,
            archive_sha256="a7924bc6aec1d396bb4d0b293e70d9363b1195c6605f1d2eddfab68d0a6d9ef5",
            target_os="mac",
            runner_os="macOS",
            runner_arch="x64",
            xcode_version="26.0.1",
            parts=(
                _part(
                    "webrtc-src-m150-macos-x64.tar.zst.part-000",
                    1900000000,
                    "f40e26d49d55f866b7ea36f3c20543f9c3bf1b96e0c062e3488a32aa5316cdf7",
                ),
                _part(
                    "webrtc-src-m150-macos-x64.tar.zst.part-001",
                    1465419868,
                    "4ff08aca299d1b582e4f0ad3c4bf1c1ce9d765598de80c2af1ac384d6811e666",
                ),
            ),
        ),
        "macos-arm64": SnapshotSpec(
            repository=_SNAPSHOT_REPOSITORY,
            release_tag=_COMMON_SNAPSHOT_TAG,
            name="webrtc-src-m150-macos-arm64",
            manifest_name="webrtc-src-m150-macos-arm64.manifest.json",
            manifest_size_bytes=560,
            manifest_sha256="ffedc6bc27c66d7c83d683829ae37a31b17050983e9af801a0c96d1fd8de842c",
            archive_size_bytes=3294284219,
            archive_sha256="66fbda6adb79a6fb9dc4c204611ab78f028a71745ae212c7437cb2c5b700543e",
            target_os="mac",
            runner_os="macOS",
            runner_arch="arm64",
            xcode_version="26.0.1",
            parts=(
                _part(
                    "webrtc-src-m150-macos-arm64.tar.zst.part-000",
                    1900000000,
                    "f6301f9d9541cf59c0108bb56aaf63f8552d142c295a394c8c42da150e3107e3",
                ),
                _part(
                    "webrtc-src-m150-macos-arm64.tar.zst.part-001",
                    1394284219,
                    "1a880e55bf01575b242b6ef73249c2d1e9e64937c22fda49f37d29fd2beaca0b",
                ),
            ),
        ),
        "windows-x64": SnapshotSpec(
            repository=_SNAPSHOT_REPOSITORY,
            release_tag="m150.7871.3-source-windows-x64",
            name="webrtc-src-m150-windows-x64",
            manifest_name="webrtc-src-m150-windows-x64.manifest.json",
            manifest_size_bytes=574,
            manifest_sha256="4a5e8f2dbb25cce3ed884c03f28422a609e87cb4b87f0e5ddfcd94926c11db50",
            archive_size_bytes=3665505354,
            archive_sha256="95062aa7044e0343edf08d2b869133e9e748ee3b5c1dad8a26ae109d89d445d1",
            target_os="win",
            runner_os="Windows",
            runner_arch="x64",
            xcode_version="none",
            parts=(
                _part(
                    "webrtc-src-m150-windows-x64.tar.zst.part-000",
                    1900000000,
                    "7c9baba8127799963a0369b8c196d32c1b97f9f0356c329b561f0b1d6b2ec523",
                ),
                _part(
                    "webrtc-src-m150-windows-x64.tar.zst.part-001",
                    1765505354,
                    "1b93f619fd89931cf3a8bb554baabe44c2d0c559432d36a08762402cd05a621c",
                ),
            ),
        ),
    }
)

TARGETS: Mapping[str, TargetConfig] = MappingProxyType(
    {
        "android": TargetConfig(
            name="android",
            runner="ubuntu-24.04",
            architectures=("arm64-v8a",),
            deployment_target=None,
            patches=(
                "add_deps.patch",
                "h265.patch",
                "h265_android.patch",
                "android_java8.patch",
                "cast_tuning_hooks.patch",
            ),
            overlays=("common", "android"),
            ninja_targets=(
                ":default",
                "buildtools/third_party/libc++",
                "sdk/android:libwebrtc",
                "sdk/android:libjingle_peerconnection_so",
                "sdk/android:native_api",
            ),
            validation_targets=("api/cast_tuning:cast_tuning_native_tests",),
            snapshot=SNAPSHOTS["android"],
        ),
        "ios": TargetConfig(
            name="ios",
            runner="macos-26",
            architectures=("device:arm64", "simulator:arm64"),
            deployment_target="14.0",
            patches=("add_deps.patch", "h265.patch", "h265_ios.patch"),
            overlays=(),
            ninja_targets=_APPLE_TARGETS + ("sdk:framework_objc",),
            validation_targets=(),
            snapshot=SNAPSHOTS["ios"],
        ),
        "macos-x64": TargetConfig(
            name="macos-x64",
            runner="macos-26-intel",
            architectures=("x64",),
            deployment_target="14.0",
            patches=(
                "add_deps.patch",
                "h265.patch",
                "h265_ios.patch",
                "macos_h265_framework.patch",
                "codec_licenses.patch",
                "cast_tuning_hooks.patch",
                "macos_hevc_cast_tuning.patch",
            ),
            overlays=("common", "macos"),
            ninja_targets=_APPLE_TARGETS + ("sdk:mac_framework_objc",),
            validation_targets=("api/cast_tuning:cast_tuning_native_tests",),
            snapshot=SNAPSHOTS["macos-x64"],
        ),
        "macos-arm64": TargetConfig(
            name="macos-arm64",
            runner="macos-26",
            architectures=("arm64",),
            deployment_target="14.0",
            patches=(
                "add_deps.patch",
                "h265.patch",
                "h265_ios.patch",
                "macos_h265_framework.patch",
                "codec_licenses.patch",
                "cast_tuning_hooks.patch",
                "macos_hevc_cast_tuning.patch",
            ),
            overlays=("common", "macos"),
            ninja_targets=_APPLE_TARGETS + ("sdk:mac_framework_objc",),
            validation_targets=("api/cast_tuning:cast_tuning_native_tests",),
            snapshot=SNAPSHOTS["macos-arm64"],
        ),
        "windows-x64": TargetConfig(
            name="windows-x64",
            runner="windows-2022",
            architectures=("x64",),
            deployment_target=None,
            patches=(
                "windows_add_deps.patch",
                "h265.patch",
                "codec_licenses.patch",
                "cast_tuning_hooks.patch",
            ),
            overlays=("common",),
            ninja_targets=(":default",),
            validation_targets=("api/cast_tuning:cast_tuning_native_tests",),
            snapshot=SNAPSHOTS["windows-x64"],
        ),
    }
)


def get_target(name: str) -> TargetConfig:
    try:
        return TARGETS[name]
    except KeyError as exc:
        choices = ", ".join(TARGETS)
        raise UnknownTargetError(f"unsupported target {name!r}; choose one of: {choices}") from exc
