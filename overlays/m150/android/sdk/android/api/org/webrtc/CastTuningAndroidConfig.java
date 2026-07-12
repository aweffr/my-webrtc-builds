package org.webrtc;

import android.content.Intent;
import androidx.annotation.Nullable;

/** Android Intent adapter for CastTuning session overrides. */
public final class CastTuningAndroidConfig {
  public static final String EXTRA_PROFILE = "org.webrtc.cast_tuning.PROFILE";
  public static final String EXTRA_OVERRIDES_JSON =
      "org.webrtc.cast_tuning.OVERRIDES_JSON";

  private CastTuningAndroidConfig() {}

  public static CastTuningConfig fromIntent(
      String baseJson, @Nullable Intent intent) {
    if (intent == null) {
      return CastTuningConfig.fromJson(baseJson);
    }
    return CastTuningConfig.fromOverrides(
        baseJson,
        intent.getStringExtra(EXTRA_PROFILE),
        intent.getStringExtra(EXTRA_OVERRIDES_JSON));
  }
}
