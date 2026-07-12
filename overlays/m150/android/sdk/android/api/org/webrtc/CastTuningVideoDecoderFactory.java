package org.webrtc;

import androidx.annotation.Nullable;

/** Default decoder factory with an optional Android MediaCodec low-latency request. */
public final class CastTuningVideoDecoderFactory extends DefaultVideoDecoderFactory {
  public CastTuningVideoDecoderFactory(
      @Nullable EglBase.Context sharedContext, boolean lowLatency) {
    super(new CastTuningHardwareVideoDecoderFactory(sharedContext, lowLatency));
  }

  private static final class CastTuningHardwareVideoDecoderFactory
      extends MediaCodecVideoDecoderFactory {
    CastTuningHardwareVideoDecoderFactory(
        @Nullable EglBase.Context sharedContext, boolean lowLatency) {
      super(sharedContext, null, lowLatency);
    }
  }
}
