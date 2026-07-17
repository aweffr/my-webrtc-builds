# HEVC Screen-Content VideoToolbox Tuning Design

## Goal

Extend the pinned WebRTC M150 macOS CastTuning path so the existing HEVC
VideoToolbox encoder receives the same reproducible casting controls already
available to H.264, plus an explicit spatial-adaptive-QP experiment control.
Build authoritative macOS arm64 and Android artifacts from one builder commit,
then integrate those exact artifacts into `webrtc-screencast-playground` and
prove a Mac HEVC sender to Android receiver path.

This design implements the approved engineering priority:

1. runtime `MaxAllowedFrameQP` for HEVC;
2. real Apple low-latency rate-control selection for HEVC;
3. explicit `SpatialAdaptiveQPLevel` `DEFAULT`/`DISABLE` A/B control;
4. existing realtime and frame-reordering controls on HEVC.

It does not implement HEVC-SCC, ROI, `BaseFrameQP`, undocumented Main 4:4:4
profile strings, the macOS 26 VBR presets, or a custom rate controller.

## Current State

The M150 H.265 patch creates a VideoToolbox HEVC session that merely allows
hardware acceleration. Its `setLowLatency` state controls
`kVTCompressionPropertyKey_RealTime`, not
`kVTVideoEncoderSpecification_EnableLowLatencyRateControl`. It always disables
frame reordering, uses `AverageBitRate`, and does not receive CastTuning options
or the per-factory runtime max-QP state.

The CastTuning encoder factory intercepts H.264 creation only. Consequently,
schema fields such as `hardware_policy`, `allow_frame_reordering`,
`video_toolbox_low_latency_rate_control`, and runtime `max_qp` do not affect
HEVC even when the same configured factory negotiates H.265.

On the accepted Apple M5 Pro / macOS 26.5.2 host, a direct 1920x1080 hardware
probe established these facts:

- ordinary HEVC supports read/write `SpatialAdaptiveQPLevel`, defaulting to
  `kVTQPModulationLevel_Default`;
- ordinary and low-latency HEVC support read/write `MaxAllowedFrameQP`;
- ordinary HEVC defaults `PrioritizeEncodingSpeedOverQuality` to false;
- low-latency HEVC rejects both `SpatialAdaptiveQPLevel` and
  `PrioritizeEncodingSpeedOverQuality` with `kVTPropertyNotSupportedErr`;
- low-latency HEVC forces no frame reordering; and
- the public SDK exposes no screen-content, ROI, palette, or intra-block-copy
  compression property.

## Considered Approaches

### Separate HEVC tuning API

A new Objective-C HEVC-only configuration object would isolate codec behavior,
but it would duplicate CastTuning precedence, hashing, validation, telemetry,
and factory lifecycle. It would also let H.264 and H.265 settings drift. This
approach is rejected.

### Modify the default H.265 encoder globally

Changing every default `RTCVideoEncoderH265` instance would be simple, but it
would change consumers that intentionally use upstream behavior and would make
experiments impossible to bind to an effective CastTuning configuration. This
approach is rejected.

### Extend the configured factory to wrap H.264 and H.265

This is the selected approach. The existing per-factory options, runtime QP
state, evidence channel, validation, and session recreation contract remain the
single control plane. The wrapper creates an option-aware H.265 encoder when
H.265 is selected and otherwise preserves the base factory behavior.

## Configuration Contract

CastTuning schema version becomes `3`; new binaries continue accepting schema
versions 1 and 2 with their exact prior defaults. Schema 3 adds this optional
encoder field:

```json
"video_toolbox_spatial_adaptive_qp": "DEFAULT"
```

Accepted values are `DEFAULT` and `DISABLE`. Absence means no setter call.
`DEFAULT` explicitly sets `kVTQPModulationLevel_Default`; `DISABLE` explicitly
sets `kVTQPModulationLevel_Disable`. Schema 1 and 2 reject the field, and old
binaries reject schema 3, so no binary silently interprets a new configuration
with old semantics.

The existing fields retain their names and gain HEVC behavior:

- `hardware_policy` selects required, preferred, or software-allowed encoder
  specifications;
- `realtime` sets `kVTCompressionPropertyKey_RealTime`;
- `allow_frame_reordering` sets the corresponding VideoToolbox property;
- `video_toolbox_low_latency_rate_control=true` adds the encoder specification
  at session creation and is fail-closed;
- `max_qp` supplies initial and runtime HEVC `MaxAllowedFrameQP` requests; and
- `data_rate_limit_factor`/`data_rate_window_ms` remain incompatible with Apple
  low-latency rate control.

Schema validation rejects any explicit spatial-adaptive-QP value combined with
enabled low-latency rate control. The Apple mode does not expose this property,
including its nominal `DISABLE` value, on the accepted hardware. The ordinary
path may omit the field to retain the encoder default or set either value for a
controlled A/B comparison.

No new public flag is added for
`PrioritizeEncodingSpeedOverQuality=false`: ordinary hardware already defaults
to quality priority and the accepted low-latency encoder rejects the property.
Adding an apparently active flag would not provide a dependable behavior
change. A future flag requires a measured platform matrix and effective-value
telemetry.

## macOS Encoder Architecture

`RTCCastTuningVideoEncoderFactory` imports both encoder classes and intercepts
case-insensitive `H264` and `H265` creation. Both instances receive the same
immutable options dictionary and the same per-factory runtime provider/result
blocks.

The H.265 patch adds an option-aware initializer without changing its existing
initializer. During compression-session creation it:

1. applies the configured hardware policy;
2. adds Apple low-latency rate control only when explicitly true;
3. records a new encoder-session ID and selected encoder ID;
4. configures realtime and frame reordering;
5. applies spatial-adaptive QP only on macOS 15 or later and only when present;
6. applies the pending max QP before the first encoded frame; and
7. prepares the session and emits structured requested/effective evidence.

Explicit low-latency session creation remains fail-closed: a failed requested
session is not retried as an ordinary encoder. Optional spatial-adaptive-QP is
nonfatal when the runtime does not support the key; it emits `unsupported` or
`failed` evidence rather than claiming success.

HEVC runtime max-QP changes use the proven H.264 contract: a new generation is
accepted synchronously by CastTuning, then the encoder replaces only its
VideoToolbox compression session before the next frame. The cap is applied and
read back before the replacement session's first frame. The initial frame is an
IDR, and the existing H.265 bitstream parser supplies actual QP evidence.

Every session and QP event gains codec identity (`H264` or `H265`) so a factory
that advertises both codecs cannot misattribute evidence from negotiation or
fallback encoders.

## Android and Artifact Contract

Android runtime encoder behavior does not change. Android is rebuilt because
the common schema/versioned CastTuning API and packaged Java/JNI surface change,
and the final downstream app must consume artifacts from one builder commit.

Only these hosted builds are required by the user:

- `macos-arm64`;
- `android` arm64-v8a.

The exact workflow artifacts are downloaded without local repacking. The
macOS thin framework is converted only as necessary into the downstream
repository's expected arm64 XCFramework directory shape; its framework binary
and headers must remain byte-identical to the downloaded package. The Android
AAR is copied byte-for-byte. Checksums and the full builder commit are recorded
in downstream provenance files.

## Downstream Integration

`webrtc-screencast-playground` gains an explicit video-codec policy rather than
hard-coded H.264 behavior. The supported values are `H264` and `H265`; the HEVC
experiment configuration selects H.265, while H.264 remains an explicit
compatibility option. Offer/answer manipulation, preferred codec ordering, and
telemetry must agree on the selected codec. Android must not rewrite an H.265
answer to H.264.

The macOS sender continues applying the existing static/motion policy:

- static text: 1 fps and max QP 22;
- motion: 15 fps and max QP 32;
- frame reordering disabled; and
- ordinary HEVC rate control with spatial adaptive QP `DEFAULT` for the primary
  quality experiment.

A separate low-latency HEVC configuration leaves spatial adaptive QP unset and
enables `video_toolbox_low_latency_rate_control`. It is an A/B latency mode, not
the default text-quality mode.

## Telemetry and Failure Policy

The existing requested/effective runtime-QP snapshot remains stable and adds
codec identity. Encoder session events record codec, encoder ID, requested
low-latency mode, requested/effective spatial-adaptive-QP mode, OSStatus,
session ID, and config hash.

The downstream E2E evidence must bind:

- negotiated codec from SDP and sender/receiver stats;
- selected VideoToolbox encoder ID;
- requested/effective max QP and actual HEVC frame QP;
- requested/effective spatial-adaptive-QP mode;
- frame type and encoded bytes;
- Android decoder name; and
- transport route and timestamps.

A mismatch between requested and negotiated codec is a failed experiment, not
a warning. Unsupported optional spatial AQ is observable and may fall back to
the ordinary default; explicit low-latency session creation and required
hardware remain hard failures.

## Verification Gates

Repository tests must prove schema 1/2 compatibility, schema 3 parsing and
validation, hash coverage, H.265 factory interception, exact M150 patch
applicability, runtime max-QP session replacement, codec-tagged evidence, and
binary/public-header contracts.

The final macOS arm64 workflow artifact must pass a real Apple Silicon HEVC
probe covering:

1. ordinary HEVC with spatial AQ `DEFAULT`;
2. ordinary HEVC with spatial AQ `DISABLE`;
3. ordinary HEVC runtime max QP `32 -> 22 -> 32` on distinct sessions; and
4. low-latency HEVC session creation with no spatial-AQ request.

The final Android workflow AAR must pass the existing AAR consumer/emulator
smoke and expose H.265 decoder capability. The downstream completion gate is a
real or emulator Mac-to-Android HEVC session with negotiated H.265, decoded
video, correlated QP evidence, and no H.264 answer rewrite.

## Follow-ups

- Compare `PrioritizeEncodingSpeedOverQuality=false` only after collecting a
  platform support matrix showing a nondefault or measurable behavior change.
- Evaluate Main 4:4:4 only after a documented public API, end-to-end pixel
  format support, and Android decoder capability negotiation exist.
- Evaluate macOS 26 VBR/presets separately because they conflict with Apple
  low-latency rate control and introduce lookahead/VBV latency.
