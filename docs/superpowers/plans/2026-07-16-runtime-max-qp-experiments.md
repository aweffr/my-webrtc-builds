# Runtime Max-QP Experiments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add live VideoToolbox H.264 max-QP control to the M150 macOS SDK and produce a real Mac-to-Android-TV comparison report for static caps 24, 22, 20, and 18.

**Architecture:** Extend the existing transactional CastTuning live-patch model with `max_qp`, then bridge it to one per-factory Objective-C runtime state captured by the configured H.264 encoder. The encoder replaces only its VideoToolbox compression session when the generation changes, applies the cap before that session's first `VTCompressionSessionEncodeFrame`, reads back the effective property, and reports actual parsed frame QP and encoded size through the existing evidence channel. The downstream reference sender supplies the desired static cap, and a focused TURN/UDP runner retains one decoded Android PNG plus correlated QP evidence for each requested value.

**Tech Stack:** C++17, Objective-C++, Apple VideoToolbox, WebRTC M150, Python `unittest`, Swift/XCTest, zsh, Android TV API 31 arm64 emulator, ADB, jq, GitHub Actions/macOS packaging.

**Design:** `docs/superpowers/specs/2026-07-16-runtime-max-qp-design.md`

---

## File Map

### `my-webrtc-builds`

- `overlays/m150/common/api/cast_tuning/cast_tuning_config.h`: public native live-patch field.
- `overlays/m150/common/api/cast_tuning/cast_tuning_controller.{h,cc}`: backend state, merge, ordering, rollback, hash and revision contract.
- `overlays/m150/common/api/cast_tuning/webrtc_cast_tuning_backend.{h,cc}`: runtime-encoder adapter boundary.
- `overlays/m150/common/api/cast_tuning/cast_tuning_config_unittest.cc`: native live update and rollback contracts.
- `overlays/m150/macos/sdk/objc/api/peerconnection/RTCCastTuning.{h,mm}`: Objective-C API, per-factory runtime state and snapshot evidence.
- `patches/m150/cast_tuning_hooks.patch`: exact M150 H.264 encoder hook.
- `tests/test_cast_tuning_overlay.py`: patch-application and transformed-source contract.
- `tools/macos-videotoolbox-probe/main.mm`: real hardware runtime-QP probe.
- `tools/run-macos-videotoolbox-probe.sh`: evidence assertions.
- `README.md`, `README_CN.md`, and CastTuning design/runbook docs: public contract and use example.

### `webrtc-screencast-playground`

- `apps/macos/WebRTCScreencast/WebRTC/StaticClarityRefreshController.swift`: static/motion QP policy.
- `apps/macos/WebRTCScreencast/WebRTC/WebRTCSession.swift`: `RTCCastTuningLivePatch.maxQp` bridge and telemetry snapshot.
- `apps/macos/WebRTCScreencast/Configuration/RuntimeConfiguration.swift`: local experiment cap input.
- `apps/macos/WebRTCScreencastTests/StaticClarityRefreshControllerTests.swift`: transition ordering and cap tests.
- `apps/macos/WebRTCScreencastTests/RuntimeConfigurationTests.swift`: accepted cap range and defaults.
- `scripts/run-static-qp-experiment.sh`: four-case TURN/UDP orchestration and artifact correlation.
- `scripts/test_static_qp_experiment.py`: report-input validation and rendering tests.
- `docs/experiments/2026-07-16-static-max-qp.md`: final measured report and image links.

## Task 1: Add the Native Live Max-QP Contract

**Files:**
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_config.h`
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_controller.h`
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_controller.cc`
- Modify: `overlays/m150/common/api/cast_tuning/webrtc_cast_tuning_backend.h`
- Modify: `overlays/m150/common/api/cast_tuning/webrtc_cast_tuning_backend.cc`
- Test: `overlays/m150/common/api/cast_tuning/cast_tuning_config_unittest.cc`

- [x] **Step 1: Write native tests for live apply and rollback**

Extend `FakeBackend` with an encoder value and failure switch, then add these assertions before implementation:

```cpp
int max_qp = 32;
bool fail_encoder = false;

bool ApplyEncoder(const BackendState& state, std::string* error) override {
  if (fail_encoder) {
    *error = "encoder failed";
    return false;
  }
  max_qp = state.max_qp;
  return true;
}

CastTuningLivePatch qp_patch;
qp_patch.max_qp = 24;
Expect(qp_patch.RequiredScope() == ApplyScope::kLive,
       "max QP should be LIVE");
Expect(controller.ApplyLivePatch(qp_patch).status == ApplyStatus::kApplied,
       "live max QP should apply");
Expect(backend.max_qp == 24 && controller.config().encoder.max_qp == 24,
       "live max QP must reach backend and effective config");

backend.fail_encoder = true;
CastTuningLivePatch rejected_qp;
rejected_qp.max_bitrate_bps = 3500000;
rejected_qp.max_qp = 22;
Expect(controller.ApplyLivePatch(rejected_qp).status == ApplyStatus::kRejected,
       "encoder failure must reject mixed live patch");
Expect(backend.bitrate == 4000000 && backend.max_qp == 24,
       "encoder failure must roll back earlier live setters");
```

- [x] **Step 2: Run the native contract test and verify RED**

Run:

```bash
python3 -m unittest tests.test_cast_tuning_overlay.CastTuningNativeContractTests.test_config_profiles_validation_and_field_trials -v
```

Expected: compilation fails because `CastTuningLivePatch::max_qp`, `BackendState::max_qp`, and `CastTuningBackend::ApplyEncoder` do not exist.

- [x] **Step 3: Implement the minimal common contract**

Add the public/state fields and backend operation:

```cpp
std::optional<int> max_qp;
int max_qp = 0;
virtual bool ApplyEncoder(const BackendState& state,
                          std::string* error) = 0;
```

Make `MergeState` copy `patch.max_qp`, make `MergeConfig` update
`config.encoder.max_qp`, and keep the existing 0 through 51 validation.
Apply operations in this order:

```text
bitrate → sender → encoder → receiver
```

On encoder failure, roll back sender and bitrate. On receiver failure, roll
back encoder, sender, and bitrate. `WebRtcCastTuningBackend` delegates only a
changed value to a nullable `CastEncoderRuntimeAdapter`; changing max QP
without an attached adapter returns `unsupported encoder runtime control`.

- [x] **Step 4: Run targeted and full native tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_cast_tuning_overlay.CastTuningNativeContractTests.test_config_profiles_validation_and_field_trials -v
python3 -m unittest discover -s tests -v
```

Expected: targeted test and all repository tests pass.

- [x] **Step 5: Commit the common contract**

```bash
git add overlays/m150/common/api/cast_tuning
git commit -m "feat: add live max qp tuning contract"
```

## Task 2: Add the Per-Factory macOS Runtime Control

**Files:**
- Modify: `overlays/m150/macos/sdk/objc/api/peerconnection/RTCCastTuning.h`
- Modify: `overlays/m150/macos/sdk/objc/api/peerconnection/RTCCastTuning.mm`
- Modify: `tests/test_cast_tuning_overlay.py`

- [x] **Step 1: Write Objective-C overlay contract assertions**

Add a Python test that requires the public API and private per-factory wiring:

```python
def test_macos_exposes_per_factory_live_max_qp_control(self) -> None:
    header = (ROOT / "overlays/m150/macos/sdk/objc/api/peerconnection/RTCCastTuning.h").read_text()
    implementation = (ROOT / "overlays/m150/macos/sdk/objc/api/peerconnection/RTCCastTuning.mm").read_text()
    self.assertIn("@property(nonatomic, nullable) NSNumber *maxQp;", header)
    self.assertIn("RTCCastTuningEncoderRuntimeState", implementation)
    self.assertIn('options[@"encoder_runtime_qp_provider"]', implementation)
    self.assertIn("ApplyMaxQp", implementation)
    self.assertIn("requestedMaxQp", header)
    self.assertIn("effectiveMaxQp", header)
    self.assertIn("lastEncodedQp", header)
```

- [x] **Step 2: Run the overlay assertion and verify RED**

Run:

```bash
python3 -m unittest tests.test_cast_tuning_overlay.CastTuningNativeContractTests.test_macos_exposes_per_factory_live_max_qp_control -v
```

Expected: failure because the public property and runtime state are absent.

- [x] **Step 3: Implement the runtime state and Objective-C bridge**

Expose the additive API:

```objc
@property(nonatomic, nullable) NSNumber *maxQp;

@property(nonatomic, readonly, nullable) NSNumber *requestedMaxQp;
@property(nonatomic, readonly, nullable) NSNumber *effectiveMaxQp;
@property(nonatomic, readonly) NSString *maxQpApplyState;
@property(nonatomic, readonly) uint64_t maxQpGeneration;
@property(nonatomic, readonly, nullable) NSNumber *maxQpOSStatus;
@property(nonatomic, readonly, nullable) NSNumber *lastEncodedQp;
@property(nonatomic, readonly, nullable) NSNumber *lastKeyFrameQp;
@property(nonatomic, readonly, nullable) NSNumber *lastKeyFrameBytes;
```

Implement `RTCCastTuningEncoderRuntimeState` with an `NSLock`, requested and
effective values, monotonically increasing generation, apply state, OSStatus,
and frame evidence. It supplies two copied blocks in encoder options:

```objc
options[@"encoder_runtime_qp_provider"] = [^NSDictionary *{
  return [runtimeState requestSnapshot];
} copy];
options[@"encoder_runtime_qp_result_handler"] =
    [^(NSDictionary *event) {
      [runtimeState recordEncoderEvent:event];
      [evidence recordEvent:event];
    } copy];
```

Create an `ObjCEncoderRuntimeAdapter` implementing the common
`CastEncoderRuntimeAdapter` and attach it to `WebRtcCastTuningBackend`.
Initialize requested QP from `configuration.nativeConfig.encoder.max_qp`.
Map `patch.maxQp` into native `max_qp`, and copy runtime evidence into
`RTCCastTuningSnapshot`. Make encoder evidence accumulate stable fields rather
than replacing the complete snapshot on every event.

- [x] **Step 4: Verify the Objective-C contract GREEN**

Run:

```bash
python3 -m unittest tests.test_cast_tuning_overlay -v
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [x] **Step 5: Commit the macOS API bridge**

```bash
git add overlays/m150/macos tests/test_cast_tuning_overlay.py
git commit -m "feat: expose macos runtime max qp control"
```

## Task 3: Patch the Exact M150 VideoToolbox Encoder

**Files:**
- Modify: `tests/test_cast_tuning_overlay.py`
- Modify: `patches/m150/cast_tuning_hooks.patch`
- Modify: `patches/m150/SOURCES.md`

- [x] **Step 1: Strengthen the transformed-source test**

Change the exact-source test to apply the H.264 hunk in a temporary checkout,
then assert the transformed file contains all runtime behavior:

```python
subprocess.run([
    "git", "apply", f"--include={relative.as_posix()}",
    str(ROOT / "patches/m150/cast_tuning_hooks.patch"),
], cwd=checkout, check=True, text=True, capture_output=True)
transformed = destination.read_text()
self.assertIn("encoder_runtime_qp_provider", transformed)
self.assertIn("VTSessionCopySupportedPropertyDictionary", transformed)
self.assertIn("kVTCompressionPropertyKey_MaxAllowedFrameQP", transformed)
self.assertIn("VTSessionCopyProperty", transformed)
self.assertIn("encoder_runtime_qp_result_handler", transformed)
self.assertIn('frame.qp = @(_h264BitstreamParser.GetLastSliceQp()', transformed)
```

- [x] **Step 2: Run the transformed-source test and verify RED**

Run:

```bash
python3 -m unittest tests.test_cast_tuning_overlay.CastTuningNativeContractTests.test_h264_hook_patch_applies_to_exact_m150_source -v
```

Expected: failure because the current patch has only session-start max QP.

- [x] **Step 3: Implement the exact M150 encoder hook**

In `RTCVideoEncoderH264.mm`, add `_lastAppliedMaxQpGeneration`. Before the
first pixel-buffer operation in `encode:codecSpecificInfo:frameTypes:`, read
the provider. When its generation changed after the current VideoToolbox
session has encoded a frame, replace that compression session so the new cap
is established before the replacement session's first frame:

```objc
NSDictionary *(^provider)(void) =
    _castTuningOptions[@"encoder_runtime_qp_provider"];
NSDictionary *request = provider ? provider() : nil;
NSNumber *generation = request[@"generation"];
NSNumber *requestedMaxQp = request[@"requested_max_qp"];
```

Query the supported-property dictionary once per compression session. If the
key is supported and read/write, call `VTSessionSetProperty` with a CFNumber,
then call `VTSessionCopyProperty` for readback. Emit one of
`encoder_runtime_qp_applied`, `encoder_runtime_qp_unsupported`, or
`encoder_runtime_qp_failed`, always including requested QP, generation,
OSStatus, encoder ID and encoder-session ID.

After the bitstream parser assigns `frame.qp`, emit
`encoder_qp_sample` for keyframes, including actual QP, keyframe flag and
encoded bytes. The reference sender forces a keyframe immediately after each
static policy transition, so this provides the required generation-bound
experiment evidence without per-frame telemetry. Reset the locally applied
generation when a compression session is destroyed, apply the current
requested value before the replacement session's first frame, and report the
new encoder-session ID with the forced initial IDR.

- [x] **Step 4: Verify patch applicability and all tests GREEN**

Run:

```bash
python3 -m unittest tests.test_cast_tuning_overlay -v
git diff --check
python3 -m unittest discover -s tests -v
```

Expected: the patch applies cleanly to pinned commit
`1f975dfd761af6e5d76d28333191973b258d82a8`; all tests pass.

- [x] **Step 5: Commit the encoder hook**

```bash
git add patches/m150 tests/test_cast_tuning_overlay.py
git commit -m "feat: apply max qp on videotoolbox frame boundaries"
```

## Task 4: Build and Prove the macOS Artifact

**Files:**
- Modify: `tools/macos-videotoolbox-probe/main.mm`
- Modify: `tools/run-macos-videotoolbox-probe.sh`
- Modify: `tests/test_verify.py` if the public-symbol contract changes
- Generated ignored evidence: `evidence/macos-videotoolbox/<sha256>/`

- [x] **Step 1: Extend the hardware probe contract before implementation**

Add probe output assertions requiring three distinct encoder-session IDs and
the runtime sequence 32, 24, and 32:

```jq
(.runtime_qp | map(.requested_max_qp)) == [32,24,32] and
(all(.runtime_qp[]; .apply_state == "applied")) and
(all(.runtime_qp[]; .effective_max_qp == .requested_max_qp)) and
([.runtime_qp[].encoder_session_id] | unique | length) == 3 and
(.runtime_qp[1].actual_qp <= 24)
```

- [x] **Step 2: Run the probe contract test and verify RED**

Run the existing relevant unit/contract test or compile the probe against the
current artifact. Expected: runtime-QP fields are missing.

- [x] **Step 3: Extend the hardware probe implementation**

Supply runtime provider/result blocks, encode three distinct forced keyframes,
and record requested/effective/actual QP, bytes, generation and session ID for
each. Keep the low-latency profile evidence already required by the probe.

- [x] **Step 4: Build the arm64 package from the feature worktree**

Run with the repository's verified snapshot cache and an isolated build root:

```bash
python3 -m builder build \
  --target macos-arm64 \
  --work-dir "$PWD/.local-build/runtime-max-qp" \
  --dist-dir "$PWD/.local-dist/runtime-max-qp" \
  --builder-commit "$(git rev-parse HEAD)"
```

Expected: GN/Ninja, package verification and checksums succeed. If local
snapshot restore cannot complete, dispatch the existing macOS arm64 and x64
GitHub Actions from the same pushed builder commit and download their artifacts.

- [x] **Step 5: Produce or obtain a universal XCFramework and run hardware evidence**

Compose matching x64/arm64 packages with `python3 -m builder merge-macos`, or
use the repository's workflow artifact when x64 is hosted-only. Then run:

```bash
EVIDENCE_DIR="$PWD/evidence/runtime-max-qp" \
  ./tools/run-macos-videotoolbox-probe.sh \
  .local-dist/runtime-max-qp/WebRTC-m150-macos-universal.xcframework.zip
```

Expected: 32 → 24 → 32 applies on three encoder-session IDs without SDP
renegotiation and every keyframe's actual QP is at most its requested cap.

Completed with hosted arm64 run `29484647343`, x64 run `29484649765`, and
corrected composition run `29490786313`. The universal zip SHA-256 is
`81bbe6dd19c79998263125abafdcbac3d14b1fc279ee951c06fc638c305db382`;
both canonical framework binary paths contain `x86_64 arm64`. The real
Apple Silicon probe observed exact actual QP `32 → 24 → 32` on three
distinct encoder sessions.

- [x] **Step 6: Commit the hardware proof tooling**

```bash
git add tools tests/test_verify.py
git commit -m "test: verify runtime videotoolbox max qp"
```

## Task 5: Integrate the Reference Sender and Experiment Input

**Files:**
- Modify: `apps/macos/WebRTCScreencast/WebRTC/StaticClarityRefreshController.swift`
- Modify: `apps/macos/WebRTCScreencast/WebRTC/WebRTCSession.swift`
- Modify: `apps/macos/WebRTCScreencast/Configuration/RuntimeConfiguration.swift`
- Test: `apps/macos/WebRTCScreencastTests/StaticClarityRefreshControllerTests.swift`
- Test: `apps/macos/WebRTCScreencastTests/RuntimeConfigurationTests.swift`
- Modify: `scripts/bootstrap-webrtc.sh` only through local artifact override support; do not commit a machine path.

- [x] **Step 1: Write Swift tests for QP transition ordering**

Change the live-policy closure to receive `(fps, bitrate, maxQp)` and require:

```swift
XCTAssertEqual(
    calls,
    ["apply:1:5000000:22", "force-key-frame"]
)
```

For motion restore require:

```swift
XCTAssertEqual(calls, ["apply:15:5000000:32"])
```

Add runtime configuration tests accepting 24, 22, 20 and 18, rejecting values
outside 0 through 51, and defaulting the reference sender to 24.

- [x] **Step 2: Run focused XCTest cases and verify RED**

Run:

```bash
make test-macos
```

Expected: compile/test failure because the controller and configuration do not
yet expose a static max-QP value.

- [x] **Step 3: Implement the sender policy**

Add optional `static_max_qp` to local runtime JSON with default 24 and retain
dynamic cap 32 as an application constant. Initialize
`StaticClarityRefreshController` with both caps. Apply:

```swift
patch.maxFps = NSNumber(value: maxFPS)
patch.maxBitrateBps = NSNumber(value: maxBitrateBps)
patch.maxQp = NSNumber(value: maxQp)
```

Treat `.applied` as accepted and preserve the existing force-IDR ordering and
retry latch. Sample `RTCCastTuningSnapshot` into sender JSONL so each experiment
can read requested/effective/apply-state/generation/actual-QP evidence.

- [x] **Step 4: Install the newly built XCFramework locally and verify GREEN**

Use environment overrides supported by `scripts/bootstrap-webrtc.sh` to point
at the new local zip, then run:

```bash
make test-macos
make build-macos
```

Expected: all macOS tests pass and the app links the new public API.

- [x] **Step 5: Commit the downstream integration**

```bash
git add apps/macos scripts/bootstrap-webrtc.sh
git commit -m "feat(macos): tune static max qp at runtime"
```

## Task 6: Automate and Execute the Four Static QP Cases

**Files:**
- Create: `scripts/run-static-qp-experiment.sh`
- Create: `scripts/test_static_qp_experiment.py`
- Modify: `Makefile`
- Generated ignored evidence: `artifacts/static-qp-experiment/<run-id>/`

- [x] **Step 1: Write analyzer/renderer tests first**

Create fixture records for requested caps 24, 22, 20 and 18. Require the
analyzer to reject a missing PNG, missing actual QP, mismatched requested QP,
non-relay/UDP path, different encoder-session IDs within a case, and a decoded
image not equal to 1920x1080. Require Markdown rows sorted 24, 22, 20, 18.

- [x] **Step 2: Run the script tests and verify RED**

Run:

```bash
python3 -m unittest scripts/test_static_qp_experiment.py -v
```

Expected: import/file failure because the experiment analyzer is absent.

- [x] **Step 3: Implement focused TURN/UDP orchestration**

For each value in `24 22 20 18`, derive a temporary runtime config containing
`static_max_qp`, then invoke the existing E2E entry point:

```bash
./scripts/run-android-tv-e2e.sh \
  --profile production-relay \
  --source main \
  --runtime-config "$case_config" \
  --run-seconds 25 \
  --output-root "$case_root" \
  --skip-macos-build
```

After stable mode evidence appears, preserve the Android decoded PNG tied to
the first `encoder_qp_sample` for the applied generation. Build one canonical
`experiment.json` containing artifact checksums, WebRTC identity, app commit,
environment, path evidence and the four case records. Never retain the runtime
config or TURN credentials.

- [x] **Step 4: Verify the script unit tests GREEN**

Run:

```bash
python3 -m unittest scripts/test_static_qp_experiment.py -v
make test-scripts
```

Expected: all tests pass.

- [x] **Step 5: Run the real four-case experiment**

Run:

```bash
./scripts/run-static-qp-experiment.sh \
  --runtime-config secrets/runtime.json \
  --output-root artifacts/static-qp-experiment
```

Expected: four successful relay/relay UDP sessions, four 1920x1080 Android
decoded PNGs, and four records with requested, effective and actual QP.

- [x] **Step 6: Commit automation, not raw ignored evidence**

```bash
git add scripts/run-static-qp-experiment.sh scripts/test_static_qp_experiment.py Makefile
git commit -m "test: automate static max qp experiments"
```

## Task 7: Inspect Images, Write the Report, Review, and Close

**Files:**
- Create: `docs/experiments/2026-07-16-static-max-qp.md`
- Create or copy review-sized PNGs under: `docs/experiments/2026-07-16-static-max-qp/`
- Modify: `docs/README.md`
- Modify: `docs/superpowers/specs/2026-07-16-runtime-max-qp-design.md` only for execution findings or follow-ups
- Modify: this plan to check completed steps and record exact commands/results

- [x] **Step 1: Open all four final Android PNGs with `view_image`**

Inspect each at original detail. Record cursor presence, complete 1920x1080
framing, text legibility, fine-line preservation, flat-color banding,
blocking/ringing and any Android UI overlay. Do not infer visual quality solely
from QP or a metric.

- [x] **Step 2: Render the measured Markdown report**

The report must include this evidence table populated from `experiment.json`:

```markdown
| Requested cap | Effective cap | Actual QP | IDR bytes | Route | Android decoded image | Visual assessment |
|---:|---:|---:|---:|---|---|---|
```

Append exactly four measured rows in the order 24, 22, 20, 18; every numeric
cell and image link is copied from the canonical experiment evidence rather
than written as a provisional value.

Also include exact commits/artifact digests, host/emulator context, commands,
evidence binding method, limitations, and a measured recommendation. State
that lower QP is a cap rather than a guaranteed exact output.

- [x] **Step 3: Run the full verification suite**

In `my-webrtc-builds`:

```bash
python3 -m unittest discover -s tests -v
git diff --check
```

In `webrtc-screencast-playground`:

```bash
make verify
./scripts/verify-no-secret-leaks.sh secrets/runtime.json
git diff --check
```

Expected: all commands pass, no credential or pairing code is retained, and
every report image checksum matches the canonical experiment evidence.

- [x] **Step 4: Request a clean-context code review**

Provide the reviewer with the user requirement, design, this plan, both diffs,
build/E2E output, experiment JSON, report and known constraints. Limit review
to requirement alignment and Critical/High correctness, concurrency,
compatibility, observability and verification risks. Apply justified fixes and
repeat at most three rounds.

Three rounds completed. The final review found one High in screenshot/evidence
correlation: historical matching `rtc_stats` could be selected after capture.
The fix accepts only the latest stats record, requires a strictly newer
post-screenshot sample, persists both record indices, and rejects any
generation/session/QP/byte mismatch. The four real cases were rerun after the
fix and retained record pairs `27→28`, `20→21`, `20→21`, and `20→21`.

- [x] **Step 5: Commit documentation and measured evidence**

```bash
git add docs/experiments docs/README.md docs/superpowers
git commit -m "docs: report static max qp experiments"
```

- [x] **Step 6: Completion audit and repository handoff**

Verify every requested cap has one real Android decoded image, actual QP,
`view_image` assessment and report row. Record commits, branch/worktree state,
artifact identity, review outcome and any remaining risk. Merge temporary
branches back to their local main branches only after the evidence and diffs
are clean, then remove temporary worktrees.

Completed on 2026-07-16. Upstream was merged to `main` by merge commit
`41bfaff`; downstream was transplanted onto the public `main` history without
a force-push and published as `f1b02a4`. The corrected universal artifact is
workflow run `29490786313` / SHA-256
`81bbe6dd19c79998263125abafdcbac3d14b1fc279ee951c06fc638c305db382`.
The final downstream report and four 1920×1080 Android images are tracked,
while raw evidence remains under `artifacts/static-max-qp/20260716T100706Z`.
Three review rounds completed and the final High was fixed and rerun. The
remaining explicit limitation is that runtime VideoToolbox hardware evidence
was collected on the accepted arm64 Mac; x64 was compile/package verified and
is present in both canonical universal binary paths, but was not executed on
physical x64 hardware.
