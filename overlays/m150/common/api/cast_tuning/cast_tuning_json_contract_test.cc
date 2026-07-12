#include <cstdlib>
#include <iostream>
#include <optional>
#include <string>

#include "api/cast_tuning/cast_tuning_config.h"

namespace {

void Expect(bool condition, const char* message) {
  if (!condition) {
    std::cerr << message << '\n';
    std::exit(1);
  }
}

}  // namespace

int RunCastTuningJsonContractTests() {
  using webrtc::cast_tuning::CastTuningConfig;
  std::string error;
  std::optional<CastTuningConfig> config = CastTuningConfig::ParseJson(
      R"({"schema_version":1,"profile":"DETAIL_IDLE","sender":{"max_fps":20,"max_bitrate_bps":5000000}})",
      &error);
  Expect(config.has_value(), error.c_str());
  Expect(config->sender.max_width == 1920, "profile should be applied first");
  Expect(config->sender.max_fps == 20, "JSON should override profile fps");
  Expect(config->sender.max_bitrate_bps == 5000000,
         "JSON should override profile bitrate");

  Expect(
      !CastTuningConfig::ParseJson(
           R"({"schema_version":1,"profile":"DETAIL_IDLE","sender":{"mystery":1}})",
           &error)
           .has_value(),
      "unknown field must fail");
  Expect(error.find("sender.mystery") != std::string::npos,
         "unknown field error must contain its path");

  config = CastTuningConfig::ParseJsonWithOverrides(
      R"({"schema_version":1,"profile":"DETAIL_IDLE","sender":{"max_fps":15}})",
      "MOTION", R"({"sender":{"max_fps":20}})", &error);
  Expect(config.has_value(), error.c_str());
  Expect(config->profile == webrtc::cast_tuning::Profile::kMotion,
         "profile override must win over base JSON");
  Expect(config->sender.max_fps == 20,
         "override JSON must win over profile defaults");
  return 0;
}
