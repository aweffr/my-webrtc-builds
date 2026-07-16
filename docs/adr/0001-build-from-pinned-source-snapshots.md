# Build from pinned source snapshots

Status: Accepted

## Context

Live upstream acquisition makes a build depend on Google-hosted Git and `gclient` services after the builder revision has already been fixed.

## Decision

Each target restores immutable assets from `aweffr/webrtc-source-snapshots` and validates consumer-pinned manifest, part, and archive digests. There is no Google checkout, `gclient sync`, hooks, or fallback. Snapshot `depot_tools` provides only GN and Ninja. CastTuning, Java 8, and codec changes remain owned by the current builder revision and are applied after restore.

## Consequences

A missing or mismatched snapshot fails the build. Updating the WebRTC baseline or snapshot requires an explicit code change to the target's `SnapshotSpec`.
