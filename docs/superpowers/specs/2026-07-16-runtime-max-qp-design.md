# Runtime Max-QP Control and Static Quality Experiment Design

## Goal

Extend the pinned M150 macOS CastTuning API so a screen-casting sender can
change VideoToolbox H.264 `MaxAllowedFrameQP` without SDP renegotiation or
recreating the WebRTC encoder object. The implementation may recreate the
underlying VideoToolbox compression session when required by the hardware.
Use that control to compare static-screen caps 24, 22, 20, and 18 in the real
Mac sender to Android TV receiver path, preserving the received image and the
actual encoded QP for every case in a reviewable Markdown report.

## Scope

This change covers the macOS VideoToolbox H.264 encoder, the shared CastTuning
live-patch model, Objective-C API and telemetry, macOS artifact production,
the existing `webrtc-screencast-playground` sender automation, and local
Mac-to-Android-TV-emulator experiments.

It does not add a generic WebRTC RTP encoding parameter, change SDP, use
per-frame `BaseFrameQP`, change Android encoder behavior, introduce a quality
gate, or optimize motion smoothness. Dynamic content remains 15 fps and
5 Mbps with the existing loose cap of 32. Static content remains 1 fps and
5 Mbps and forces an IDR after requesting the selected static cap.

## Current State

`EncoderConfig.max_qp` is parsed and included in the factory configuration,
but `CastTuningLivePatch` has no `max_qp`. The macOS H.264 hook consequently
sets `kVTCompressionPropertyKey_MaxAllowedFrameQP` only while configuring a
new compression session. The existing static experiment therefore retains
the global cap of 32 and has produced an actual static QP of 26.

M150's generic `VideoEncoderConfig.qpMax` path is unsuitable for runtime
switching because `VideoStreamEncoder::RequiresEncoderReset` treats a QP-cap
change as an encoder reset. Apple `BaseFrameQP` is also unsuitable because it
disables standard rate control and must be supplied for every frame in the
session.

## Considered Approaches

### 1. Reconfigure generic `VideoEncoderConfig.qpMax`

This would look natural at the WebRTC API layer, but M150 releases and
reinitializes the encoder when `qpMax` changes. Repeated static/motion
transitions would create new VideoToolbox sessions, force recovery work, and
make the requested low-latency transition less predictable. This approach is
rejected.

### 2. Set `kVTEncodeFrameOptionKey_BaseFrameQP` per frame

This offers exact frame-level requests, but Apple documents that it disables
normal rate control, ignores bitrate and QP-bound properties, and must be used
on every frame. This conflicts with the existing 5 Mbps transport policy and
is rejected.

### 3. Maintain per-factory runtime `MaxAllowedFrameQP` state

This is the selected approach. CastTuning already establishes a per-factory
boundary shared by its configuration, encoder factory, H.264 encoder, and
controller evidence object. A small runtime-control object will carry the
requested QP cap and generation from the controller to encoders created by
that factory. The H.264 encoder applies a changed generation immediately
before encoding the next frame, reads the property back, and records the
result. On ordinary Apple H.264 hardware the encoder recreates only its
VideoToolbox compression session first, because real-hardware experiments
found that post-first-frame property writes are acknowledged but do not affect
bitstream QP. No standard RTP API, SDP renegotiation, WebRTC encoder-object
recreation, or process-global registry is needed.

## Public Contract

`CastTuningLivePatch` gains optional `max_qp`, and
`RTCCastTuningLivePatch` gains nullable `maxQp`. Values use the existing
H.264 range 0 through 51. A live patch containing `maxQp` updates the
requested per-factory state and participates in the configuration hash and
revision.

The apply result means the runtime request was accepted. Hardware effect is
reported separately because it occurs at the encoder's next frame boundary.
The snapshot exposes:

- requested max QP;
- effective max QP read back from VideoToolbox;
- apply state: `pending`, `applied`, `unsupported`, or `failed`;
- request generation;
- last VideoToolbox `OSStatus`;
- active encoder-session ID;
- encoder-session ID on which the requested generation was applied;
- latest encoded QP and the latest keyframe QP and byte size;
- generation and encoder-session ID associated with the latest QP sample.

Unsupported or failed QP control does not terminate the stream. It retains the
last effective cap and emits explicit telemetry. A supported cap change may
replace the underlying VideoToolbox compression session and therefore changes
the observable encoder-session ID.
Other synchronous live-patch setters retain their existing rollback contract.

## Components and Data Flow

`RTCCastTuningConfiguration` owns one thread-safe encoder runtime state next
to its existing encoder evidence object. `RTCCastTuningFactoryBuilder` passes
the state to every H.264 encoder created by that configured factory, and
`RTCCastTuningController` passes an adapter to the common backend.

For a static transition:

1. The application submits one live patch containing 1 fps, 5 Mbps, and the
   selected static max QP.
2. The controller validates the candidate, updates ordinary sender controls,
   and publishes the requested QP and a new generation.
3. The application requests an IDR through the existing controller API.
4. Before its next `VTCompressionSessionEncodeFrame` call, the H.264 encoder
   sees the new generation. If the active compression session has already
   encoded a frame, it recreates that session, then checks property support,
   sets `MaxAllowedFrameQP`, and reads the value back before the replacement
   session's first frame.
5. The same frame is encoded with the new cap as the replacement session's
   initial IDR; no separate SDP or peer-connection operation occurs.
6. The H.264 bitstream parser records the frame's actual slice QP. Telemetry
   correlates request generation, effective cap, actual QP, frame type,
   encoded byte count, and encoder-session ID.

For motion recovery, the application applies 15 fps, 5 Mbps, and max QP 32
before forwarding the resumed motion frame. The cap generation causes the
same controlled compression-session replacement, so the first resumed frame
is an IDR governed by the motion cap.

## Capability and Failure Handling

After VideoToolbox creates a compression session, the encoder queries
`VTSessionCopySupportedPropertyDictionary` for
`MaxAllowedFrameQP`, including read/write status and any advertised value
range. It still checks the return value of `VTSessionSetProperty` and then
uses `VTSessionCopyProperty` for effective-value evidence.

If no session exists, the request remains pending and is applied when the
next session is configured. If the property is unsupported, the state becomes
`unsupported`. If setting or reading it fails, the state becomes `failed` and
records the numeric `OSStatus`. The sender continues with the last known
effective value. These states are observable and are not silently reported as
hardware success.

## Experiment Contract

The official local acceptance environment is one Apple Silicon Mac and the
existing Android TV 1080p arm64 emulator. The sender captures the Mac main
display with the cursor visible. Extension-display behavior is out of scope.

The experiment runs four otherwise identical static cases in this order:

1. max QP 24;
2. max QP 22;
3. max QP 20;
4. max QP 18.

Each case must preserve:

- the decoded 1920x1080 Android receiver PNG;
- a machine-readable metrics/evidence record containing requested cap,
  effective cap, actual encoded QP, frame type, encoded bytes, bitrate, FPS,
  route, timestamps, and encoder-session ID;
- enough sender/receiver logs to bind the PNG to the encoded frame evidence.

The four images must be opened with `view_image` and assessed for legibility,
visible block/ringing artifacts, cursor presence, cropping, overlays, and
unexpected receiver UI. The report records observations rather than enforcing
a pass/fail quality threshold. The route used for the primary comparison is
TURN/UDP; a Direct/UDP control run may be retained when the existing runner
can produce it without changing the image contract.

The Markdown report lives under the screencast playground's `docs/` tree and
contains a row for every cap with requested/effective/actual QP, encoded size,
route, image link, and visual assessment. It also states the exact WebRTC
artifact identity, application commit, commands, environment, limitations,
and a recommendation for the default static cap.

## Verification

The shared C++ tests cover validation, merge, scope, revision/hash, backend
application, and failure behavior. Overlay contract tests first prove that
the exact M150 hook patch exposes the runtime control and telemetry. The
patched exact source must pass `git apply --check`.

A macOS arm64 hardware probe proves that 32 to 24 to 32 changes are accepted,
that each changed generation uses a new encoder-session ID, and that effective-
value readback and actual bitstream QP are observable. The final framework then runs through the
real screencast application and Android emulator for all four requested caps.

## Execution Findings

On 2026-07-16, a real Apple Silicon probe on `Mac17,8` / macOS 26.5.2 showed
that the ordinary `com.apple.videotoolbox.videoencoder.ave.avc` encoder
advertises `MaxAllowedFrameQP` as read/write and returns successful set and
readback results after encoding starts, but a `32 → 24` update left the next
IDR at actual slice QP 32. A reverse probe starting the session at 24 produced
actual IDR QP 24, confirming both the parser and the property itself; the
hardware only honored the cap established before that session's first frame.

The Apple low-latency `com.apple.videotoolbox.videoencoder.h264.rtvc` encoder
did not advertise `MaxAllowedFrameQP` on this host. It advertised
`SupportsBaseFrameQP`, but Apple documents that `BaseFrameQP` disables standard
rate control and ignores average bitrate/data-rate limits. That path remains
out of scope. The selected implementation therefore keeps the stable live API
but performs a controlled VideoToolbox compression-session replacement for
each changed max-QP generation.

The final local arm64 package was built from builder commit
`807ed27450a27528c332969019450dc8819b35d5`. Its XCFramework zip SHA-256 is
`9b551376bfbd056b70d8b75142efa697a049fcff9a27f6a2a4694a847b140ba4`.
The real hardware probe produced three distinct sessions for `32 → 24 → 32`,
with effective and actual QP exactly equal to each requested value. Hosted
macOS arm64 run `29484647343` completed successfully from the same commit;
hosted x64 run `29484649765` also completed successfully from that commit.

The first hosted composition exposed an existing framework-layout defect:
the top-level binary was fat while `Versions/A/WebRTC` remained x64-only.
Composer commit `505d58fe845592238fea03ff82ba5388caa05327` fixed the source
of that inconsistency by writing the fat binary to the canonical versioned
path and restoring the standard top-level symlink. Hosted composition run
`29490786313` then produced the corrected universal XCFramework with SHA-256
`81bbe6dd19c79998263125abafdcbac3d14b1fc279ee951c06fc638c305db382`.
Both the top-level and `Versions/A` paths report `x86_64 arm64`, and the public
header contains the applied-session and sample-generation/session evidence
fields. A real Apple Silicon probe against that exact universal archive again
produced three distinct sessions for `32 → 24 → 32`, with exact actual QP
`32 → 24 → 32`.

The downstream reference app commit `f90e985c8b0d4488fa2fb325192ee6a17f008176`
then completed four independent Mac main-display to Android TV API 31 arm64
emulator sessions through verified `relay/relay + UDP`. Requested, effective,
and actual IDR QP were exactly `24/24/24`, `22/22/22`, `20/20/20`, and
`18/18/18`. The automation accepted only the latest `rtc_stats`, captured the
Android image, waited for a strictly newer metrics record, and required the
same generation, applied/sample encoder-session IDs, QP, and encoded byte
count across that window. The retained record pairs were `27→28`, `20→21`,
`20→21`, and `20→21` respectively. Raw evidence is retained under
`artifacts/static-max-qp/20260716T100706Z` in the screencast playground.

All four Android images were 1920×1080 and were inspected at original detail.
The measured report recommends static Max QP 22 as the default engineering
tradeoff while preserving motion Max QP 32; QP 20 remains an optional
quality-biased setting and QP 18 is not the default. VMAF is retained as a
reference column only because capture and receive images are not strict
frame-timestamp matches and the four screen contents are not identical.

The repository's full unit suite, targeted native tests, macOS build/package
verification, downstream build/tests, and E2E runner must pass before the
experiment report is considered complete.

## Release and Follow-ups

This feature requires new macOS arm64 and x64 artifacts and a universal
XCFramework from one builder commit. It may be published as a macOS-scoped
pre-release; Android AAR runtime behavior is unchanged, though Android common
overlay tests still run for compatibility.

Choosing a production default below 24 is not part of the implementation
contract. The report will recommend a value only from the measured QP,
encoded-size, stability, and visual evidence. Content-aware target QP,
per-region quality, and Apple `BaseFrameQP` remain out of scope.
