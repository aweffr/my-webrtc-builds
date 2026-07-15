# Android AAR and Apple Low-Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `execute-long-horizon-task` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. The user explicitly requires inline
> execution on `main`; do not create a branch or worktree.

**Goal:** Publish an Android app-consumable M150 AAR and macOS M150 frameworks
with opt-in CastTuning VideoToolbox low-latency rate control, then prove both
artifacts through hosted builds and local hardware/runtime smoke tests.

**Architecture:** The existing GN Android build remains the only compilation
source; the Python packager stages its stripped JNI shared library into both
the raw tar and a standalone AAR and verifies byte identity. CastTuning schema
2 carries a macOS-only session-creation option into the existing Objective-C
H.264 encoder wrapper, while schema 1 preserves its prior defaults. A scoped
macOS/Android pre-release composes artifacts from one builder commit only after
the exact GitHub Actions AAR and final arm64 XCFramework slice pass local
runtime probes.

**Tech Stack:** Python 3.11+, `unittest`, C++17 contract tests, Objective-C++,
VideoToolbox, GN/Ninja, Android AAR/APK tooling, Android arm64 API 31 emulator,
GitHub Actions, GitHub CLI

---

## File responsibilities

- `builder/package.py`: stage Android GN outputs and construct the raw archive
  plus AAR from the same bytes.
- `builder/verify.py`: verify package/AAR layout, ELF identity, exported JNI
  entry point, Java API, paired payload equality, and macOS linked symbols.
- `builder/metadata.py`: record CastTuning schema 2 in artifact metadata.
- `builder/compose.py`: validate the scoped release platform set and produce a
  partial manifest containing the Android AAR.
- `overlays/m150/common/api/cast_tuning/*`: schema-versioned defaults, parsing,
  validation, hashing, and contract tests.
- `overlays/m150/macos/sdk/objc/api/peerconnection/RTCCastTuning.*`: bridge the
  typed setting to the encoder and expose persistent mismatch evidence.
- `patches/m150/cast_tuning_hooks.patch`: wire the M150 H.264 VideoToolbox
  session specification and first-keyframe profile observation.
- `smoke/android-aar/*`: minimal AAR-only Android consumer used for CI compile
  and local emulator runtime smoke.
- `tools/android-aar-smoke.sh`: download and verify the exact workflow artifact,
  run the emulator smoke, and write bound evidence.
- `tools/macos-videotoolbox-probe/*`: link the final framework slice and record
  normal/low-latency VideoToolbox evidence on real Apple Silicon hardware.
- `.github/workflows/build-android.yml`: upload the raw tar, AAR, consumer APK,
  hashes, and diagnostics from one hosted build.
- `.github/workflows/publish-macos-android-preview.yml`: publish only the agreed
  macOS/Android preview asset set after explicit local evidence inputs validate.

### Task 1: Complete the Android raw package and AAR contract

**Files:**
- Modify: `builder/package.py`
- Modify: `builder/verify.py`
- Modify: `tests/test_package.py`
- Modify: `tests/test_verify.py`

- [x] **Step 1: Keep the package test RED until both containers use the same
  GN outputs**

  The Android fixture creates `libjingle_peerconnection_so.so` beside
  `libwebrtc.a` and asserts these exact AAR members:

  ```python
  self.assertEqual(
      set(stream.namelist()),
      {
          "AndroidManifest.xml",
          "classes.jar",
          "jni/arm64-v8a/libjingle_peerconnection_so.so",
      },
  )
  self.assertEqual(stream.read("classes.jar"), raw_jar.read_bytes())
  self.assertEqual(stream.read(jni_member), raw_jni.read_bytes())
  ```

- [x] **Step 2: Run the focused RED contract**

  Run:

  ```bash
  python3 -m unittest \
    tests.test_package.PackageContractTests.test_android_stage_contains_library_jar_metadata_and_notices \
    tests.test_verify.PackageLayoutVerificationTests.test_android_requires_static_library_jar_and_jni_shared_object \
    tests.test_verify.BinaryVerificationTests.test_android_can_use_hermetic_archiver -v
  ```

  Expected before implementation: missing raw JNI path/AAR and absent
  `llvm-readelf`/`llvm-nm` calls.

- [x] **Step 3: Stage the stripped JNI library and construct the AAR**

  Implement the fixed output and archive mapping:

  ```python
  def android_aar_filename() -> str:
      return "webrtc-m150-android-arm64-v8a.aar"

  def create_android_aar(stage: Path, manifest: Path, archive: Path) -> None:
      with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
          stream.write(manifest, "AndroidManifest.xml")
          stream.write(stage / "jar/webrtc.jar", "classes.jar")
          stream.write(
              stage / "jni/arm64-v8a/libjingle_peerconnection_so.so",
              "jni/arm64-v8a/libjingle_peerconnection_so.so",
          )
  ```

  `_copy_payload()` copies the stripped output-root `.so`; it never substitutes
  `lib.unstripped/libjingle_peerconnection_so.so`.

- [x] **Step 4: Verify architecture, JNI entry point, and paired bytes**

  `verify_binaries()` invokes the checkout's hermetic tools:

  ```python
  elf = runner.capture([android_readelf, "-h", shared_library])
  if "ELF64" not in elf or "AArch64" not in elf:
      raise VerificationError("unexpected Android JNI ELF architecture")
  symbols = runner.capture([android_nm, "-D", "--defined-only", shared_library])
  if "JNI_OnLoad" not in symbols:
      raise VerificationError("required symbol 'JNI_OnLoad' is missing")
  ```

  `verify_android_aar()` requires the three-member structure and compares
  `classes.jar` plus JNI bytes with their raw package counterparts.

- [x] **Step 5: Run focused and full Python tests**

  Run:

  ```bash
  python3 -m unittest tests.test_package tests.test_verify -v
  python3 -m unittest discover -s tests -v
  ```

  Expected: all tests pass.

- [x] **Step 6: Commit the package contract**

  ```bash
  git add builder/package.py builder/verify.py tests/test_package.py tests/test_verify.py
  git commit -m "feat: publish app-consumable Android AAR"
  ```

### Task 2: Implement CastTuning schema 2 compatibility

**Files:**
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_config.h`
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_config.cc`
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_json.cc`
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_config_unittest.cc`
- Modify: `overlays/m150/common/api/cast_tuning/cast_tuning_json_contract_test.cc`
- Modify: `builder/metadata.py`
- Modify: `builder/package.py`
- Modify: `tests/test_metadata.py`
- Modify: `examples/cast-tuning-detail-idle.json`

- [x] **Step 1: Write schema/default/validation RED tests**

  Cover these contracts directly in the native test executable:

  ```cpp
  Expect(kTuningSchemaVersion == 2, "current schema must be version 2");
  const auto current = CastTuningConfig::ForProfile(Profile::kDetailIdle, 2);
  Expect(current.encoder.h264_profile == "CONSTRAINED_HIGH", "v2 profile");
  Expect(current.encoder.video_toolbox_low_latency_rate_control == true,
         "v2 low latency default");
  Expect(!current.encoder.data_rate_limit_factor, "v2 has no hard window");

  const auto legacy = CastTuningConfig::ForProfile(Profile::kDetailIdle, 1);
  Expect(legacy.encoder.h264_profile == "CONSTRAINED_BASELINE", "v1 profile");
  Expect(!legacy.encoder.video_toolbox_low_latency_rate_control,
         "v1 has no low latency opt-in");
  Expect(legacy.encoder.data_rate_limit_factor == 1.5, "v1 hard window");
  ```

  Add JSON cases proving schema 1 and 2 parse, schema 1 rejects the new field,
  schema 3 fails, explicit schema 2 Baseline is accepted, and low latency plus
  either `data_rate_limit_*` field fails.

- [x] **Step 2: Run the native RED contract**

  ```bash
  python3 -m unittest \
    tests.test_cast_tuning_overlay.CastTuningNativeContractTests.test_config_profiles_validation_and_field_trials -v
  ```

  Expected before implementation: schema/default assertion or missing field/API
  failure.

- [x] **Step 3: Add the version-aware typed model**

  Use the exact public shape:

  ```cpp
  inline constexpr int kTuningSchemaVersion = 2;
  inline constexpr int kMinimumTuningSchemaVersion = 1;

  struct EncoderConfig {
    // Existing members remain in their current order.
    std::optional<bool> video_toolbox_low_latency_rate_control;
  };

  static CastTuningConfig ForProfile(Profile profile,
                                     int schema_version = kTuningSchemaVersion);
  ```

  For non-UPSTREAM schema 2 profiles set low latency `true`, Constrained High
  4.1, and leave both DataRateLimits values unset. For schema 1 set no low
  latency value, Constrained Baseline 4.1, factor `1.5`, and window `1000`.

- [x] **Step 4: Parse and validate by schema before applying profile defaults**

  `ParseJson()` first reads and range-checks `schema_version`, then calls
  `ForProfile(profile, schema_version)`. `ParseEncoder()` accepts
  `video_toolbox_low_latency_rate_control` only for schema 2. Validation returns
  this exact error for a conflicting hard window:

  ```cpp
  return ValidationResult::Error(
      "encoder VideoToolbox low-latency rate control is mutually exclusive "
      "with DataRateLimits");
  ```

- [x] **Step 5: Move metadata and examples to schema 2**

  `BuildMetadata.create()` defaults `tuning_schema_version=2`, metadata loading
  requires `2` for newly built artifacts, `stage_and_package()` records `2`,
  and `examples/cast-tuning-detail-idle.json` uses schema 2, Constrained High,
  and `"video_toolbox_low_latency_rate_control": true`.

- [x] **Step 6: Run native, metadata, and full tests**

  ```bash
  python3 -m unittest tests.test_cast_tuning_overlay tests.test_metadata -v
  python3 -m unittest discover -s tests -v
  ```

  Expected: all tests pass, including legacy schema 1 behavior.

- [x] **Step 7: Commit schema 2**

  ```bash
  git add overlays/m150/common/api/cast_tuning builder/metadata.py \
    builder/package.py tests/test_metadata.py examples/cast-tuning-detail-idle.json
  git commit -m "feat: add CastTuning schema 2 low latency contract"
  ```

### Task 3: Wire VideoToolbox low-latency session creation and evidence

**Files:**
- Modify: `overlays/m150/macos/sdk/objc/api/peerconnection/RTCCastTuning.h`
- Modify: `overlays/m150/macos/sdk/objc/api/peerconnection/RTCCastTuning.mm`
- Modify: `patches/m150/cast_tuning_hooks.patch`
- Modify: `tests/test_cast_tuning_overlay.py`
- Modify: `builder/verify.py`
- Modify: `tests/test_verify.py`

- [x] **Step 1: Add RED patch/bridge contract tests**

  The test copies the cached exact M150 source file to a temporary tree, applies
  `cast_tuning_hooks.patch --check` and then applies it. It asserts the patched
  code compiles through the hosted build and the framework verifier requires
  `kVTVideoEncoderSpecification_EnableLowLatencyRateControl` as an undefined
  linked symbol. The bridge contract requires the Objective-C options key:

  ```objective-c
  options[@"video_toolbox_low_latency_rate_control"] =
      @(config.encoder.video_toolbox_low_latency_rate_control.value());
  ```

- [x] **Step 2: Run the RED overlay/verifier tests**

  ```bash
  python3 -m unittest tests.test_cast_tuning_overlay tests.test_verify -v
  ```

  Expected before implementation: missing option and low-latency linked symbol.

- [x] **Step 3: Add the macOS-only encoder specification**

  Preserve the normal encoder specification and append the low-latency key only
  for an explicit true value:

  ```objective-c
  NSNumber *lowLatency =
      _castTuningOptions[@"video_toolbox_low_latency_rate_control"];
  if (lowLatency.boolValue) {
    specs[(NSString *)
        kVTVideoEncoderSpecification_EnableLowLatencyRateControl] = @(YES);
  }
  ```

  Pass the resulting immutable dictionary to `VTCompressionSessionCreate`.
  Creation failure returns the original `OSStatus`; no ordinary-session retry
  is added.

- [x] **Step 4: Avoid DataRateLimits in low-latency mode**

  `setEncoderBitrateBps:frameRate:` always sets `AverageBitRate`, but builds and
  sets `DataRateLimits` only when the low-latency option is not true. Schema
  validation remains the caller-facing rejection for an explicit conflict.

- [x] **Step 5: Record encoder/profile compatibility once per session**

  At session creation, query and log Encoder ID. At the first keyframe, derive
  the SPS profile family and compare it with the codec's negotiated
  `profile-level-id`. Emit one warning with expected/actual profile, Encoder ID,
  session/config correlation values, and retain `profile_mismatch=true` in the
  encoder evidence exposed through `RTCCastTuningSnapshot`. Continue delivering
  the encoded frame; do not rewrite SDP or recreate the encoder.

- [x] **Step 6: Verify patched source and binary contract**

  ```bash
  python3 -m unittest tests.test_cast_tuning_overlay tests.test_verify -v
  git apply --check patches/m150/cast_tuning_hooks.patch
  ```

  The final `git apply --check` runs against a clean pinned M150 checkout after
  the existing prerequisite patches, matching `prepare_source()` order.

- [x] **Step 7: Commit the VideoToolbox integration**

  ```bash
  git add overlays/m150/macos patches/m150/cast_tuning_hooks.patch \
    tests/test_cast_tuning_overlay.py builder/verify.py tests/test_verify.py
  git commit -m "feat: enable macOS VideoToolbox low latency rate control"
  ```

### Task 4: Add the AAR consumer compile and local emulator smoke

**Files:**
- Create: `smoke/android-aar/settings.gradle.kts`
- Create: `smoke/android-aar/build.gradle.kts`
- Create: `smoke/android-aar/app/build.gradle.kts`
- Create: `smoke/android-aar/app/src/main/AndroidManifest.xml`
- Create: `smoke/android-aar/app/src/main/java/dev/aweffr/webrtcsmoke/MainActivity.java`
- Create: `smoke/android-aar/app/src/main/res/values/strings.xml`
- Create: `tools/android-aar-smoke.sh`
- Modify: `.github/workflows/build-android.yml`

- [x] **Step 1: Create a minimal AAR-only consumer**

  The app repository declares only the local AAR and AndroidX-free platform
  APIs. Its activity executes this runtime path and writes `AAR_SMOKE_OK` only
  after every call succeeds:

  ```java
  PeerConnectionFactory.initialize(
      PeerConnectionFactory.InitializationOptions.builder(this)
          .createInitializationOptions());
  PeerConnectionFactory factory =
      PeerConnectionFactory.builder().createPeerConnectionFactory();
  VideoCodecInfo[] codecs = new DefaultVideoDecoderFactory(null)
      .getSupportedCodecs();
  boolean hasH264 = Arrays.stream(codecs)
      .anyMatch(codec -> "H264".equalsIgnoreCase(codec.name));
  if (!hasH264) throw new IllegalStateException("H264 decoder is unavailable");
  Log.i("WebRTCAarSmoke", "AAR_SMOKE_OK");
  factory.dispose();
  ```

- [x] **Step 2: Make hosted CI compile and inspect the APK**

  `build-android.yml` uses the WebRTC checkout Android SDK, runs the checked-in
  SHA-pinned Gradle 9.4.1 wrapper with JDK 21 (the M150 jar is class-file
  version 65), copies the produced AAR to
  `smoke/android-aar/app/libs/`, builds `assembleDebug`, and verifies with
  `unzip -l` that the APK includes
  `lib/arm64-v8a/libjingle_peerconnection_so.so`.

- [x] **Step 3: Upload one evidence-bearing workflow artifact**

  Upload these exact files under artifact name
  `webrtc-m150-android-arm64-v8a` with compression level 0:

  ```text
  dist/webrtc-m150-android-arm64-v8a.tar.gz
  dist/webrtc-m150-android-arm64-v8a.aar
  smoke/android-aar/app/build/outputs/apk/debug/app-debug.apk
  diagnostics/android-artifact-sha256.txt
  ```

- [x] **Step 4: Implement the local download-and-run evidence script**

  `tools/android-aar-smoke.sh RUN_ID` uses `gh run download` for the named
  artifact, computes artifact file SHA-256 values, starts the existing arm64
  API 31 AVD, installs the downloaded APK, launches the activity, waits for
  `AAR_SMOKE_OK`, and writes JSON containing repository, run ID, AAR SHA-256,
  APK SHA-256, ABI, API level, AVD name, and bounded logcat output. Any missing
  field, timeout, non-arm64 ABI, or absent marker exits non-zero.

- [x] **Step 5: Validate workflow syntax and script behavior**

  ```bash
  actionlint .github/workflows/build-android.yml
  bash -n tools/android-aar-smoke.sh
  python3 -m unittest discover -s tests -v
  ```

  Expected: all commands pass.

- [x] **Step 6: Commit Android smoke infrastructure**

  ```bash
  git add smoke/android-aar tools/android-aar-smoke.sh \
    .github/workflows/build-android.yml
  git commit -m "ci: verify Android AAR app consumption"
  ```

### Task 5: Add final-framework VideoToolbox hardware probe

**Files:**
- Create: `tools/macos-videotoolbox-probe/main.mm`
- Create: `tools/run-macos-videotoolbox-probe.sh`
- Modify: `.github/workflows/build-macos-arm64.yml`
- Modify: `.github/workflows/build-macos-x64.yml`

- [x] **Step 1: Implement a probe against the packaged framework**

  The runner accepts the downloaded XCFramework zip, verifies its SHA-256,
  extracts it safely, links the arm64 framework, creates normal and
  CastTuning-low-latency 1920x1080 H.264 encoders, feeds a deterministic frame,
  waits for the first keyframe, and emits one JSON object per mode with:

  ```text
  framework_sha256, architecture, os_version, hardware_model,
  requested_low_latency, session_status, encoder_id,
  negotiated_profile, sps_profile, profile_mismatch
  ```

- [x] **Step 2: Enforce real-hardware evidence**

  `tools/run-macos-videotoolbox-probe.sh` rejects virtualized hardware evidence,
  requires `arm64`, requires successful normal and low-latency sessions, and
  requires the low-latency encoder ID to be recorded. A Baseline/High mismatch
  is accepted only when `profile_mismatch=true` and the warning is present.

- [x] **Step 3: Keep hosted x64 verification explicit**

  Both macOS workflows verify compilation, package layout, architecture, and
  the low-latency linked symbol. Their summaries state that hosted VM results
  are not real VideoToolbox hardware evidence; the preview manifest records
  `macos_x64_hardware_runtime_verified=false`.

- [x] **Step 4: Validate scripts and local contract tests**

  ```bash
  bash -n tools/run-macos-videotoolbox-probe.sh
  xcrun clang++ -fsyntax-only tools/macos-videotoolbox-probe/main.mm \
    -F /path/to/WebRTC.framework/.. -framework WebRTC
  python3 -m unittest discover -s tests -v
  ```

  Expected: syntax/build/tests pass on the local Mac.

- [x] **Step 5: Commit probe infrastructure**

  ```bash
  git add tools/macos-videotoolbox-probe tools/run-macos-videotoolbox-probe.sh \
    .github/workflows/build-macos-arm64.yml \
    .github/workflows/build-macos-x64.yml
  git commit -m "test: add macOS VideoToolbox hardware probe"
  ```

### Task 6: Add the scoped macOS/Android preview release

**Files:**
- Modify: `builder/compose.py`
- Modify: `builder/__main__.py`
- Modify: `builder/metadata.py`
- Modify: `tests/test_compose.py`
- Modify: `tests/test_metadata.py`
- Create: `.github/workflows/publish-macos-android-preview.yml`
- Modify: `docs/runbook.md`

- [x] **Step 1: Write RED scoped-manifest tests**

  Require exactly these binary assets from one builder commit:

  ```python
  expected = {
      "android": android_tar,
      "macos-x64": macos_x64_tar,
      "macos-arm64": macos_arm64_tar,
  }
  auxiliary = {"android-aar": android_aar, "macos-xcframework": xcframework}
  ```

  Assert the tag suffix is `macos-android-preview.1`, the AAR payload matches
  the Android tar, local smoke evidence SHA values match the exact AAR and
  XCFramework, x64 hardware coverage is false, and extra iOS/Windows assets are
  rejected.

- [x] **Step 2: Run scoped-release RED tests**

  ```bash
  python3 -m unittest tests.test_compose tests.test_metadata -v
  ```

  Expected before implementation: the composer still requires all five stable
  platform packages and has no preview revision/evidence API.

- [x] **Step 3: Add a separate preview manifest API**

  Keep the stable `-all` platform scope and add the Android AAR to its future
  app-consumable asset contract. Add
  `create_preview_release_manifest()` with explicit Android tar/AAR, macOS thin
  packages, XCFramework metadata, Android smoke JSON, macOS probe JSON, builder
  commit, date, and positive preview revision. It writes manifest schema 1,
  assets with SHA-256/size, evidence digests, and coverage flags.

- [x] **Step 4: Add the preview CLI and workflow**

  The new workflow accepts Android, macOS x64, macOS arm64, and XCFramework run
  IDs; builder commit; preview revision; and paths/digests for the two locally
  exported evidence files. It downloads the hosted artifacts, validates them,
  creates a GitHub pre-release with `--prerelease`, uploads only the agreed
  seven assets, downloads them again, and rechecks `SHA256SUMS` before success.

- [x] **Step 5: Validate release behavior**

  ```bash
  python3 -m unittest tests.test_compose tests.test_metadata -v
  actionlint .github/workflows/publish-macos-android-preview.yml
  python3 -m unittest discover -s tests -v
  ```

  Expected: stable all-platform tests remain green and preview tests pass.

- [x] **Step 6: Commit scoped release support**

  ```bash
  git add builder/compose.py builder/__main__.py builder/metadata.py \
    tests/test_compose.py tests/test_metadata.py \
    .github/workflows/publish-macos-android-preview.yml docs/runbook.md
  git commit -m "feat: add macOS Android preview release"
  ```

### Task 7: Hosted builds and local runtime gates

**Files:**
- Modify: this plan's `Execution findings` section with immutable run IDs,
  hashes, command results, and release URL.
- Modify implementation/tests only for failures reproduced from authoritative
  hosted or runtime evidence.

- [x] **Step 1: Run the complete local static suite**

  ```bash
  python3 -m compileall -q builder tests
  python3 -m unittest discover -s tests -v
  actionlint .github/workflows/*.yml
  git diff --check
  ```

- [x] **Step 2: Push one builder commit and trigger affected builds**

  Trigger Android, macOS x64, and macOS arm64 from the same full commit SHA.
  Wait for all three runs; if any code fix changes the commit, rerun all three
  so no preview inputs mix builder commits.

- [x] **Step 3: Compose the universal XCFramework**

  Trigger `package-macos-xcframework.yml` with the successful thin-run IDs and
  the same full builder commit. Download the exact produced zip.

- [x] **Step 4: Run the downloaded Android artifact smoke**

  ```bash
  tools/android-aar-smoke.sh <android-run-id>
  ```

  Expected: emulator marker `AAR_SMOKE_OK`; evidence SHA equals the workflow AAR.

- [x] **Step 5: Run the final XCFramework hardware probe**

  ```bash
  tools/run-macos-videotoolbox-probe.sh \
    downloads/WebRTC-m150-macos-universal.xcframework.zip
  ```

  Expected: normal and low-latency sessions succeed and evidence binds the
  exact XCFramework SHA.

- [x] **Step 6: Publish and independently verify preview 1**

  Trigger `publish-macos-android-preview.yml` with the four run IDs, builder
  commit, revision `1`, and both local evidence files. Download all release
  assets and run `shasum -a 256 -c SHA256SUMS`.

- [x] **Step 7: Record immutable execution evidence**

  Add build/composition/release run IDs, exact asset SHA-256 values, local OS and
  hardware identity, emulator identity, probe summaries, checksum verification,
  and the explicit x64 runtime coverage gap under `Execution findings`.

### Task 8: Clean-context review and completion audit

**Files:**
- Modify implementation/tests/docs only for validated Critical/High findings.

- [x] **Step 1: Prepare the review context package**

  Include the original two requirements, both design documents, this plan,
  implementation commits, full diff, local/hosted/runtime results, release
  manifest, and known x64 hardware coverage limitation.

- [x] **Step 2: Dispatch a clean-context reviewer**

  Use a sub-agent without inherited conversation context and restrict review to
  requirement alignment, package/runtime correctness, schema compatibility,
  VideoToolbox failure policy, reproducibility, release integrity, and missing
  Critical/High verification.

- [x] **Step 3: Fix validated findings and re-review**

  Reproduce each accepted issue, add a regression test when behavior is
  testable, implement the smallest strategic fix, rerun the affected and full
  suites, and return changes to the same reviewer. Stop when no required fix
  remains or after three rounds.

- [x] **Step 4: Perform the requirement-by-requirement completion audit**

  Confirm raw JNI/AAR content, app runtime smoke, schema 1 compatibility,
  schema 2 defaults/validation, macOS-only low-latency session creation,
  fail-closed behavior, profile mismatch evidence, no low-latency
  `DataRateLimits`, both macOS builds, final-framework hardware probe, joint
  pre-release asset set, post-download checksums, and documented x64 runtime
  gap from authoritative artifacts and logs.

- [x] **Step 5: Report final repository state**

  Report implementation, core files, design choices, tests and E2E evidence,
  review findings/fixes, commit list, current `main` status, and remaining
  downstream bitrate/quality baseline work.

## Execution findings

- 2026-07-14: The user explicitly requires direct execution on local `main` and
  no worktree. Git operations remain serial.
- 2026-07-14: Exact M150 hosted Android logs prove Ninja already builds both
  stripped and unstripped `libjingle_peerconnection_so.so`; packaging, not GN,
  is the missing contract.
- 2026-07-14: A local M5 Pro VideoToolbox probe proves the RTVC encoder accepts
  both Constrained Baseline and Constrained High on macOS 26.5.2, while
  `UsingHardwareAcceleratedVideoEncoder` is unavailable for that encoder ID.
  Release evidence therefore records Encoder ID and SPS rather than treating
  that property as authoritative.
- 2026-07-14: The user requires GitHub Actions to build the AAR. Local Android
  E2E must download and run the exact workflow artifact; a local rebuild or
  repack is not admissible evidence.
- 2026-07-14: Final builder commit `0ff0e8c28325ec1e41fcb9d1acaa6fafbd9dff73`
  passed all three platform builds: Android run `29351721362`, macOS x64 run
  `29351723544`, and macOS arm64 run `29351726219`. Android artifact digest is
  `sha256:d83ad2954e32e0b9e4dca0f48304634aab0d8ea6b01f41c3786cb3381954c11e`,
  x64 is `sha256:b7681997ebae56c28a1ed421dfb6c34fdade66d47b01f7890a59ad45f611186b`,
  and arm64 is `sha256:eab2d58c9cb3bf641583b2aaf6c46eb655dbbfa003e305027256647a48708bb5`.
- 2026-07-14: Android API 31 `Pixel_6_API_31` arm64 smoke passed with marker
  `AAR_SMOKE_OK`; evidence is `evidence/android-aar/29351721362/evidence.json`.
  The exact AAR SHA-256 is
  `4699bc6fd2c7bf96a6762fee22e3b82094192b8aaeabebb0609ca96b813f66a9` and the
  complete AAR is copied to `/Users/aweffr/Downloads/webrtc-m150-android-arm64-v8a.aar`.
- 2026-07-14: XCFramework run `29359050764` produced zip SHA-256
  `8ae44b7ceab069e704acb5a8faaaea5aa4547ea6351bb1bf2bb38e5b343c9678`.
  Local Apple Silicon probe evidence is
  `evidence/macos-videotoolbox/8ae44b7ceab069e704acb5a8faaaea5aa4547ea6351bb1bf2bb38e5b343c9678/evidence.json`;
  normal and low-latency sessions both passed with `profile_mismatch=false`,
  and low-latency selected the `.rtvc` encoder. x64 hardware runtime remains
  explicitly unverified.
- 2026-07-14: Preview release workflow `29359317001` validated packages,
  published assets, and downloaded `SHA256SUMS` successfully. Published tag:
  `webrtc-m150.7871.3-0ff0e8c-20260714-macos-android-preview.1`.
- 2026-07-16: Downstream JDK 17 compilation exposed that the preview AAR's
  `classes.jar` uses classfile major 65 because pinned Chromium M150 hardcodes
  Java 21. The follow-up contract patches both Javac and Turbine to Java 17,
  rejects classfile major values above 61 during package verification, and
  moves the AAR-only consumer smoke back to JDK/Java 17. A new hosted Android
  artifact and scoped preview are required before downstream E2E resumes.
