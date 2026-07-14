# M150 WebRTC Builds Design

## Goal

Create a public `aweffr/my-webrtc-builds` repository whose GitHub Actions manually build and publish reproducible WebRTC M150 binaries for Android, iOS, macOS x86_64, macOS arm64, and Windows x86_64.

## Fixed upstream version

- Milestone: M150
- Branch head: `7871`
- Commit position: `3`
- Commit: `1f975dfd761af6e5d76d28333191973b258d82a8`
- Xcode: 26.0.1
- iOS and macOS deployment target: 14.0

The project intentionally has no milestone input, updater, schedule, or moving branch reference. A repository release revision changes only when this project's builder, patch set, or packaging changes.

## Architecture

A small Python standard-library package owns the complete build contract: target configuration, source checkout, patch application, GN generation, Ninja execution, static archive assembly, package metadata, validation, and release composition. Platform workflows are thin adapters that select a target and runner.

The project borrows proven concepts rather than either reference repository wholesale:

- From Shiguredo: exact M150 source pin, complete-object static archive assembly, dependency-completeness patch, generated third-party notices, and M150 H.265 patches.
- From stasel: building `sdk:mac_framework_objc` and packaging Apple frameworks.

Only these upstream behavior patches are vendored: `add_deps.patch`, `windows_add_deps.patch`, `h265.patch`, `h265_ios.patch`, and `h265_android.patch`. A project-maintained `macos_h265_framework.patch` exposes the already-wired H.265 implementation and public headers from the M150 macOS framework target. A minimal `codec_licenses.patch` prevents the upstream notice generator from rejecting the introduced codec dependencies. Proxy, simulcast, Sora SDK, TLS, audio-device, and milestone-update patches remain out of scope except for the Windows dependency-completeness hunk required by the standalone root library.

## Platform contracts

### Android

- Runner: `ubuntu-24.04`
- ABI: `arm64-v8a` only
- Raw SDK output: C++ headers, `lib/arm64-v8a/libwebrtc.a`,
  `jar/webrtc.jar`, and the loadable
  `jni/arm64-v8a/libjingle_peerconnection_so.so`
- App-consumable output: a standalone arm64-v8a AAR containing
  `AndroidManifest.xml`, the same Java bytecode as `jar/webrtc.jar`, and the
  same stripped JNI shared library as the raw SDK package
- H.264/H.265: Android MediaCodec integration compiled through the WebRTC Java/JNI targets

### iOS

- Runner: `macos-26` (arm64)
- Slices: device arm64 and simulator arm64, packaged as separate static libraries
- Outputs: C++/Objective-C headers and one `libwebrtc.a` per SDK environment
- H.264/H.265: VideoToolbox integration; no mobile OpenH264/FFmpeg software path

### macOS

- x86_64 runner: `macos-26-intel`
- arm64 runner: `macos-26`
- Per-architecture outputs: headers, `lib/libwebrtc.a`, and thin `Frameworks/WebRTC.framework`
- Static library H.264: bundled OpenH264 encoder and FFmpeg decoder using `rtc_system_openh264=false` and `ffmpeg_branding="Chrome"`
- Framework H.264/H.265: VideoToolbox integration

The repository compiles codec capabilities but does not alter upstream runtime codec-factory selection. H.265 software fallback is not part of this project.

### Windows

- Runner: `windows-2022` with the installed Visual Studio 2022 toolchain
- ABI: x86_64, non-component Release static library using the upstream `/MT` CRT contract
- Outputs: C++ headers, `lib/webrtc.lib`, CastTuning common C++ API, metadata, notices, and checksums
- GN uses `target_os="win"`, `target_cpu="x64"`, `use_custom_libcxx=false`, and the installed toolchain with `DEPOT_TOOLS_WIN_TOOLCHAIN=0`
- Static-library H.264: bundled OpenH264 encoder and FFmpeg decoder using `rtc_use_h264=true`, `rtc_system_openh264=false`, and `ffmpeg_branding="Chrome"`
- H.265: parser/negotiation capability only; no Windows encoder/decoder integration is promised
- No Windows-specific CastTuning wrapper is included; consumers use the common C++ API directly

## Workflows and release flow

All workflows use only `workflow_dispatch`:

1. Build Android
2. Build iOS
3. Build macOS x64
4. Build macOS arm64
5. Build Windows x64
6. Package macOS XCFramework
7. Publish Release

Build workflows upload compressed packages as 30-day Actions artifacts. Compression happens before upload so Apple framework symlinks survive artifact transport.

The XCFramework workflow accepts explicit x64 and arm64 run IDs. It rejects mismatched WebRTC commits, builder commits, configuration fingerprints, or header manifests. It creates a universal framework binary with `lipo`, then wraps that framework with `xcodebuild -create-xcframework`.

The release workflow accepts five build run IDs and the XCFramework run ID. It rejects mixed builder commits and existing release tags. The combined-release tag format is `webrtc-m150.7871.3-<builder-short-sha>-YYYYMMDD-all`.

The stable `-all` contract remains unchanged. A scoped GitHub pre-release may
publish only the platforms changed by an experimental binary revision without
rebuilding unrelated platforms. Such a pre-release contains only artifacts
built from its new builder commit, uses an explicit platform-set/preview tag,
and is marked as a GitHub pre-release; it must not mix unchanged artifacts from
an older builder commit or present itself as the stable all-platform release.
The Android AAR and the macOS low-latency change are initially delivered by a
single macOS/Android-scoped pre-release, while iOS and Windows remain on the
prior stable release. Its tag follows
`webrtc-m150.7871.3-<builder-short-sha>-YYYYMMDD-macos-android-preview.N`;
`N` starts at `1` and increments for another preview from the same revision
line.

## Package contract

Binary packages are:

- `webrtc-m150-android-arm64-v8a.tar.gz`
- `webrtc-m150-android-arm64-v8a.aar`
- `webrtc-m150-ios.tar.gz`
- `webrtc-m150-macos-x64.tar.gz`
- `webrtc-m150-macos-arm64.tar.gz`
- `webrtc-m150-windows-x64.zip`
- `WebRTC-m150-macos-universal.xcframework.zip`

Every package includes or is accompanied by machine-readable metadata containing schema version, target, source version, builder commit, configuration fingerprint, GN arguments, patch hashes, runner/toolchain details (including the M150-pinned `depot_tools` commit), and payload checksums. Static packages also contain upstream `LICENSE`, `PATENTS`, `AUTHORS`, generated third-party `NOTICE`, and `SHA256SUMS`.

The Android AAR is a first-class GitHub Release asset rather than an
application-local repackaging step. Its `classes.jar` and
`jni/arm64-v8a/libjingle_peerconnection_so.so` are assembled from the same GN
outputs staged into the raw Android package. Release validation rejects either
asset when those paired payloads differ, when `JNI_OnLoad` is absent, or when
the shared library is not AArch64.

Android package acceptance has two layers. GitHub Actions builds and uploads
the AAR, then compiles a minimal APK that consumes only that AAR and verifies
that the resulting APK carries the expected arm64-v8a JNI library. Before the
scoped pre-release is published, the exact workflow artifact is downloaded to
the local Mac without repackaging and used for an arm64 API 31 emulator E2E
smoke: the app initializes `PeerConnectionFactory`, creates a factory, and
queries the available H.264 codec capability. The evidence binds the workflow
run ID and artifact digest to the AAR SHA-256, ABI, Android API level, and
relevant logs. The verified AAR bytes are the bytes later uploaded to the
pre-release. This is an app-consumability gate, not an Android TV UI or
end-to-end screencast test.

## Error handling and verification

The builder fails immediately when source identity, patch applicability, expected output, architecture, metadata schema, package safety, or compatibility checks fail. Subprocess failures preserve the command and exit status in Actions logs without printing credentials.

Unit tests protect target configuration, metadata construction and validation, archive path safety, cross-run compatibility, and release-tag rules. Each actual build additionally verifies archive members, CPU architecture, framework plist/symlinks/headers, Java contents, codec symbols, checksums, and package structure.

The full release delivery is complete only after all five hosted-runner builds succeed, the universal XCFramework is produced, and the corresponding GitHub Release is published and downloaded for checksum verification. The Windows extension itself is accepted on this branch after its hosted build succeeds; combined-release publication remains a later same-commit operation.

A scoped pre-release is complete when every artifact in its declared platform
set is built from the same builder commit, composed artifacts validate against
their inputs, the partial release manifest lists exactly that set, GitHub marks
the release as pre-release, and every uploaded asset is downloaded and its
checksum reverified. For a scoped release containing Android, the compile and
arm64 emulator runtime smokes above must pass against the exact AAR SHA being
published. For this preview, the final arm64 framework/XCFramework slice must
also pass a 1080p H.264 probe on a real Apple Silicon Mac, covering normal and
low-latency session creation, encoder ID, negotiated profile, output SPS
profile, and explicit mismatch logging. The x64 slice receives hosted build,
link/symbol, and package verification; its lack of real Intel VideoToolbox
runtime coverage is recorded explicitly and hosted-runner VM results are not
treated as hardware evidence. It does not satisfy or weaken the full-release
criterion.

The initial scoped manifest contains exactly the Android raw tar and AAR,
macOS x64 and arm64 tar packages, universal macOS XCFramework, manifest, and
release checksums. One joint manifest proves that the sender/receiver platform
pair belongs to the same preview revision; separate platform release tags are
not created.

## Observability

Every long-running phase writes both human-readable logs and an append-only JSONL journal containing target, architecture, phase state, duration, and sanitized failure information. Workflows preserve the complete builder output with `tee` and upload diagnostics on both success and failure. Diagnostics include runner/toolchain identity, disk snapshots, source commit/status, resolved GN arguments, and output inventories. Actions Step Summaries point directly to the failing phase and diagnostics artifact; command logging never serializes environment variables or tokens.

## Licensing

The repository uses Apache-2.0 for its own code and preserves the license of every vendored patch. Distributed packages carry WebRTC and generated third-party notices. The user has confirmed that their company has the required H.264/H.265 licenses, so bundled macOS OpenH264 distribution is an accepted product decision.
