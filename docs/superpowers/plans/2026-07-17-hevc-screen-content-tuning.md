# HEVC Screen-Content Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reproducible HEVC VideoToolbox CastTuning controls, publish matching macOS arm64 and Android artifacts, and integrate them into a verified Mac-to-Android H.265 screencast path.

**Architecture:** Keep CastTuning as the single versioned control plane, extend its configured macOS encoder factory to construct option-aware H.264 and H.265 encoders, and reuse the per-factory runtime max-QP state for either negotiated codec. Add only one schema-3 setting for spatial adaptive QP, then install the exact hosted arm64 framework and AAR downstream, where one codec policy drives offer/answer handling, telemetry, and E2E verification.

**Tech Stack:** C++17, Objective-C++, Apple VideoToolbox, WebRTC M150 patch overlays, Python `unittest`, Swift/XCTest, Java/JUnit, Gradle, shell verifiers, GitHub Actions, GitHub CLI, Android TV API 31 arm64 emulator.

**Design:** `docs/superpowers/specs/2026-07-17-hevc-screen-content-tuning-design.md`

**Execution constraint:** Work directly on each repository's `main`; do not create a branch or worktree. Preserve the downstream repository's existing local commit ahead of `origin/main`.

---

## File map

### `my-webrtc-builds`

- `overlays/m150/common/api/cast_tuning/cast_tuning_config.{h,cc}`: schema-3 enum, field, defaults, validation, and string conversion.
- `overlays/m150/common/api/cast_tuning/cast_tuning_json.cc`: parse the new encoder field only for schema 3.
- `overlays/m150/common/api/cast_tuning/cast_tuning_controller.cc`: include the field in the effective-config hash.
- native contract tests: schema compatibility, validation, and hash coverage.
- `overlays/m150/macos/sdk/objc/api/peerconnection/RTCCastTuning.{h,mm}`: H.265 factory interception, option bridge, codec-tagged evidence.
- `patches/m150/h265_ios.patch` and `patches/m150/cast_tuning_hooks.patch`: exact M150 option-aware H.265 implementation.
- `tests/test_cast_tuning_overlay.py`: transformed exact-source and bridge contracts.
- `builder/verify.py`, `tests/test_verify.py`: public/binary feature verification.
- `tools/macos-videotoolbox-probe/*`: HEVC normal/spatial/runtime-QP/low-latency hardware cases.
- `smoke/android-aar/app/src/main/java/dev/aweffr/webrtcsmoke/MainActivity.java`:
  require H.265 capability from the packaged Android decoder factory.

### `webrtc-screencast-playground`

- bootstrap/checksum/verifier scripts: exact hosted artifact pin and arm64-only framework contract.
- bundled macOS/Android runtime config: synchronized schema-3 HEVC tuning.
- macOS codec factory/policy/session and tests: selected H.264 or H.265 behavior.
- Android receiver codec/answer/fatal policy and tests: selected H.264 or H.265 behavior.
- diagnostics verifiers: expected-codec-aware E2E evidence.

## Task 1: Add the schema-3 spatial-adaptive-QP contract

**Files:**
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_config.h`
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_config.cc`
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_json.cc`
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_controller.cc`
- Test: `overlays/m150/common/api/cast_tuning/cast_tuning_config_unittest.cc`
- Test: `overlays/m150/common/api/cast_tuning/cast_tuning_json_contract_test.cc`
- Test: `tests/test_metadata.py`

- [x] **Step 1: Write failing native schema tests**

Require schema 3 while preserving schema 1/2 behavior:

```cpp
Expect(kTuningSchemaVersion == 3, "current schema must be version 3");
const auto v2 = CastTuningConfig::ForProfile(Profile::kDetailIdle, 2);
Expect(!v2.encoder.video_toolbox_spatial_adaptive_qp,
       "schema 2 must not invent spatial AQ");
```

Parse schema-3 `DEFAULT` and `DISABLE`; reject an unknown value, schema 2 with
the new field, and low-latency rate control combined with either spatial mode.

- [x] **Step 2: Run the native contract and verify RED**

```bash
python3 -m unittest tests.test_cast_tuning_overlay.CastTuningNativeContractTests.test_config_profiles_validation_and_field_trials -v
```

Expected: compilation/assertion failure because schema 3, the enum, and field
do not exist.

- [x] **Step 3: Implement the minimal typed field and parser**

```cpp
inline constexpr int kTuningSchemaVersion = 3;
enum class SpatialAdaptiveQpMode { kDefault, kDisable };
std::optional<SpatialAdaptiveQpMode> video_toolbox_spatial_adaptive_qp;
```

Only schema 3 accepts the JSON field. Add it to the canonical hash and reject
the low-latency combination with the exact validation error documented in the
design. Do not add profile defaults.

- [x] **Step 4: Verify GREEN and compatibility**

```bash
python3 -m unittest tests.test_cast_tuning_overlay tests.test_metadata -v
python3 -m unittest discover -s tests -v
git diff --check
```

- [x] **Step 5: Commit the schema contract**

```bash
git add overlays/m150/common/api/cast_tuning builder/metadata.py builder/package.py tests/test_metadata.py
git commit -m "feat: add schema 3 spatial aq tuning"
```

## Task 2: Route CastTuning options to H.265

**Files:**
- Modify: `overlays/m150/macos/sdk/objc/api/peerconnection/RTCCastTuning.mm`
- Modify: `tests/test_cast_tuning_overlay.py`

- [x] **Step 1: Write a failing factory bridge test**

```python
self.assertIn('caseInsensitiveCompare:@"H265"', implementation)
self.assertIn('RTCVideoEncoderH265', implementation)
self.assertIn('initWithCodecInfo:info castTuningOptions:_options', implementation)
self.assertIn('@"video_toolbox_spatial_adaptive_qp"', implementation)
self.assertIn('@"codec_name"', implementation)
```

- [x] **Step 2: Run the focused test and verify RED**

```bash
python3 -m unittest tests.test_cast_tuning_overlay.CastTuningNativeContractTests.test_macos_exposes_hevc_cast_tuning -v
```

- [x] **Step 3: Implement the option bridge and factory interception**

Import `RTCVideoEncoderH265.h`; map the enum to `DEFAULT` or `DISABLE`; intercept
H.265 with the same immutable options used by H.264. Keep all other codecs
delegated to the base factory and retain codec identity in encoder evidence.

- [x] **Step 4: Verify bridge GREEN and commit**

```bash
python3 -m unittest tests.test_cast_tuning_overlay -v
python3 -m unittest discover -s tests -v
git add overlays/m150/macos tests/test_cast_tuning_overlay.py
git commit -m "feat: route cast tuning to hevc encoder"
```

## Task 3: Patch the exact M150 H.265 VideoToolbox encoder

**Files:**
- Modify: `tests/test_cast_tuning_overlay.py`
- Modify: `patches/m150/h265_ios.patch`
- Modify: `patches/m150/cast_tuning_hooks.patch`
- Modify: `patches/m150/SOURCES.md`

- [x] **Step 1: Add a transformed H.265 source test before patch changes**

Apply prerequisite patches in target order, then require the transformed H.265
header/implementation to contain `castTuningOptions`, Apple low-latency rate
control, spatial adaptive QP, supported-property/readback checks, runtime max-QP
provider/result blocks, and `codec_name=H265` events.

- [x] **Step 2: Run the transformed-source test and verify RED**

```bash
python3 -m unittest tests.test_cast_tuning_overlay.CastTuningNativeContractTests.test_h265_hook_patch_applies_to_exact_m150_source -v
```

- [x] **Step 3: Add the option-aware initializer and session specification**

Keep the old initializer by delegating to empty options. Build macOS encoder
specifications from `hardware_policy`; add low-latency rate control only for
explicit true and do not retry an explicitly requested low-latency session as
ordinary.

- [x] **Step 4: Add session properties and effective evidence**

Apply realtime and frame reordering. On macOS 15+, map `DEFAULT`/`DISABLE` to
the public QP modulation constants, check support, set/read back, and emit
codec-tagged state/OSStatus. Older/unsupported runtimes continue with explicit
unsupported evidence.

- [x] **Step 5: Port runtime max-QP session replacement**

For a changed generation, replace only the H.265 compression session before
the next frame. Apply/read back the cap before first encode; emit actual H.265
keyframe QP/bytes with the same generation and session ID.

- [x] **Step 6: Verify exact patch order GREEN and commit**

```bash
python3 -m unittest tests.test_cast_tuning_overlay -v
python3 -m unittest discover -s tests -v
git diff --check
git add patches/m150 tests/test_cast_tuning_overlay.py
git commit -m "feat: tune videotoolbox hevc sessions"
```

## Task 4: Extend binary verification and real HEVC hardware probe

**Files:**
- Modify: `builder/verify.py`
- Modify: `tests/test_verify.py`
- Modify: `tools/macos-videotoolbox-probe/main.mm`
- Modify: `tools/run-macos-videotoolbox-probe.sh`
- Modify: `smoke/android-aar/app/src/main/java/dev/aweffr/webrtcsmoke/MainActivity.java`
- Modify: `.github/workflows/build-android.yml`
- Modify: public documentation files

- [x] **Step 1: Write failing verifier/probe assertions**

Require the H.265 option-aware API and linked feature symbols. Require the AAR
consumer smoke to find H.265 as well as H.264. Probe evidence
must include normal `DEFAULT`, normal `DISABLE`, low-latency, and H.265 runtime
QP `32 -> 22 -> 32` on three distinct encoder sessions.

- [x] **Step 2: Run focused tests and verify RED**

```bash
python3 -m unittest tests.test_verify -v
bash -n tools/run-macos-videotoolbox-probe.sh
```

- [x] **Step 3: Implement verifier and probe cases**

Use the packaged framework API for runtime QP. Record framework SHA,
architecture, OS/hardware, codec, encoder/session IDs, requested/effective
feature state, QP, bytes, and errors.

- [x] **Step 4: Run the full local gate**

```bash
python3 -m compileall -q builder tests
python3 -m unittest discover -s tests -v
actionlint .github/workflows/*.yml
git diff --check
```

- [x] **Step 5: Run clean-context review, fix accepted Critical/High findings, and commit**

```bash
git add builder/verify.py tests/test_verify.py tools README.md README_CN.md docs
git commit -m "test: verify hevc videotoolbox tuning"
```

## Task 5: Build and download authoritative hosted artifacts

**Files:**
- Modify: this plan's `Execution findings` with immutable run IDs and hashes.

- [ ] **Step 1: Push the complete builder commit on main**

```bash
git status --short --branch
git push origin main
```

- [ ] **Step 2: Dispatch only the requested workflows**

Dispatch `build-macos-arm64.yml` and `build-android.yml` for the same full
builder SHA. Record run IDs and verify each run's head SHA before waiting.

- [ ] **Step 3: Wait for both Actions runs**

Poll `gh run view <id> --json status,conclusion,headSha,url,jobs`. On failure,
inspect logs, reproduce with a failing test where possible, fix on main, rerun
the local gate, push, and dispatch both platforms again so commits never mix.

- [ ] **Step 4: Download without repacking**

Use `gh run download` into an ignored directory. Verify package metadata builder
commit, arm64 framework architecture, AAR members, and SHA-256.

- [ ] **Step 5: Run runtime gates on exact downloads**

```bash
tools/run-macos-videotoolbox-probe.sh <downloaded-arm64-framework-archive>
tools/android-aar-smoke.sh <android-run-id>
```

Expected: HEVC hardware cases pass; Android reports `AAR_SMOKE_OK` and H.265
decoder capability from the exact AAR.

- [ ] **Step 6: Record immutable evidence and commit**

Append run IDs, head SHA, artifact names/hashes, M5 Pro/macOS identity, Android
ABI/API/decoder identity, and probe results. Do not commit binaries or logs.

## Task 6: Pin the exact new artifacts downstream

**Files:**
- Modify: `/Users/aweffr/developer/aweffr/webrtc-screencast-playground/scripts/bootstrap-webrtc.sh`
- Modify: `/Users/aweffr/developer/aweffr/webrtc-screencast-playground/artifacts/SHA256SUMS`
- Modify: downstream bootstrap verifier fixtures and documentation.

- [ ] **Step 1: Write failing bootstrap verifier fixtures**

Require the new macOS arm64 artifact shape, AAR filename/digest, exact builder
identity, and removal of obsolete universal-layout repair when unnecessary.

- [ ] **Step 2: Run verifier tests and verify RED**

```bash
cd /Users/aweffr/developer/aweffr/webrtc-screencast-playground
./scripts/test-verifiers.sh
```

- [ ] **Step 3: Install exact bytes and update the pin**

Copy the AAR byte-for-byte to the ignored artifact path. Stage the downloaded
arm64 framework into `Vendor/WebRTC.xcframework` without modifying its binary
or headers. Update URLs/names, checksums, bootstrap verification, and docs; do
not commit machine-local paths.

- [ ] **Step 4: Verify bootstrap GREEN and fresh-header compilation**

```bash
./scripts/test-verifiers.sh
make test-macos
make build-macos
apps/android-tv/gradlew -p apps/android-tv testDebugUnitTest
```

- [ ] **Step 5: Commit the artifact pin**

```bash
git add artifacts/SHA256SUMS scripts README.md apps/android-tv/README.md
git commit -m "build: pin hevc tuning WebRTC artifacts"
```

## Task 7: Replace hard-coded H.264 policy with selected-codec policy

**Files:**
- Modify: downstream bundled config and its Android XML copy.
- Modify/create: macOS runtime config, codec policy/factory, WebRTC session, and tests.
- Modify/create: Android receiver codec/answer/fatal policy and tests.

- [ ] **Step 1: Write failing macOS policy/configuration tests**

Require H.265 mode to advertise H.265 plus associated RTX in preference order,
preserve H.265 SDP, use schema 3 with spatial AQ `DEFAULT`, and reject spatial
AQ with low latency. Retain explicit H.264 compatibility coverage.

- [ ] **Step 2: Run macOS tests and verify RED**

```bash
make test-macos
```

Expected: construction remains H.264-only and schema assertions remain 2.

- [ ] **Step 3: Implement one macOS selected-codec policy**

Introduce a `VideoCodecName`/policy boundary used by capability filtering,
normalization, factories, WebRTC session construction, and telemetry. H.265
must not run H.264 profile-level rewriting; H.264 mode retains prior behavior.

- [ ] **Step 4: Write failing Android policy tests**

Require H.265 preference, no H.264 answer rewrite in H.265 mode, H.265 fatal
capability messages, and synchronized schema-3 config in
`reference_runtime.xml`.

- [ ] **Step 5: Run Android tests and verify RED**

```bash
apps/android-tv/gradlew -p apps/android-tv testDebugUnitTest
```

- [ ] **Step 6: Implement Android selected-codec policy**

Drive ordering and answer handling from the embedded config. H.265 mode keeps
payload/RTX mapping intact; H.264 retains level-4.1 normalization.

- [ ] **Step 7: Verify both apps GREEN and commit**

```bash
make test-macos
make build-macos
apps/android-tv/gradlew -p apps/android-tv testDebugUnitTest lintDebug assembleDebug
git diff --check
git add config apps/macos apps/android-tv
git commit -m "feat: negotiate HEVC screencasting"
```

## Task 8: Make E2E verification codec-aware and prove HEVC

**Files:**
- Modify: downstream `scripts/verify-diagnostics.sh`
- Modify: downstream `scripts/test-verifiers.sh`
- Modify: E2E docs only for measured findings.

- [ ] **Step 1: Write failing HEVC diagnostics fixtures**

Add valid `video/H265` sender/receiver evidence and failures for H.264 fallback,
missing decoder identity, mismatched runtime-QP codec, or spatial-AQ evidence
not matching ordinary HEVC mode.

- [ ] **Step 2: Run verifier tests and verify RED**

```bash
./scripts/test-verifiers.sh
```

- [ ] **Step 3: Implement expected-codec-aware diagnostics**

Read configured codec from effective runtime config. Require matching
offer/answer/stats codec, codec-tagged max-QP/session evidence, Android decoder,
and requested/effective spatial-AQ state.

- [ ] **Step 4: Run the complete static gate**

```bash
make verify
./scripts/verify-no-secret-leaks.sh secrets/runtime.json
git diff --check
```

- [ ] **Step 5: Run real Mac-to-Android HEVC E2E**

Use the existing Android TV arm64 emulator/device and schema-3 ordinary HEVC
configuration. Require decoded video, `video/H265` on both ends, actual H.265
QP within cap, Apple HEVC encoder ID, spatial AQ `DEFAULT`, Android decoder
identity, and route evidence.

- [ ] **Step 6: Run clean-context downstream review and commit**

Fix validated Critical/High codec, compatibility, provenance, observability,
or verification findings; re-review at most three rounds.

```bash
git add scripts docs
git commit -m "test: verify end-to-end HEVC casting"
```

## Task 9: Completion audit and handoff

- [ ] **Step 1: Audit every explicit requirement**

Prove `my-webrtc-builds` changed first; macOS arm64 and Android workflows ran
from one final SHA; exact artifacts were downloaded/installed; downstream uses
H.265 rather than fallback; HEVC receives max QP, low-latency A/B, spatial AQ,
realtime, and frame-reordering controls; tests, hardware probe, Android smoke,
and E2E passed.

- [ ] **Step 2: Confirm repository state**

Both repositories are on `main` with clean worktrees. Report ahead/behind state
without discarding the downstream pre-existing local commit. Do not mark the
goal complete while any workflow, artifact, integration, or evidence is missing.

- [ ] **Step 3: Report final evidence**

List core files, design choices, tests/E2E, review findings/fixes, commits,
workflow URLs and hashes, branch/worktree state, and follow-ups for
quality-priority, Main 4:4:4, and VBR/presets.

## Execution findings

- 2026-07-17: User explicitly requires direct execution on `main`, no
  worktrees, macOS arm64 and Android hosted builds only, artifact download,
  followed by downstream integration.
- 2026-07-17: Downstream started clean on `main` at `037351d`, one commit ahead
  of `origin/main`; that existing commit is preserved.
- 2026-07-17: The user requires TDD and review to stay focused on core business
  value. Tests are limited to effective HEVC controls, codec negotiation/decode,
  artifact identity, and necessary compatibility; review must ignore defensive
  boilerplate, style-only suggestions, speculative abstractions, and unrelated
  refactors.
- 2026-07-17: Schema-3 RED failed on the missing enum/field and metadata version
  exactly as intended. The focused suite then passed 14 tests and the complete
  repository suite passed all 105 tests after the minimal implementation.
