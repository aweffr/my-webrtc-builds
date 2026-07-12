package org.webrtc;

import java.util.Collections;
import java.util.Map;

/** Immutable inputs used to create a CastTuning controller. */
public final class CastTuningConfig {
  public static final String PROFILE_ENV = "CAST_TUNING_PROFILE";
  public static final String OVERRIDES_ENV = "CAST_TUNING_OVERRIDES_JSON";

  private final String baseJson;
  private final String profileOverride;
  private final String overridesJson;

  private CastTuningConfig(String baseJson, String profileOverride, String overridesJson) {
    if (baseJson == null || baseJson.trim().isEmpty()) {
      throw new IllegalArgumentException("CastTuning JSON must not be blank");
    }
    this.baseJson = baseJson;
    this.profileOverride = emptyToNull(profileOverride);
    this.overridesJson = emptyToNull(overridesJson);
  }

  public static CastTuningConfig fromJson(String json) {
    return new CastTuningConfig(json, null, null);
  }

  public static CastTuningConfig fromSources(String json, Map<String, String> environment) {
    Map<String, String> safeEnvironment =
        environment == null ? Collections.emptyMap() : environment;
    return new CastTuningConfig(
        json, safeEnvironment.get(PROFILE_ENV), safeEnvironment.get(OVERRIDES_ENV));
  }

  public static CastTuningConfig fromOverrides(
      String json, String profileOverride, String overridesJson) {
    return new CastTuningConfig(json, profileOverride, overridesJson);
  }

  public static CastTuningConfig fromProcessEnvironment(String json) {
    return fromSources(json, System.getenv());
  }

  public String baseJson() {
    return baseJson;
  }

  public String profileOverride() {
    return profileOverride;
  }

  public String overridesJson() {
    return overridesJson;
  }

  private static String emptyToNull(String value) {
    return value == null || value.trim().isEmpty() ? null : value;
  }
}
