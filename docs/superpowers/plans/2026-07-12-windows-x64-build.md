# Windows x64 Build Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the isolated worktree. Keep the checkboxes and append only verified execution findings.

**Goal:** Add a reproducible WebRTC M150 Windows x64 package with CastTuning common C++ support and integrate it into the release manifest contract.

**Architecture:** Extend the existing target-driven Python builder with a Windows-specific tool/bootstrap path, consume the upstream `complete_static_lib` `obj/webrtc.lib`, and package it as a safe ZIP. Add a thin `windows-2022` workflow and extend release validation without changing metadata schemas.

**Tech Stack:** Python 3.11 standard library, `unittest`, depot_tools, GN, Ninja, LLVM COFF tools, Visual Studio 2022, GitHub Actions.

---

## Confirmed decisions

- Target name: `windows-x64`; runner: `windows-2022`; architecture: `x64`.
- Package: `webrtc-m150-windows-x64.zip`, rooted at `webrtc/`.
- Include the `common` CastTuning overlay and run `cast_tuning_native_tests.exe`; no Windows-specific wrapper.
- Bundle software H.264 through OpenH264/FFmpeg; H.265 is parser/negotiation only.
- Keep the pinned M150 non-component Release `/MT` CRT contract and `use_custom_libcxx=false`.
- This execution ends after a successful Windows hosted build and artifact verification; do not merge or publish a combined release.

## Task 1: Target, environment, and build contract

**Files:**
- Modify: `builder/config.py`, `builder/source.py`, `builder/build.py`, `builder/observability.py`
- Modify: `builder/__main__.py`
- Modify: `tests/test_config.py`, `tests/test_build.py`, `tests/test_observability.py`
- Create: `patches/m150/windows_add_deps.patch`
- Modify: `patches/m150/SOURCES.md`

- [ ] Add a failing target test requiring `windows-x64`, `windows-2022`, `("x64",)`, `("common",)`, `windows_add_deps.patch`, H.264 software flags, `target_os="win"`, `target_cpu="x64"`, `use_custom_libcxx=false`, `use_custom_libcxx_for_host=false`, and `:default` as the production Ninja target.
- [ ] Add a failing source/build test that Windows target preparation never executes the Unix `bash` bootstrap, emits `DEPOT_TOOLS_WIN_TOOLCHAIN=0` and Git long-path configuration, invokes `.bat` depot_tools entrypoints, copies `obj/webrtc.lib`, and invokes the native CastTuning validation executable.
- [ ] Vendor the M150 `windows_add_deps.patch` hunk from the Shiguredo M150 reference and record its URL, source tag, and SHA-256 in `SOURCES.md`.
- [ ] Implement target-aware environment and command selection while preserving all existing non-Windows command sequences and metadata behavior.
- [ ] Run `python3 -m unittest tests.test_config tests.test_build tests.test_observability -v`; expected result is PASS.
- [ ] Commit `feat: add Windows x64 build target`.

## Task 2: Windows package and binary verification

**Files:**
- Modify: `builder/package.py`, `builder/verify.py`
- Modify: `tests/test_package.py`, `tests/test_verify.py`

- [ ] Add failing tests for `webrtc-m150-windows-x64.zip`, safe ZIP extraction rejecting traversal/drive paths/backslash escapes/symlinks, required `lib/webrtc.lib`, and Windows tool command selection.
- [ ] Add ZIP creation with stable `webrtc/` archive root and a format-dispatching safe extraction helper; leave existing tar extraction behavior unchanged.
- [ ] Package `unit.output_dir / "webrtc.lib"`, generated headers, CastTuning headers, notices, resolved GN args, metadata, and `SHA256SUMS`.
- [ ] Verify the Windows archive with hermetic checkout tools: non-empty `llvm-lib.exe /list`, `llvm-readobj.exe --file-headers` reporting AMD64 COFF members, and demangled `H264EncoderImpl`, `H264DecoderImpl`, and `webrtc::cast_tuning::CastTuningController` symbols from `llvm-nm.exe`.
- [ ] Run `python3 -m unittest tests.test_package tests.test_verify -v`; expected result is PASS.
- [ ] Commit `feat: package and verify Windows x64 artifacts`.

## Task 3: Release manifest and CLI integration

**Files:**
- Modify: `builder/compose.py`, `builder/__main__.py`
- Modify: `tests/test_compose.py`

- [ ] Add failing tests requiring the exact five platform keys, the Windows ZIP filename, metadata extraction from ZIP, and rejection of missing or mismatched Windows metadata.
- [ ] Extend `create_release_manifest` to accept `windows-x64`, dispatch extraction by archive format, validate it with the same source/builder/tuning schema rules, and include it in aggregate assets/checksums.
- [ ] Add `--windows-x64-package` to the `release-manifest` CLI while preserving all existing arguments and manifest schema version `1`.
- [ ] Run `python3 -m unittest tests.test_compose -v`; expected result is PASS.
- [ ] Commit `feat: include Windows x64 in release manifests`.

## Task 4: Hosted Windows workflow and release workflow contract

**Files:**
- Create: `.github/workflows/build-windows-x64.yml`
- Modify: `.github/workflows/publish-release.yml`

- [ ] Add only `workflow_dispatch`, `windows-2022`, minimal read permissions, concurrency protection, and a timeout that covers the observed ~50-minute M150 build.
- [ ] Use C-drive build workspace, remove nonessential Android/JDK images before the build, record runner/VS/SDK/disk state, run unit tests, invoke the builder, upload the ZIP only on success, upload diagnostics with `if: always()`, and propagate build failure.
- [ ] Pin every GitHub action to the repository’s existing full commit SHAs; keep PowerShell-native diagnostics free of secrets.
- [ ] Add required `windows_x64_run_id`, download `webrtc-m150-windows-x64`, pass `--windows-x64-package`, and publish the ZIP in the combined release asset list.
- [ ] Run actionlint and the full Python test suite; expected result is PASS.
- [ ] Commit `ci: add Windows x64 hosted build`.

## Task 5: Documentation and local verification

**Files:**
- Modify: `README.md`, `README_CN.md`, `docs/runbook.md`
- Modify: `docs/superpowers/specs/2026-07-12-m150-webrtc-builds-design.md`

- [ ] Document Windows package contents, `/MT` ABI, VS2022 runner, C++ CastTuning boundary, H.264/H.265 contract, dispatch command, diagnostics name, and the additional release run ID.
- [ ] Run `python3 -m unittest discover -s tests -v`, `python3 -m compileall -q builder tests`, actionlint, and `git diff --check`.
- [ ] Append only verified implementation findings or remaining risks to this plan.
- [ ] Commit `docs: document Windows x64 artifact workflow`.

## Task 6: Hosted build, artifact verification, and review

**Files:**
- Modify only files required by failures reproduced in the hosted job; add a focused regression test for every locally testable behavior change.

- [ ] Push `feature/windows-x64-build` and dispatch `build-windows-x64.yml` from that branch.
- [ ] Monitor the run to completion; on failure inspect `build.log`, `build-events.jsonl`, runner state, GN args, source identity, patch hashes, and output inventory before changing code.
- [ ] Download the successful artifact and verify ZIP paths, `metadata.json`, `SHA256SUMS`, configured builder commit, and package filename locally; record run ID and digest here.
- [ ] Launch an independent-context high-reasoning code review with the original request, this plan, design doc, diff, test results, hosted evidence, and known limitations.
- [ ] Fix only validated Critical/High or requirement-blocking findings, rerun affected tests and hosted validation, and stop after approval or three review rounds.
- [ ] Leave the worktree and branch intact; do not merge `main`, clean up the worktree, or publish a combined release in this execution.

## Execution findings

- 2026-07-12: The pinned M150 root `webrtc` target is `complete_static_lib`; Windows should copy `obj/webrtc.lib` instead of re-archiving `.obj` files.
- 2026-07-12: The pinned M150 Windows build configuration uses desktop static CRT `/MT`; changing to `/MD` would require a separate Chromium build-config decision.
- 2026-07-12: `windows-2022` is the verified runner for this M150 line; `windows-latest` now moves with newer Windows/Visual Studio images.
- 2026-07-12: GitHub `workflow_dispatch` does not register a workflow file that exists only on a feature branch; the API returns 404 until the workflow is present on the repository default branch. Hosted validation therefore requires either merging the CI workflow to `main` or explicitly accepting local/actionlint-only validation.
- 2026-07-13: Rebased the Windows extension onto `origin/main@3eabb6f`; no conflicts occurred. The post-rebase suite passed 73 tests, including Windows CastTuning native/package/symbol contracts.
