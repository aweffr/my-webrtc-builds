# WebRTC Build Distribution

This context defines the source and artifact identities used to produce reproducible WebRTC CastKit distributions.

## Language

**Snapshot-backed build**:
A build whose complete baseline source input is an immutable Source Snapshot rather than a live upstream checkout.
_Avoid_: Cached checkout, offline checkout

**Source Snapshot**:
A target-specific, immutable WebRTC baseline that has completed upstream source preparation but contains no project patches or build outputs.
_Avoid_: Source cache, source bundle

**Snapshot Contract**:
The independently pinned identity and integrity record a consumer requires before accepting a Source Snapshot.
_Avoid_: Latest snapshot, release pointer
