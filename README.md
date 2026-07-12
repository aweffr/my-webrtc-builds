# my-webrtc-builds

Reproducible, manually triggered WebRTC M150 builds for Android, iOS, and
macOS. Every binary is pinned to:

- WebRTC milestone: M150
- Branch head: `7871`
- Commit position: `3`
- Commit: `1f975dfd761af6e5d76d28333191973b258d82a8`

This repository intentionally does not accept a WebRTC version input and does
not run builds on pushes, schedules, or pull requests.

## Packages

| Workflow | Package | Contents |
| --- | --- | --- |
| Build Android | `webrtc-m150-android-arm64-v8a.tar.gz` | arm64-v8a `libwebrtc.a`, C++ headers, `webrtc.jar` |
| Build iOS | `webrtc-m150-ios.tar.gz` | Separate device-arm64 and simulator-arm64 `libwebrtc.a` files and headers |
| Build macOS x64 | `webrtc-m150-macos-x64.tar.gz` | x86_64 `libwebrtc.a`, headers, thin `WebRTC.framework` |
| Build macOS arm64 | `webrtc-m150-macos-arm64.tar.gz` | arm64 `libwebrtc.a`, headers, thin `WebRTC.framework` |
| Package macOS XCFramework | `WebRTC-m150-macos-universal.xcframework.zip` | x86_64 + arm64 macOS `WebRTC.xcframework` |

Static packages also contain resolved GN arguments, `metadata.json`, upstream
license files, generated third-party `NOTICE`, and `SHA256SUMS`.

## CastTuning runtime tuning

Android and both macOS artifacts include the CastTuning schema `1` shim. iOS
is intentionally unchanged. After building this release once, normal latency
experiments change runtime configuration instead of recompiling WebRTC.

Start with [`examples/cast-tuning-detail-idle.json`](examples/cast-tuning-detail-idle.json).
Profiles are `UPSTREAM`, `DETAIL_IDLE`, `DETAIL_ACTIVE`, `MOTION`, and
`RECOVERY`. Omitted values preserve upstream behavior; `UPSTREAM` generates no
Field Trials and calls no tuning setters.

The fixed precedence is upstream defaults → profile → JSON → environment or
Android Intent → live patch. macOS reads:

```bash
export CAST_TUNING_CONFIG=/absolute/path/cast-tuning.json
export CAST_TUNING_PROFILE=DETAIL_ACTIVE
export CAST_TUNING_OVERRIDES_JSON='{"sender":{"max_fps":20}}'
```

Use `RTCCastTuningConfiguration`, `RTCCastTuningFactoryBuilder`, and
`RTCCastTuningController` from the macOS framework. On Android, construct a
`CastTuningConfig`, pass the controller through `configureFactory` and
`configurePeerConnection`, attach the receiver, and use the controller's
decoder factory:

```java
CastTuningConfig config = CastTuningAndroidConfig.fromIntent(baseJson, intent);
try (CastTuningController tuning = new CastTuningController(config)) {
  PeerConnectionFactory.Builder factoryBuilder =
      tuning.configureFactory(PeerConnectionFactory.builder());
  tuning.configurePeerConnection(rtcConfiguration);
  tuning.attachReceiver(videoReceiver);
  VideoDecoderFactory decoders = tuning.createVideoDecoderFactory(eglContext);
}
```

Android Intent extras are `org.webrtc.cast_tuning.PROFILE` and
`org.webrtc.cast_tuning.OVERRIDES_JSON`.

Changes have three scopes:

- `LIVE`: bitrate bounds, frame constraints, content hint, degradation
  preference, minimum jitter, and stale-frame policy. A failed multi-setter
  patch is rolled back atomically; rollback failure requires session rebuild.
- `SESSION`: start bitrate/BWE reset and encoder or decoder construction values.
- `FACTORY`: Field Trials, pacer, and recovery advertisement. Build a new
  factory and session.

The recommended first experiment is NACK+RTX, FEC disabled, zero minimum jitter,
prerender smoothing disabled, VideoToolbox realtime enabled, and frame
reordering disabled. Change one variable at a time, retain the effective config
hash, and compare at least capture/encode, pacer queue, RTT/loss, jitter/decode,
and render timing. Optional codec properties may fall back with a recorded
reason; `REQUIRE_HARDWARE` is a hard failure. A telemetry `jsonl_path` enables
ordered, asynchronous controller events keyed by session ID, hash, and
revision.

The recovery state machine reports `PLI_REQUESTED`,
`DECODER_RECREATE_REQUIRED`, and `SENDER_RESET_AND_KEYFRAME_REQUIRED`; the
embedding application owns the actual action and cross-end signalling. This
repository does not contain a debug UI, remote-config service, or casting app.
The full design is in
[`docs/superpowers/specs/2026-07-12-cast-tuning-shim-design.md`](docs/superpowers/specs/2026-07-12-cast-tuning-shim-design.md).

## Build and release sequence

All commands below assume `gh auth status` succeeds.

Trigger the four builds from the same `main` commit:

```bash
gh workflow run build-android.yml -R aweffr/my-webrtc-builds --ref main
gh workflow run build-ios.yml -R aweffr/my-webrtc-builds --ref main
gh workflow run build-macos-x64.yml -R aweffr/my-webrtc-builds --ref main
gh workflow run build-macos-arm64.yml -R aweffr/my-webrtc-builds --ref main
```

Find the run IDs:

```bash
gh run list -R aweffr/my-webrtc-builds --limit 20
```

After both macOS builds succeed, compose the XCFramework:

```bash
gh workflow run package-macos-xcframework.yml \
  -R aweffr/my-webrtc-builds \
  --ref main \
  -f x64_run_id=MACOS_X64_RUN_ID \
  -f arm64_run_id=MACOS_ARM64_RUN_ID
```

Publish a release only after all five artifact-producing runs succeed:

```bash
gh workflow run publish-release.yml \
  -R aweffr/my-webrtc-builds \
  --ref main \
  -f android_run_id=ANDROID_RUN_ID \
  -f ios_run_id=IOS_RUN_ID \
  -f macos_x64_run_id=MACOS_X64_RUN_ID \
  -f macos_arm64_run_id=MACOS_ARM64_RUN_ID \
  -f xcframework_run_id=XCFRAMEWORK_RUN_ID
```

The release workflow rejects artifacts built from different repository
commits, mismatched WebRTC sources, invalid target metadata, and existing tags.
The combined multi-platform release tag uses
`webrtc-m150.7871.3-<builder-short-sha>-YYYYMMDD-all`.

## Codec behavior

- macOS static libraries bundle the OpenH264 encoder and FFmpeg H.264 decoder.
- Apple frameworks expose VideoToolbox H.264/H.265 implementations.
- Android builds expose MediaCodec H.264/H.265 through WebRTC Java/JNI APIs.
- iOS static builds contain the patched VideoToolbox H.264/H.265 Objective-C
  implementation.
- The project compiles codec capabilities but does not modify WebRTC's runtime
  codec-factory selection. It does not provide H.265 software fallback.

The distributor is responsible for H.264/H.265 patent and product licensing.

## Diagnosing failed Actions runs

Every workflow uploads a diagnostics artifact even when the build fails. Its
name is the binary artifact name plus `-diagnostics`.

Diagnostics contain:

- a complete `tee` copy of the builder log;
- an append-only JSONL phase journal with start, success/failure, and duration;
- runner OS/architecture/image and tool versions;
- disk usage before and after the build;
- the checked-out WebRTC commit and dirty-source status;
- resolved `gn-args.txt` files and the generated-output file list.

The Actions Step Summary shows the failing phase and diagnostics artifact name.
Download diagnostics without opening the browser:

```bash
gh run download RUN_ID \
  -R aweffr/my-webrtc-builds \
  -n webrtc-m150-macos-arm64-diagnostics
```

The builder never logs its environment mapping, so `GITHUB_TOKEN` and other
secrets are not included in command diagnostics.

## Local checks

The local tests do not download or compile WebRTC:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q builder tests
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/*.yml
```

An actual platform build uses the same CLI as Actions:

```bash
python3 -u -m builder build \
  --target macos-arm64 \
  --work-dir build-workspace \
  --dist-dir dist \
  --builder-commit "$(git rev-parse HEAD)"
```

## Sources and licenses

The build design is intentionally small and was informed by:

- [shiguredo-webrtc-build/webrtc-build](https://github.com/shiguredo-webrtc-build/webrtc-build)
- [stasel/WebRTC](https://github.com/stasel/WebRTC)

The repository's own code is Apache-2.0. Vendored patch provenance and hashes
are recorded in [`patches/m150/SOURCES.md`](patches/m150/SOURCES.md). Binary
packages preserve WebRTC and third-party notices.
