package org.webrtc;

/** Applies validated CastTuning configuration to Android WebRTC objects. */
public final class CastTuningController implements AutoCloseable {
  private long nativeController;

  public CastTuningController(CastTuningConfig config) {
    if (config == null) {
      throw new IllegalArgumentException("CastTuning config must not be null");
    }
    nativeController = nativeCreate(
        config.baseJson(), config.profileOverride(), config.overridesJson());
    if (nativeController == 0) {
      throw new IllegalArgumentException("CastTuning configuration is invalid");
    }
  }

  public PeerConnectionFactory.Builder configureFactory(PeerConnectionFactory.Builder builder) {
    checkOpen();
    if (builder == null) {
      throw new IllegalArgumentException("PeerConnectionFactory.Builder must not be null");
    }
    String fieldTrials = nativeGetFieldTrials(nativeController);
    if (!fieldTrials.isEmpty()) {
      builder.setFieldTrials(fieldTrials);
    }
    return builder;
  }

  public PeerConnection.RTCConfiguration configurePeerConnection(
      PeerConnection.RTCConfiguration configuration) {
    checkOpen();
    if (configuration == null) {
      throw new IllegalArgumentException("RTCConfiguration must not be null");
    }
    int relayOnly = nativeGetRelayOnly(nativeController);
    if (relayOnly >= 0) {
      configuration.iceTransportsType = relayOnly == 1
          ? PeerConnection.IceTransportsType.RELAY
          : PeerConnection.IceTransportsType.ALL;
    }
    int disableTcpCandidates = nativeGetDisableTcpCandidates(nativeController);
    if (disableTcpCandidates >= 0) {
      configuration.tcpCandidatePolicy = disableTcpCandidates == 1
          ? PeerConnection.TcpCandidatePolicy.DISABLED
          : PeerConnection.TcpCandidatePolicy.ENABLED;
    }
    int screencastMinBitrateBps = nativeGetScreencastMinBitrateBps(nativeController);
    if (screencastMinBitrateBps >= 0) {
      configuration.screencastMinBitrate = screencastMinBitrateBps;
    }
    int prerendererSmoothing = nativeGetPrerendererSmoothing(nativeController);
    if (prerendererSmoothing >= 0) {
      configuration.enablePrerendererSmoothing = prerendererSmoothing == 1;
    }
    int renderLeadMs = nativeGetRenderLeadMs(nativeController);
    if (renderLeadMs >= 0) {
      configuration.videoRenderDelayMs = renderLeadMs;
    }
    return configuration;
  }

  public void attachReceiver(RtpReceiver receiver) {
    checkOpen();
    if (receiver == null) {
      throw new IllegalArgumentException("RtpReceiver must not be null");
    }
    int jitterMinimumMs = nativeGetJitterMinimumMs(nativeController);
    if (jitterMinimumMs >= 0) {
      receiver.setJitterBufferMinimumDelay(jitterMinimumMs / 1000.0);
    }
  }

  public boolean androidDecoderLowLatencyEnabled() {
    checkOpen();
    return nativeGetAndroidDecoderLowLatency(nativeController);
  }

  public CastTuningVideoDecoderFactory createVideoDecoderFactory(
      EglBase.Context sharedContext) {
    return new CastTuningVideoDecoderFactory(
        sharedContext, androidDecoderLowLatencyEnabled());
  }

  public CastTuningSnapshot snapshot() {
    checkOpen();
    return new CastTuningSnapshot(
        nativeGetSessionId(nativeController),
        nativeGetEffectiveConfigHash(nativeController),
        nativeGetRevision(nativeController),
        nativeGetRecreateRequired(nativeController));
  }

  @Override
  public void close() {
    if (nativeController != 0) {
      nativeFree(nativeController);
      nativeController = 0;
    }
  }

  private void checkOpen() {
    if (nativeController == 0) {
      throw new IllegalStateException("CastTuningController is closed");
    }
  }

  private static native long nativeCreate(
      String baseJson, String profileOverride, String overridesJson);
  private static native String nativeGetFieldTrials(long pointer);
  private static native int nativeGetPrerendererSmoothing(long pointer);
  private static native int nativeGetRelayOnly(long pointer);
  private static native int nativeGetDisableTcpCandidates(long pointer);
  private static native int nativeGetScreencastMinBitrateBps(long pointer);
  private static native int nativeGetRenderLeadMs(long pointer);
  private static native int nativeGetJitterMinimumMs(long pointer);
  private static native boolean nativeGetAndroidDecoderLowLatency(long pointer);
  private static native String nativeGetSessionId(long pointer);
  private static native String nativeGetEffectiveConfigHash(long pointer);
  private static native long nativeGetRevision(long pointer);
  private static native boolean nativeGetRecreateRequired(long pointer);
  private static native void nativeFree(long pointer);
}
