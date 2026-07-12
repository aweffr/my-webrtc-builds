# Build and release runbook

This runbook describes the operational workflow for WebRTC CastKit. It is for
maintainers who build, compose, release, or diagnose the binary artifacts.

## Prerequisites

- `gh auth status` succeeds for `aweffr/my-webrtc-builds`.
- Build workflows are manually dispatched only. They do not run on push,
  pull request, or schedule.
- Use the same repository commit for the five platform builds.

## Build platform artifacts

Dispatch the four workflows from the intended branch or commit. Replace `main`
when validating a feature branch.

```bash
gh workflow run build-android.yml -R aweffr/my-webrtc-builds --ref main
gh workflow run build-ios.yml -R aweffr/my-webrtc-builds --ref main
gh workflow run build-macos-x64.yml -R aweffr/my-webrtc-builds --ref main
gh workflow run build-macos-arm64.yml -R aweffr/my-webrtc-builds --ref main
gh workflow run build-windows-x64.yml -R aweffr/my-webrtc-builds --ref main
```

List and inspect runs:

```bash
gh run list -R aweffr/my-webrtc-builds --limit 20
gh run view RUN_ID -R aweffr/my-webrtc-builds
```

## Compose the macOS XCFramework

After both macOS builds succeed, dispatch the composition workflow with their
run IDs:

```bash
gh workflow run package-macos-xcframework.yml \
  -R aweffr/my-webrtc-builds \
  --ref main \
  -f x64_run_id=MACOS_X64_RUN_ID \
  -f arm64_run_id=MACOS_ARM64_RUN_ID
```

The composition step rejects mismatched WebRTC source, builder commit,
configuration fingerprint, header manifest, or CastTuning overlay manifest.

## Publish a release

Publish only after Android, iOS, both macOS builds, and XCFramework composition
all succeed:

```bash
gh workflow run publish-release.yml \
  -R aweffr/my-webrtc-builds \
  --ref main \
  -f android_run_id=ANDROID_RUN_ID \
  -f ios_run_id=IOS_RUN_ID \
  -f macos_x64_run_id=MACOS_X64_RUN_ID \
  -f macos_arm64_run_id=MACOS_ARM64_RUN_ID \
  -f windows_x64_run_id=WINDOWS_X64_RUN_ID \
  -f xcframework_run_id=XCFRAMEWORK_RUN_ID
```

The release workflow validates every input artifact before publishing and
rejects mixed builder commits, source versions, and existing tags. Release tags
are provenance based:

```text
webrtc-m150.7871.3-<builder-short-sha>-YYYYMMDD-all
```

## Local checks

These checks do not download or compile WebRTC:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q builder tests
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/*.yml
git diff --check
```

Run one real platform build with the same CLI used by Actions:

```bash
python3 -u -m builder build \
  --target macos-arm64 \
  --work-dir build-workspace \
  --dist-dir dist \
  --builder-commit "$(git rev-parse HEAD)"
```

## Diagnose failed hosted builds

Every workflow uploads `<artifact>-diagnostics`, including failures. Download
it with:

```bash
gh run download RUN_ID \
  -R aweffr/my-webrtc-builds \
  -n webrtc-m150-macos-arm64-diagnostics

gh run download WINDOWS_RUN_ID \
  -R aweffr/my-webrtc-builds \
  -n webrtc-m150-windows-x64-diagnostics
```

Inspect these files first:

| File | What it answers |
| --- | --- |
| `build.log` | Exact command output and compiler/linker failure |
| `build-events.jsonl` | Last completed phase and duration |
| `runner-before.txt`, `runner-after.txt` | Runner image, tool versions, and disk pressure |
| `webrtc-commit.txt`, `webrtc-status.txt` | Actual checked-out source and unexpected mutations |
| `gn-args-*` | Resolved GN arguments for each architecture; iOS retains both slices |
| `patch-hashes.txt` | Exact patch files present in the workflow checkout |
| `output-files.txt` | Full generated output inventory |

The builder deliberately does not serialize environment mappings into logs, so
secrets such as `GITHUB_TOKEN` are not exposed. When fixing a reproducible
failure, add a focused local regression test if the behavior can be tested
without a full WebRTC checkout; then rerun every artifact that must share the
same builder commit.
