# M150 WebRTC Builds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish reproducible WebRTC M150 static libraries and Apple frameworks through manually triggered GitHub Actions.

**Architecture:** A Python standard-library builder owns target configuration, source preparation, build commands, packaging, metadata, and cross-run validation. Six workflow-dispatch-only GitHub Actions invoke that builder for four builds, macOS XCFramework composition, and immutable release publication.

**Tech Stack:** Python 3.11+, `unittest`, depot_tools, GN, Ninja, LLVM `ar`, Xcode 26.0.1, GitHub Actions, GitHub CLI

---

### Task 1: Repository baseline and target configuration

**Files:**
- Create: `.gitignore`
- Create: `LICENSE`
- Create: `pyproject.toml`
- Create: `builder/__init__.py`
- Create: `builder/config.py`
- Create: `tests/test_config.py`

- [ ] Add `.worktrees/`, Python caches, build workspaces, and `dist/` to `.gitignore`; add Apache-2.0 license and a dependency-free Python project definition.
- [ ] Write failing tests that require exactly four targets, the fixed M150 identity, exact runner/architecture mappings, deployment target 14.0, macOS bundled OpenH264 flags, and mobile hardware-codec flags.
- [ ] Run `python -m unittest tests.test_config -v` and confirm it fails because `builder.config` is absent.
- [ ] Implement immutable `SourceVersion` and `TargetConfig` dataclasses plus `SOURCE_VERSION`, `TARGETS`, and `get_target()`.
- [ ] Re-run the test and then `python -m unittest discover -s tests -v`; both must pass.
- [ ] Commit with `feat: define M150 build targets`.

### Task 2: Metadata and package compatibility

**Files:**
- Create: `builder/metadata.py`
- Create: `tests/test_metadata.py`

- [ ] Write failing tests for deterministic configuration fingerprints, schema-version rejection, target mismatch, source mismatch, builder-commit mismatch, header-manifest mismatch, and release tag `m150.7871.3-rN` validation.
- [ ] Run `python -m unittest tests.test_metadata -v` and confirm the missing API failure.
- [ ] Implement metadata construction, canonical JSON hashing, load/save, compatibility validation, and release-tag generation without external dependencies.
- [ ] Re-run focused and full unit tests.
- [ ] Commit with `feat: add build metadata validation`.

### Task 3: Source preparation and build orchestration

**Files:**
- Create: `builder/commands.py`
- Create: `builder/source.py`
- Create: `builder/build.py`
- Create: `builder/__main__.py`
- Create: `tests/test_commands.py`
- Create: `tests/test_build.py`

- [ ] Write failing tests for subprocess error reporting, depot_tools/bootstrap commands, exact commit checkout verification, patch check-before-apply ordering, per-target GN args, Ninja targets, and CLI target rejection.
- [ ] Run the focused tests and confirm failures are caused by missing production modules.
- [ ] Implement a command runner with injectable execution, shallow WebRTC checkout/sync, patch verification/application, GN generation, target builds, and object-file static archive assembly.
- [ ] Ensure secrets and complete environment dictionaries are never logged; command failures include argv and exit status.
- [ ] Implement `python -m builder build --target ... --work-dir ... --dist-dir ... --builder-commit ...`.
- [ ] Re-run focused and full unit tests.
- [ ] Commit with `feat: add WebRTC build orchestrator`.

### Task 4: Packaging, verification, and M150 patches

**Files:**
- Create: `builder/package.py`
- Create: `builder/verify.py`
- Create: `tests/test_package.py`
- Create: `tests/test_verify.py`
- Create: `patches/m150/add_deps.patch`
- Create: `patches/m150/h265.patch`
- Create: `patches/m150/h265_ios.patch`
- Create: `patches/m150/h265_android.patch`
- Create: `patches/m150/SOURCES.md`

- [ ] Write failing tests for safe archive extraction, traversal rejection, header-manifest hashing, package layout, checksum generation, architecture command selection, and framework bundle validation.
- [ ] Run the focused tests and confirm missing behavior.
- [ ] Implement header/license collection, upstream third-party notice generation, target-specific layouts, tar/zip creation preserving symlinks, SHA-256 generation, and metadata emission.
- [ ] Implement post-build verification for static archive members, Mach-O architectures, Android jar entries, framework plist/headers/symlinks, and required codec symbols.
- [ ] Vendor only the four approved patches from Shiguredo tag `m150.7871.3.0`, preserving headers and recording source URLs and SHA-256 values.
- [ ] Re-run all unit tests and `git diff --check`.
- [ ] Commit with `feat: package and verify WebRTC artifacts`.

### Task 5: macOS merge and release composition

**Files:**
- Create: `builder/compose.py`
- Create: `tests/test_compose.py`

- [ ] Write failing tests requiring two compatible thin macOS packages, rejecting duplicate/wrong architectures and mixed metadata, producing a universal-framework command sequence, and refusing an existing release tag.
- [ ] Run `python -m unittest tests.test_compose -v` and confirm missing behavior.
- [ ] Implement safe extraction, compatibility checks, resource/header comparison, `lipo` universal binary creation, `xcodebuild -create-xcframework`, XCFramework verification, release manifest generation, and aggregate checksums.
- [ ] Extend the CLI with `merge-macos` and `release-manifest` subcommands.
- [ ] Re-run focused and full tests.
- [ ] Commit with `feat: compose macOS and release artifacts`.

### Task 6: Manual GitHub Actions

**Files:**
- Create: `.github/workflows/build-android.yml`
- Create: `.github/workflows/build-ios.yml`
- Create: `.github/workflows/build-macos-x64.yml`
- Create: `.github/workflows/build-macos-arm64.yml`
- Create: `.github/workflows/package-macos-xcframework.yml`
- Create: `.github/workflows/publish-release.yml`

- [ ] Add four build workflows containing only `workflow_dispatch`, explicit fixed runner labels, minimal permissions, disk/toolchain setup, unit tests, builder invocation, and 30-day compressed-artifact upload.
- [ ] Add an XCFramework workflow with required x64 and arm64 run ID inputs, `actions: read`, artifact download from those runs, merge invocation, and artifact upload.
- [ ] Add a release workflow with five required run IDs and a positive revision, `actions: read` plus `contents: write`, metadata validation, existing-tag rejection, and `gh release create` for five binary packages plus manifest/checksums.
- [ ] Pin every GitHub-provided action to a full commit SHA and add a comment naming its release version.
- [ ] Run `actionlint .github/workflows/*.yml`, `python -m unittest discover -s tests -v`, and `git diff --check`.
- [ ] Commit with `ci: add manual WebRTC build workflows`.

### Task 7: Documentation and local verification

**Files:**
- Create: `README.md`
- Modify: `docs/superpowers/specs/2026-07-12-m150-webrtc-builds-design.md`
- Modify: `docs/superpowers/plans/2026-07-12-m150-webrtc-builds.md`

- [ ] Document package contents, manual workflow sequence, run ID lookup, release procedure, codec behavior, license responsibility, local CLI usage, and troubleshooting without claiming unsupported fallback behavior.
- [ ] Run `python -m compileall -q builder tests`, full unit tests, actionlint, patch dry-run checks against the pinned source where feasible, and `git diff --check`.
- [ ] Append execution findings only when they alter a confirmed constraint, verification result, or follow-up.
- [ ] Commit with `docs: document M150 build and release workflow`.

### Task 8: GitHub end-to-end build and r1 release

**Files:**
- Modify only files required by failures reproduced during hosted builds; every behavioral fix starts with a failing regression test.

- [ ] Create public repository `aweffr/my-webrtc-builds`, add `origin`, and push `main`.
- [ ] Trigger all four build workflows from the same `main` commit with `gh workflow run`; record run IDs and monitor to completion.
- [ ] For any failure, inspect the exact job log, write a focused regression test when behavior is locally testable, fix, validate, commit, push, and rerun every artifact required to keep builder commits identical.
- [ ] Trigger the XCFramework workflow with the successful x64/arm64 run IDs and verify its downloaded zip contains a macOS universal `x86_64 arm64` framework.
- [ ] Trigger the Release workflow with the five successful run IDs and revision `1`; verify Release `m150.7871.3-r1` contains five binary packages, manifest, and checksums.
- [ ] Download the release assets, run checksum and metadata verification locally, and append run IDs/results to the plan's `Execution findings` section.
- [ ] Commit any documentation-only execution findings with `docs: record r1 build verification`.

### Task 9: Review, merge, and cleanup

**Files:**
- Modify implementation/tests/docs only for validated review findings.

- [ ] Run the complete local verification suite and capture commands/results.
- [ ] Dispatch a clean-context reviewer with the original request, design, plan, git range, implementation summary, E2E results, and known limitations; focus on Critical/High correctness, security, reproducibility, and missing validation.
- [ ] Fix validated issues with regression tests, rerun verification, and send the changes to the same reviewer; stop after approval or three review rounds.
- [ ] Merge the implementation branch into local `main`, push, remove the worktree and temporary branch, and confirm clean `main` plus published release.
- [ ] Report implementation, core files, design choices, tests/E2E, review findings, commits, branch/worktree status, and remaining follow-ups.

## Execution findings

No execution findings have been recorded yet.
