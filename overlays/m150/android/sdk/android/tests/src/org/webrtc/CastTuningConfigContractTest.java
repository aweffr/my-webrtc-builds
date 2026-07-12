package org.webrtc;

import java.util.HashMap;
import java.util.Map;

public final class CastTuningConfigContractTest {
  private static void expect(boolean condition, String message) {
    if (!condition) {
      throw new AssertionError(message);
    }
  }

  public static void main(String[] args) {
    Map<String, String> environment = new HashMap<>();
    environment.put("CAST_TUNING_PROFILE", "MOTION");
    environment.put(
        "CAST_TUNING_OVERRIDES_JSON", "{\"sender\":{\"max_fps\":20}}");
    CastTuningConfig config = CastTuningConfig.fromSources(
        "{\"schema_version\":1,\"profile\":\"DETAIL_IDLE\"}", environment);
    expect(config.profileOverride().equals("MOTION"), "profile environment override");
    expect(config.overridesJson().contains("max_fps"), "JSON environment override");
    expect(config.baseJson().contains("DETAIL_IDLE"), "base JSON is retained");

    CastTuningConfig direct = CastTuningConfig.fromJson(
        "{\"schema_version\":1,\"profile\":\"UPSTREAM\"}");
    expect(direct.profileOverride() == null, "direct JSON has no profile override");
    expect(direct.overridesJson() == null, "direct JSON has no override document");

    CastTuningConfig intentValues = CastTuningConfig.fromOverrides(
        direct.baseJson(), "RECOVERY", "{\"receiver\":{\"jitter_minimum_ms\":0}}");
    expect(intentValues.profileOverride().equals("RECOVERY"), "intent profile override");
    expect(intentValues.overridesJson().contains("jitter_minimum_ms"),
        "intent JSON override");

    boolean rejected = false;
    try {
      CastTuningConfig.fromJson(" ");
    } catch (IllegalArgumentException expected) {
      rejected = true;
    }
    expect(rejected, "blank JSON must be rejected");
    System.out.println("CastTuning Java tests passed");
  }
}
