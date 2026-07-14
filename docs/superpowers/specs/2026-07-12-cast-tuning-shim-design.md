# WebRTC M150 CastTuning Shim Design

## Goal and boundary

Add a versioned CastTuning overlay to the pinned WebRTC M150 artifacts so a
macOS sender and Android receiver can repeat office-screen-casting latency
experiments without rebuilding WebRTC for every parameter change. The first
CastTuning release requires one new WebRTC build; subsequent experiments use
JSON, macOS process environment overrides, Android Intent overrides, live
patches, or session/factory recreation.

This repository supplies the shim, platform bindings, build integration,
artifact validation, and telemetry primitives. It does not add a debug UI,
remote configuration service, casting application, cross-end recovery
protocol, or invasive GoogCC/FrameBuffer algorithm changes. End-to-end P50 and
P95 latency remain downstream acceptance targets after a real sender and
receiver integrate the artifact.

## Configuration model

`CastTuningConfig` is the single effective configuration. Precedence is fixed:

1. WebRTC upstream defaults
2. built-in profile
3. base JSON
4. macOS environment or Android Intent override
5. live patch

The current schema version is `2`. New binaries also accept legacy schema `1`
with its original defaults; schema `1` neither accepts nor enables the new
VideoToolbox low-latency rate-control setting. Unknown fields, unknown enum
values, invalid ranges, and invalid combinations are rejected. The built-in
profiles are `UPSTREAM`, `DETAIL_IDLE`, `DETAIL_ACTIVE`, `MOTION`, and
`RECOVERY`; `UPSTREAM` is the default and emits no field trials or setter
calls. New examples and application configurations use schema `2`; old
binaries reject schema `2` rather than silently interpreting new semantics.

The validation contract includes bitrate ordering, dimensions and frame rate,
VideoToolbox ranges and low-latency rate-control consistency, minimum
10-second periodic IDR, jitter/render ranges,
`RTX requires NACK`, one FEC mode, ordered recovery escalation thresholds, and
raw Field Trial opt-in. A raw trial may not replace a typed trial.

`encoder.video_toolbox_low_latency_rate_control` is an optional schema `2`
typed Boolean. It is unset for `UPSTREAM` and defaults to `true` for
`DETAIL_IDLE`, `DETAIL_ACTIVE`, `MOTION`, and `RECOVERY`. Schema `1` and an
unset schema `2` `UPSTREAM` configuration preserve exact upstream session
creation; `true` requires creation with
`kVTVideoEncoderSpecification_EnableLowLatencyRateControl`; `false` explicitly
uses the ordinary VideoToolbox encoder path. This setting is implemented only
in the macOS x64/arm64 framework artifacts and their universal XCFramework;
the iOS artifact remains unchanged in this release.

Schema `2` treats enabled VideoToolbox low-latency rate control and
`data_rate_limit_factor`/`data_rate_window_ms` as mutually exclusive. Its
low-latency profiles leave both hard-window fields unset and use the
WebRTC/GoogCC target through `AverageBitRate`; validation rejects an explicit
combination. Schema `1` retains the previous `DataRateLimits` behavior.

Schema `1` profiles retain H.264 Constrained Baseline level 4.1. Schema `2`
non-`UPSTREAM` profiles use Constrained High level 4.1 when low-latency rate
control is enabled. Callers may explicitly select Constrained Baseline as a
compatibility request even when low-latency rate control is enabled. Runtime
verification compares the negotiated SDP profile with the first encoded SPS.
A mismatch is an explicit structured compatibility event containing the
expected and actual profile family; it is not silently ignored and does not by
itself fail the session.

The mismatch policy is `WARN_AND_CONTINUE`: record the event once per encoder
session, expose a persistent `profile_mismatch` warning in telemetry/snapshot,
and continue delivering the low-latency bitstream. The encoder does not rewrite
SDP, automatically recreate an ordinary VideoToolbox session, or silently turn
off low-latency rate control. A caller that requires strict Baseline output
must disable the low-latency setting; receiver decode failure remains an
application/recovery signal rather than an inferred sender-side failure.

## Apply scopes

- `LIVE`: bitrate min/max, frame constraints, content hint, degradation
  preference, receiver minimum jitter, and stale-frame policy.
- `SESSION`: start bitrate/BWE reset, VideoToolbox low-latency rate control,
  and encoder/decoder values whose state is created with a media session.
- `FACTORY`: Field Trials and pacer/recovery advertisement values captured by a
  per-factory environment.

A live patch is validated as one candidate before any setter is called. Setter
failure rolls previously applied values back. If rollback also fails, the
result is `SESSION_RECREATE_REQUIRED`; a partial success is never reported as
success. Successful application increments the session revision and changes a
hash covering every typed and raw setting.

## Overlay architecture

Project-owned files live below `overlays/m150/`:

- `common/api/cast_tuning`: C++ configuration, controller, WebRTC backend,
  recovery state machine, and asynchronous JSONL sink.
- `macos`: Objective-C API and the VideoToolbox-aware factory/controller.
- `android`: Java/JNI API, Intent adapter, receiver controls, and decoder
  factory.

`patches/m150/cast_tuning_hooks.patch` contains only GN wiring and the hooks
that cannot be supplied as new files. The builder applies the existing M150
patch set first, checks and applies the hook patch, then copies overlay files.
Missing groups and destination collisions fail immediately. CastTuning is
included only in macOS x64/arm64 and Android; iOS remains unchanged.

Artifact metadata schema `2` records every overlay path/hash and the current
tuning schema version (`2`). macOS composition rejects different headers or
overlay manifests.
Packaging verifies public C++/Objective-C headers and symbols, plus Android
classes and public methods.

## Platform integration

On macOS, `RTCCastTuningFactoryBuilder` creates a PeerConnection factory with a
per-factory `Environment` and Field Trials. The encoder wrapper configures
VideoToolbox hardware policy, H.264 profile/level, realtime mode, frame
reordering, low-latency rate control at compression-session creation, optional
periodic IDR/slice/frame-delay/QP values, and mode-compatible rate control. The controller
binds PeerConnection, sender, source, and receiver;
initial typed values are applied when their object is attached. Live sender
changes use `SetBitrate`, `RtpParameters`, source adaptation, and content hints.
Keyframes use `RtpSenderInterface::GenerateKeyFrame`.

Low-latency rate control is fail-closed when explicitly enabled. If
VideoToolbox cannot create the requested encoder, encoder startup fails and
reports the original `OSStatus`; it must not retry without the specification.
Successful creation records the selected encoder ID and configured/encoded
H.264 profile evidence because `UsingHardwareAcceleratedVideoEncoder` is not
queryable for Apple's RTVC encoder on all supported systems.

On Android, the controller configures the per-factory Field Trials and
RTCConfiguration, exposes minimum jitter delay through Java/JNI, and creates a
low-latency decoder factory. On API 30+, the decoder requests
`MediaFormat.KEY_LOW_LATENCY`; a rejected configure releases and recreates the
codec, removes that key, and retries exactly once. The Intent adapter accepts a
profile and override JSON while preserving the same precedence as macOS.

Recovery Field Trials control NACK history, RTX, and FEC advertisement without
replacing WebRTC's retransmission algorithms. A separate deterministic state
machine emits `PLI_REQUESTED`, `DECODER_RECREATE_REQUIRED`, and
`SENDER_RESET_AND_KEYFRAME_REQUIRED`; the embedding application performs those
actions and any cross-end signalling.

## Telemetry and failure policy

Each controller allocates a session ID, effective config hash, and monotonically
increasing revision. When `telemetry.jsonl_path` is configured, controller
events are queued and written by a dedicated thread so file I/O does not run on
media threads. Events carry schema, timestamp, session, hash, revision, type,
and payload. Metric adapters must represent unavailable values as `null` and
include an unavailable reason.

Optional platform capabilities may fall back and log the reason. Explicit hard
constraints such as `REQUIRE_HARDWARE` are session-creation failures. Disk
telemetry failure is observable but must never block media processing.

## Verification gate

The repository contract tests cover profile mapping, JSON merge/validation,
Field Trials, apply scopes, transactional rollback, config hash/revision,
recovery escalation, ordered JSONL, Android configuration sources, overlay
conflicts/hashes, metadata schema `2`, package layout, and required public APIs.
Release readiness additionally requires patch dry-runs, real Android and both
macOS architecture builds, native test target execution on macOS, and a
successfully composed XCFramework. VideoToolbox validation additionally checks
that the binary references the low-latency encoder specification and uses a
hardware-capable Mac probe to correlate successful session creation, selected
encoder ID, negotiated H.264 profile, and encoded SPS profile.
