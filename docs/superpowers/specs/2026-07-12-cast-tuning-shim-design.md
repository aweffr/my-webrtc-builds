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

The schema version is `1`. Unknown fields, unknown enum values, invalid ranges,
and invalid combinations are rejected. The built-in profiles are `UPSTREAM`,
`DETAIL_IDLE`, `DETAIL_ACTIVE`, `MOTION`, and `RECOVERY`; `UPSTREAM` is the
default and emits no field trials or setter calls.

The validation contract includes bitrate ordering, dimensions and frame rate,
VideoToolbox ranges, minimum 10-second periodic IDR, jitter/render ranges,
`RTX requires NACK`, one FEC mode, ordered recovery escalation thresholds, and
raw Field Trial opt-in. A raw trial may not replace a typed trial.

## Apply scopes

- `LIVE`: bitrate min/max, frame constraints, content hint, degradation
  preference, receiver minimum jitter, and stale-frame policy.
- `SESSION`: start bitrate/BWE reset and encoder/decoder values whose state is
  created with a media session.
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

Artifact metadata schema `2` records every overlay path/hash and tuning schema
version. macOS composition rejects different headers or overlay manifests.
Packaging verifies public C++/Objective-C headers and symbols, plus Android
classes and public methods.

## Platform integration

On macOS, `RTCCastTuningFactoryBuilder` creates a PeerConnection factory with a
per-factory `Environment` and Field Trials. The encoder wrapper configures
VideoToolbox hardware policy, H.264 profile/level, realtime mode, frame
reordering, optional periodic IDR/slice/frame-delay/QP values, and data-rate
limits. The controller binds PeerConnection, sender, source, and receiver;
initial typed values are applied when their object is attached. Live sender
changes use `SetBitrate`, `RtpParameters`, source adaptation, and content hints.
Keyframes use `RtpSenderInterface::GenerateKeyFrame`.

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
successfully composed XCFramework.
