# WebRTC CastKit

[简体中文](README_CN.md)

WebRTC CastKit is a reproducible WebRTC runtime kit for low-latency screen
casting. It publishes pinned M150 artifacts for Android, iOS, and macOS, and
adds the CastTuning runtime shim to Android and macOS so application teams can
iterate on casting parameters without rebuilding WebRTC each time.

The project is aimed at office-screen-casting integrations where readable text,
fast interaction feedback, and controlled recovery matter more than a generic
one-size-fits-all media preset.

## What it provides

- Pinned WebRTC M150 artifacts: Android arm64, iOS device/simulator arm64,
  macOS x64/arm64 static libraries, and a Windows x64 static library; macOS
  also ships a framework/XCFramework.
- CastTuning schema `1` on Android and macOS: typed APIs, JSON configuration,
  macOS environment overrides, Android Intent overrides, live patches, and
  snapshots.
- Built-in profiles for `UPSTREAM`, `DETAIL_IDLE`, `DETAIL_ACTIVE`, `MOTION`,
  and `RECOVERY`.
- Per-factory Field Trials; sender/receiver controls; VideoToolbox and Android
  MediaCodec low-latency hooks; NACK/RTX/FEC advertisement controls.
- Artifact provenance, overlay hashes, checksums, and diagnostics suitable for
  reproducible release and failure analysis.

The exact upstream source is WebRTC M150 branch-head `7871` commit
`1f975dfd761af6e5d76d28333191973b258d82a8`. The project deliberately does
not accept an arbitrary WebRTC version at build time.

## Use CastTuning

Start from [`examples/cast-tuning-detail-idle.json`](examples/cast-tuning-detail-idle.json).
The effective configuration is merged in this order:

```text
WebRTC upstream defaults → built-in profile → JSON → platform override → live patch
```

`UPSTREAM` is the default: it produces no CastTuning Field Trials and does not
call tuning setters, preserving upstream behavior.

macOS accepts process overrides:

```bash
export CAST_TUNING_CONFIG=/absolute/path/cast-tuning.json
export CAST_TUNING_PROFILE=DETAIL_ACTIVE
export CAST_TUNING_OVERRIDES_JSON='{"sender":{"max_fps":20}}'
```

Use `RTCCastTuningConfiguration`, `RTCCastTuningFactoryBuilder`, and
`RTCCastTuningController` from the macOS framework. Android exposes
`CastTuningConfig`, `CastTuningAndroidConfig`, and `CastTuningController`:

The macOS factory builder requires an explicit hardware-capable
`RTCVideoEncoderFactory` (for example, the VideoToolbox H264 factory). It does
not pull in WebRTC's software codec factory implicitly.

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

| Scope | Examples | How it takes effect |
| --- | --- | --- |
| `LIVE` | bitrate bounds, FPS, content hint, minimum jitter delay | apply a validated live patch |
| `SESSION` | start bitrate/BWE reset, encoder/decoder construction values | recreate the session |
| `FACTORY` | Field Trials, pacer, recovery advertisement | create a new factory and session |

Live patches are prevalidated as a whole. On setter failure, CastTuning rolls
back the old values; an unsuccessful rollback reports
`SESSION_RECREATE_REQUIRED` rather than reporting a partial success.

For the first office-casting experiment, use NACK+RTX, FEC disabled, zero
minimum jitter delay, prerender smoothing disabled, VideoToolbox realtime
enabled, and frame reordering disabled. Change one variable at a time and keep
the session ID, effective config hash, and revision with the measurement.

The full design and boundaries are in
[`docs/superpowers/specs/2026-07-12-cast-tuning-shim-design.md`](docs/superpowers/specs/2026-07-12-cast-tuning-shim-design.md).

## Packages

| Platform | Artifact | Contents |
| --- | --- | --- |
| Android | `webrtc-m150-android-arm64-v8a.tar.gz` | arm64 static library, C++ headers, `webrtc.jar`, CastTuning Java/JNI API |
| iOS | `webrtc-m150-ios.tar.gz` | separate device and simulator arm64 static libraries and headers |
| macOS x64 | `webrtc-m150-macos-x64.tar.gz` | x64 static library, headers, thin `WebRTC.framework`, CastTuning ObjC API |
| macOS arm64 | `webrtc-m150-macos-arm64.tar.gz` | arm64 static library, headers, thin `WebRTC.framework`, CastTuning ObjC API |
| Windows x64 | `webrtc-m150-windows-x64.zip` | x64 `webrtc.lib`, C++ headers, CastTuning common C++ API, `/MT` Release ABI |
| macOS universal | `WebRTC-m150-macos-universal.xcframework.zip` | universal `WebRTC.xcframework` |

Static packages contain resolved GN arguments, metadata schema `2`, patch and
overlay hashes, source/license notices, and `SHA256SUMS`.

## Operational runbook

Build dispatch, XCFramework composition, release publication, local checks,
and diagnosing failed GitHub Actions are documented in
[`docs/runbook.md`](docs/runbook.md).

Every hosted build uploads diagnostics even on failure. They include the full
builder log, JSONL phase journal, per-architecture GN arguments, patch hashes,
source identity, toolchain/disk state, and a full output inventory.

## Codec and licensing notes

- macOS static libraries bundle the OpenH264 encoder and FFmpeg H.264 decoder.
- Apple frameworks use VideoToolbox H.264/H.265; Android uses MediaCodec
  H.264/H.265 through WebRTC Java/JNI APIs.
- Windows bundles the software H.264 encoder/decoder path; its H.265 support is
  limited to the parser/negotiation layer. The Windows static library uses the
  pinned M150 `/MT` CRT contract and has no Windows-specific CastTuning wrapper.
- The project compiles codec capabilities but does not alter upstream runtime
  codec-factory selection or add an H.265 software fallback.

The distributor is responsible for required H.264/H.265 product and patent
licensing. Project code is Apache-2.0; patch provenance is recorded in
[`patches/m150/SOURCES.md`](patches/m150/SOURCES.md).
