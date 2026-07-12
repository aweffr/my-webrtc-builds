from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


class UnknownTargetError(ValueError):
    """Raised when a CLI target is not part of the fixed build matrix."""


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
    ninja_targets: tuple[str, ...]

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
                "rtc_enable_objc_symbol_export=false",
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

TARGETS: Mapping[str, TargetConfig] = MappingProxyType(
    {
        "android": TargetConfig(
            name="android",
            runner="ubuntu-24.04",
            architectures=("arm64-v8a",),
            deployment_target=None,
            patches=("add_deps.patch", "h265.patch", "h265_android.patch"),
            ninja_targets=(
                ":default",
                "buildtools/third_party/libc++",
                "sdk/android:libwebrtc",
                "sdk/android:libjingle_peerconnection_so",
                "sdk/android:native_api",
            ),
        ),
        "ios": TargetConfig(
            name="ios",
            runner="macos-26",
            architectures=("device:arm64", "simulator:arm64"),
            deployment_target="14.0",
            patches=("add_deps.patch", "h265.patch", "h265_ios.patch"),
            ninja_targets=_APPLE_TARGETS + ("sdk:framework_objc",),
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
                "codec_licenses.patch",
            ),
            ninja_targets=_APPLE_TARGETS + ("sdk:mac_framework_objc",),
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
                "codec_licenses.patch",
            ),
            ninja_targets=_APPLE_TARGETS + ("sdk:mac_framework_objc",),
        ),
    }
)


def get_target(name: str) -> TargetConfig:
    try:
        return TARGETS[name]
    except KeyError as exc:
        choices = ", ".join(TARGETS)
        raise UnknownTargetError(f"unsupported target {name!r}; choose one of: {choices}") from exc
