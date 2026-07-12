# Compose Existing M150 Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate the macOS universal XCFramework from the already successful M150 macOS artifacts, then publish all four existing platform packages plus the XCFramework as a formal release without rebuilding.

**Architecture:** The build workflows remain unchanged. The XCFramework and release workflows accept an explicit, validated artifact `builder_commit`; the workflow checkout commit remains the composer/release implementation commit and is recorded separately in diagnostics. Existing metadata and framework-public-header checks continue to enforce artifact compatibility.

**Tech Stack:** GitHub Actions workflow_dispatch, Python builder CLI, GitHub CLI, macOS `lipo`/`xcodebuild`.

---

### Task 1: Permit composing previously built artifacts

**Files:**
- Modify: `.github/workflows/package-macos-xcframework.yml`
- Modify: `.github/workflows/publish-release.yml`

- [ ] Add required `builder_commit` workflow inputs to both manual workflows.
- [ ] Pass the input commit to `builder merge-macos` and `builder release-manifest` instead of `$GITHUB_SHA`.
- [ ] Record both the composer/release checkout commit (`GITHUB_SHA`) and artifact builder commit in step summaries and release notes.
- [ ] Validate YAML with `actionlint` and inspect the diff.

### Task 2: Commit and push workflow change

**Files:**
- Modify: `.github/workflows/package-macos-xcframework.yml`
- Modify: `.github/workflows/publish-release.yml`

- [ ] Commit with conventional message `fix: compose and release existing artifacts`.
- [ ] Push the commit to `main`.

### Task 3: Compose and publish

**Files:**
- No source files; use the pushed manual workflows.

- [ ] Trigger XCFramework composition using successful runs `29194090249` and `29194091219` with builder commit `9e94c129420b3c55bd70dc67143213201e325809`.
- [ ] Monitor composition logs and diagnostics until successful.
- [ ] Trigger formal release using successful runs `29194088028`, `29194089060`, the two macOS runs above, and the successful XCFramework run.
- [ ] Verify the release is not a prerelease, contains five expected assets, and compare GitHub asset SHA-256 digests with locally downloaded/validated source assets.

