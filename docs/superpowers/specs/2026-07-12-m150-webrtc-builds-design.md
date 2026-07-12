# M150 WebRTC Builds Design

## Goal

Create a public `aweffr/my-webrtc-builds` repository whose GitHub Actions manually build and publish reproducible WebRTC M150 binaries for Android, iOS, macOS x86_64, and macOS arm64.

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

Only these behavior patches are vendored: `add_deps.patch`, `h265.patch`, `h265_ios.patch`, and `h265_android.patch`. A project-maintained `codec_licenses.patch` adds the FFmpeg and OpenH264 license-file mappings required by the M150 notice generator after those dependencies enter the graph; it does not change codec behavior. Proxy, simulcast, Sora SDK, TLS, audio-device, and milestone-update patches remain out of scope.

## Platform contracts

### Android

- Runner: `ubuntu-24.04`
- ABI: `arm64-v8a` only
- Outputs: C++ headers, `lib/arm64-v8a/libwebrtc.a`, and `jar/webrtc.jar`
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

## Workflows and release flow

All workflows use only `workflow_dispatch`:

1. Build Android
2. Build iOS
3. Build macOS x64
4. Build macOS arm64
5. Package macOS XCFramework
6. Publish Release

Build workflows upload compressed packages as 30-day Actions artifacts. Compression happens before upload so Apple framework symlinks survive artifact transport.

The XCFramework workflow accepts explicit x64 and arm64 run IDs. It rejects mismatched WebRTC commits, builder commits, configuration fingerprints, or header manifests. It creates a universal framework binary with `lipo`, then wraps that framework with `xcodebuild -create-xcframework`.

The release workflow accepts the four build run IDs, the XCFramework run ID, and a release revision. It rejects mixed builder commits and existing release tags. The tag format is `m150.7871.3-rN`.

## Package contract

Binary packages are:

- `webrtc-m150-android-arm64-v8a.tar.gz`
- `webrtc-m150-ios.tar.gz`
- `webrtc-m150-macos-x64.tar.gz`
- `webrtc-m150-macos-arm64.tar.gz`
- `WebRTC-m150-macos-universal.xcframework.zip`

Every package includes or is accompanied by machine-readable metadata containing schema version, target, source version, builder commit, configuration fingerprint, GN arguments, patch hashes, runner/toolchain details (including the M150-pinned `depot_tools` commit), and payload checksums. Static packages also contain upstream `LICENSE`, `PATENTS`, `AUTHORS`, generated third-party `NOTICE`, and `SHA256SUMS`.

## Error handling and verification

The builder fails immediately when source identity, patch applicability, expected output, architecture, metadata schema, package safety, or compatibility checks fail. Subprocess failures preserve the command and exit status in Actions logs without printing credentials.

Unit tests protect target configuration, metadata construction and validation, archive path safety, cross-run compatibility, and release-tag rules. Each actual build additionally verifies archive members, CPU architecture, framework plist/symlinks/headers, Java contents, codec symbols, checksums, and package structure.

The initial delivery is complete only after all four hosted-runner builds succeed, the universal XCFramework is produced, and GitHub Release `m150.7871.3-r1` is published and downloaded for checksum verification.

## Observability

Every long-running phase writes both human-readable logs and an append-only JSONL journal containing target, architecture, phase state, duration, and sanitized failure information. Workflows preserve the complete builder output with `tee` and upload diagnostics on both success and failure. Diagnostics include runner/toolchain identity, disk snapshots, source commit/status, resolved GN arguments, and output inventories. Actions Step Summaries point directly to the failing phase and diagnostics artifact; command logging never serializes environment variables or tokens.

## Licensing

The repository uses Apache-2.0 for its own code and preserves the license of every vendored patch. Distributed packages carry WebRTC and generated third-party notices. The user has confirmed that their company has the required H.264/H.265 licenses, so bundled macOS OpenH264 distribution is an accepted product decision.
