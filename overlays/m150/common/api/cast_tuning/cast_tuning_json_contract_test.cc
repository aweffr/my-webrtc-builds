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
  using webrtc::cast_tuning::SpatialAdaptiveQpMode;
  std::string error;
  std::optional<CastTuningConfig> config = CastTuningConfig::ParseJson(
      R"({"schema_version":1,"profile":"DETAIL_IDLE","sender":{"max_fps":20,"max_bitrate_bps":5000000}})",
      &error);
  Expect(config.has_value(), error.c_str());
  Expect(config->sender.max_width == 1920, "profile should be applied first");
  Expect(config->sender.max_fps == 20, "JSON should override profile fps");
  Expect(config->sender.max_bitrate_bps == 5000000,
         "JSON should override profile bitrate");
  Expect(config->encoder.h264_profile == "CONSTRAINED_BASELINE",
         "schema v1 JSON must retain constrained baseline");
  Expect(!config->encoder.video_toolbox_low_latency_rate_control,
         "schema v1 JSON must not enable VideoToolbox low latency");

  config = CastTuningConfig::ParseJson(
      R"({"schema_version":2,"profile":"DETAIL_IDLE","encoder":{"h264_profile":"CONSTRAINED_BASELINE","video_toolbox_low_latency_rate_control":true}})",
      &error);
  Expect(config.has_value(), error.c_str());
  Expect(config->encoder.h264_profile == "CONSTRAINED_BASELINE",
         "schema v2 must allow an explicit constrained baseline request");
  Expect(config->encoder.video_toolbox_low_latency_rate_control == true,
         "schema v2 must parse the VideoToolbox low-latency setting");

  Expect(
      !CastTuningConfig::ParseJson(
           R"({"schema_version":1,"profile":"DETAIL_IDLE","encoder":{"video_toolbox_low_latency_rate_control":true}})",
           &error)
           .has_value(),
      "schema v1 must reject the schema v2 VideoToolbox setting");
  Expect(error.find("requires schema_version 2") != std::string::npos,
         "schema v1 rejection must identify the required schema");

  Expect(
      !CastTuningConfig::ParseJson(
           R"({"schema_version":2,"profile":"DETAIL_IDLE","encoder":{"video_toolbox_low_latency_rate_control":true,"data_rate_limit_factor":1.5}})",
           &error)
           .has_value(),
      "low-latency rate control and DataRateLimits must be mutually exclusive");
  Expect(error.find("mutually exclusive") != std::string::npos,
         "DataRateLimits conflict must be explicit");

  config = CastTuningConfig::ParseJson(
      R"({"schema_version":3,"profile":"UPSTREAM","enabled":true,"encoder":{"video_toolbox_low_latency_rate_control":false,"video_toolbox_spatial_adaptive_qp":"DEFAULT"}})",
      &error);
  Expect(config.has_value(), error.c_str());
  Expect(config->encoder.video_toolbox_spatial_adaptive_qp ==
             SpatialAdaptiveQpMode::kDefault,
         "schema v3 must parse DEFAULT spatial adaptive QP");

  config = CastTuningConfig::ParseJson(
      R"({"schema_version":3,"profile":"UPSTREAM","enabled":true,"encoder":{"video_toolbox_low_latency_rate_control":false,"video_toolbox_spatial_adaptive_qp":"DISABLE"}})",
      &error);
  Expect(config.has_value(), error.c_str());
  Expect(config->encoder.video_toolbox_spatial_adaptive_qp ==
             SpatialAdaptiveQpMode::kDisable,
         "schema v3 must parse DISABLE spatial adaptive QP");

  Expect(!CastTuningConfig::ParseJson(
              R"({"schema_version":2,"profile":"UPSTREAM","enabled":true,"encoder":{"video_toolbox_spatial_adaptive_qp":"DEFAULT"}})",
              &error)
              .has_value(),
         "schema v2 must reject the schema v3 spatial adaptive QP setting");
  Expect(error.find("requires schema_version 3") != std::string::npos,
         "schema v2 rejection must identify schema version 3");

  Expect(!CastTuningConfig::ParseJson(
              R"({"schema_version":3,"profile":"UPSTREAM","enabled":true,"encoder":{"video_toolbox_spatial_adaptive_qp":"UNKNOWN"}})",
              &error)
              .has_value(),
         "unknown spatial adaptive QP mode must fail");

  Expect(!CastTuningConfig::ParseJson(
              R"({"schema_version":3,"profile":"UPSTREAM","enabled":true,"encoder":{"video_toolbox_low_latency_rate_control":true,"video_toolbox_spatial_adaptive_qp":"DEFAULT"}})",
              &error)
              .has_value(),
         "spatial adaptive QP and low-latency rate control must conflict");
  Expect(error.find("spatial adaptive QP") != std::string::npos,
         "spatial adaptive QP conflict must be explicit");

  Expect(!CastTuningConfig::ParseJson(
              R"({"schema_version":4,"profile":"DETAIL_IDLE"})", &error)
              .has_value(),
         "future schema versions must fail closed");

  Expect(
      !CastTuningConfig::ParseJson(
           R"({"schema_version":1,"profile":"DETAIL_IDLE","sender":{"mystery":1}})",
           &error)
           .has_value(),
      "unknown field must fail");
  Expect(error.find("sender.mystery") != std::string::npos,
         "unknown field error must contain its path");

  config = CastTuningConfig::ParseJsonWithOverrides(
      R"({"schema_version":2,"profile":"DETAIL_IDLE","sender":{"max_fps":15}})",
      "MOTION", R"({"sender":{"max_fps":20}})", &error);
  Expect(config.has_value(), error.c_str());
  Expect(config->profile == webrtc::cast_tuning::Profile::kMotion,
         "profile override must win over base JSON");
  Expect(config->sender.max_fps == 20,
         "override JSON must win over profile defaults");
  return 0;
}
