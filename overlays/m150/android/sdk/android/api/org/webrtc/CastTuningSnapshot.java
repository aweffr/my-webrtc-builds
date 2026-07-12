package org.webrtc;

/** Immutable description of the effective CastTuning configuration. */
public final class CastTuningSnapshot {
  public final String sessionId;
  public final String effectiveConfigHash;
  public final long revision;
  public final boolean recreateRequired;

  public CastTuningSnapshot(
      String sessionId, String effectiveConfigHash, long revision, boolean recreateRequired) {
    this.sessionId = sessionId;
    this.effectiveConfigHash = effectiveConfigHash;
    this.revision = revision;
    this.recreateRequired = recreateRequired;
  }
}
