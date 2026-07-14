#include <initializer_list>
#include <map>
#include <memory>
#include <set>
#include <string>

#include "api/cast_tuning/cast_tuning_config.h"
#include "rtc_base/strings/json.h"

namespace webrtc::cast_tuning {
namespace {

bool ParseDocument(const std::string& json,
                   Json::Value* output,
                   std::string* error) {
  Json::CharReaderBuilder builder;
  builder["collectComments"] = false;
  std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
  return reader->parse(json.data(), json.data() + json.size(), output, error);
}

void MergeObject(const Json::Value& overrides, Json::Value* destination) {
  for (const std::string& key : overrides.getMemberNames()) {
    if (overrides[key].isObject() && (*destination)[key].isObject()) {
      MergeObject(overrides[key], &(*destination)[key]);
    } else {
      (*destination)[key] = overrides[key];
    }
  }
}

bool CheckObject(const Json::Value& value,
                 const std::string& path,
                 std::initializer_list<const char*> allowed,
                 std::string* error) {
  if (!value.isObject()) {
    *error = path + " must be an object";
    return false;
  }
  const std::set<std::string> keys(allowed.begin(), allowed.end());
  for (const std::string& member : value.getMemberNames()) {
    if (keys.count(member) == 0) {
      *error = path.empty() ? member : path + "." + member;
      *error += " is not a recognized CastTuning field";
      return false;
    }
  }
  return true;
}

bool ReadInt(const Json::Value& object,
             const char* key,
             const std::string& path,
             std::optional<int>* output,
             std::string* error) {
  if (!object.isMember(key))
    return true;
  if (!object[key].isInt()) {
    *error = path + "." + key + " must be an integer";
    return false;
  }
  *output = object[key].asInt();
  return true;
}

bool ReadDouble(const Json::Value& object,
                const char* key,
                const std::string& path,
                std::optional<double>* output,
                std::string* error) {
  if (!object.isMember(key))
    return true;
  if (!object[key].isNumeric()) {
    *error = path + "." + key + " must be numeric";
    return false;
  }
  *output = object[key].asDouble();
  return true;
}

bool ReadBool(const Json::Value& object,
              const char* key,
              const std::string& path,
              std::optional<bool>* output,
              std::string* error) {
  if (!object.isMember(key))
    return true;
  if (!object[key].isBool()) {
    *error = path + "." + key + " must be boolean";
    return false;
  }
  *output = object[key].asBool();
  return true;
}

bool ReadString(const Json::Value& object,
                const char* key,
                const std::string& path,
                std::optional<std::string>* output,
                std::string* error) {
  if (!object.isMember(key))
    return true;
  if (!object[key].isString()) {
    *error = path + "." + key + " must be a string";
    return false;
  }
  *output = object[key].asString();
  return true;
}

template <typename Enum>
bool ReadEnum(const Json::Value& object,
              const char* key,
              const std::string& path,
              const std::map<std::string, Enum>& values,
              std::optional<Enum>* output,
              std::string* error) {
  if (!object.isMember(key))
    return true;
  if (!object[key].isString()) {
    *error = path + "." + key + " must be a string";
    return false;
  }
  auto found = values.find(object[key].asString());
  if (found == values.end()) {
    *error = path + "." + key + " has an unsupported value";
    return false;
  }
  *output = found->second;
  return true;
}

std::optional<Profile> ParseProfile(const Json::Value& root,
                                    std::string* error) {
  if (!root.isMember("profile"))
    return Profile::kUpstream;
  if (!root["profile"].isString()) {
    *error = "profile must be a string";
    return std::nullopt;
  }
  const std::map<std::string, Profile> profiles = {
      {"UPSTREAM", Profile::kUpstream},
      {"DETAIL_IDLE", Profile::kDetailIdle},
      {"DETAIL_ACTIVE", Profile::kDetailActive},
      {"MOTION", Profile::kMotion},
      {"RECOVERY", Profile::kRecovery},
  };
  auto found = profiles.find(root["profile"].asString());
  if (found == profiles.end()) {
    *error = "profile has an unsupported value";
    return std::nullopt;
  }
  return found->second;
}

bool ParseSender(const Json::Value& value,
                 SenderConfig* sender,
                 std::string* error) {
  if (!CheckObject(
          value, "sender",
          {"max_width", "max_height", "min_fps", "max_fps", "latest_frame_only",
           "content_mode", "min_bitrate_bps", "start_bitrate_bps",
           "max_bitrate_bps", "degradation_preference", "network_priority"},
          error)) {
    return false;
  }
  return ReadInt(value, "max_width", "sender", &sender->max_width, error) &&
         ReadInt(value, "max_height", "sender", &sender->max_height, error) &&
         ReadInt(value, "min_fps", "sender", &sender->min_fps, error) &&
         ReadInt(value, "max_fps", "sender", &sender->max_fps, error) &&
         ReadBool(value, "latest_frame_only", "sender",
                  &sender->latest_frame_only, error) &&
         ReadEnum(
             value, "content_mode", "sender",
             {{"TEXT", ContentMode::kText}, {"FLUID", ContentMode::kFluid}},
             &sender->content_mode, error) &&
         ReadInt(value, "min_bitrate_bps", "sender", &sender->min_bitrate_bps,
                 error) &&
         ReadInt(value, "start_bitrate_bps", "sender",
                 &sender->start_bitrate_bps, error) &&
         ReadInt(value, "max_bitrate_bps", "sender", &sender->max_bitrate_bps,
                 error) &&
         ReadEnum(value, "degradation_preference", "sender",
                  {{"MAINTAIN_RESOLUTION",
                    DegradationPreference::kMaintainResolution},
                   {"MAINTAIN_FRAMERATE",
                    DegradationPreference::kMaintainFramerate}},
                  &sender->degradation_preference, error) &&
         ReadEnum(value, "network_priority", "sender",
                  {{"LOW", NetworkPriority::kLow},
                   {"MEDIUM", NetworkPriority::kMedium},
                   {"HIGH", NetworkPriority::kHigh}},
                  &sender->network_priority, error);
}

bool ParseTransport(const Json::Value& value,
                    TransportConfig* transport,
                    std::string* error) {
  if (!CheckObject(value, "transport",
                   {"relay_only", "disable_tcp_candidates",
                    "screencast_min_bitrate_bps", "allow_probe_without_media"},
                   error)) {
    return false;
  }
  return ReadBool(value, "relay_only", "transport", &transport->relay_only,
                  error) &&
         ReadBool(value, "disable_tcp_candidates", "transport",
                  &transport->disable_tcp_candidates, error) &&
         ReadInt(value, "screencast_min_bitrate_bps", "transport",
                 &transport->screencast_min_bitrate_bps, error) &&
         ReadBool(value, "allow_probe_without_media", "transport",
                  &transport->allow_probe_without_media, error);
}

bool ParsePacing(const Json::Value& value,
                 PacingConfig* pacing,
                 std::string* error) {
  if (!CheckObject(value, "pacing",
                   {"screenshare_alr_probing", "factor", "max_queue_ms"},
                   error)) {
    return false;
  }
  return ReadBool(value, "screenshare_alr_probing", "pacing",
                  &pacing->screenshare_alr_probing, error) &&
         ReadDouble(value, "factor", "pacing", &pacing->factor, error) &&
         ReadInt(value, "max_queue_ms", "pacing", &pacing->max_queue_ms, error);
}

bool ParseEncoder(const Json::Value& value,
                  EncoderConfig* encoder,
                  std::string* error) {
  if (!CheckObject(value, "encoder",
                   {"hardware_policy", "realtime", "allow_frame_reordering",
                    "h264_profile", "h264_level", "periodic_idr_seconds",
                    "max_h264_slice_bytes", "data_rate_limit_factor",
                    "data_rate_window_ms", "max_frame_delay_count", "max_qp",
                    "video_toolbox_low_latency_rate_control"},
                   error)) {
    return false;
  }
  if (value.isMember("hardware_policy")) {
    if (!value["hardware_policy"].isString()) {
      *error = "encoder.hardware_policy must be a string";
      return false;
    }
    const std::map<std::string, HardwarePolicy> policies = {
        {"PREFER_HARDWARE", HardwarePolicy::kPreferHardware},
        {"REQUIRE_HARDWARE", HardwarePolicy::kRequireHardware},
        {"ALLOW_SOFTWARE", HardwarePolicy::kAllowSoftware},
    };
    auto found = policies.find(value["hardware_policy"].asString());
    if (found == policies.end()) {
      *error = "encoder.hardware_policy has an unsupported value";
      return false;
    }
    encoder->hardware_policy = found->second;
  }
  return ReadBool(value, "realtime", "encoder", &encoder->realtime, error) &&
         ReadBool(value, "allow_frame_reordering", "encoder",
                  &encoder->allow_frame_reordering, error) &&
         ReadString(value, "h264_profile", "encoder", &encoder->h264_profile,
                    error) &&
         ReadString(value, "h264_level", "encoder", &encoder->h264_level,
                    error) &&
         ReadInt(value, "periodic_idr_seconds", "encoder",
                 &encoder->periodic_idr_seconds, error) &&
         ReadInt(value, "max_h264_slice_bytes", "encoder",
                 &encoder->max_h264_slice_bytes, error) &&
         ReadDouble(value, "data_rate_limit_factor", "encoder",
                    &encoder->data_rate_limit_factor, error) &&
         ReadInt(value, "data_rate_window_ms", "encoder",
                 &encoder->data_rate_window_ms, error) &&
         ReadInt(value, "max_frame_delay_count", "encoder",
                 &encoder->max_frame_delay_count, error) &&
         ReadInt(value, "max_qp", "encoder", &encoder->max_qp, error) &&
         ReadBool(value, "video_toolbox_low_latency_rate_control", "encoder",
                  &encoder->video_toolbox_low_latency_rate_control, error);
}

bool ParseReceiver(const Json::Value& value,
                   ReceiverConfig* receiver,
                   std::string* error) {
  if (!CheckObject(
          value, "receiver",
          {"jitter_minimum_ms", "prerender_smoothing", "render_lead_ms",
           "android_decoder_low_latency", "stale_decoded_frame_ms"},
          error)) {
    return false;
  }
  return ReadInt(value, "jitter_minimum_ms", "receiver",
                 &receiver->jitter_minimum_ms, error) &&
         ReadBool(value, "prerender_smoothing", "receiver",
                  &receiver->prerender_smoothing, error) &&
         ReadInt(value, "render_lead_ms", "receiver", &receiver->render_lead_ms,
                 error) &&
         ReadBool(value, "android_decoder_low_latency", "receiver",
                  &receiver->android_decoder_low_latency, error) &&
         ReadInt(value, "stale_decoded_frame_ms", "receiver",
                 &receiver->stale_decoded_frame_ms, error);
}

bool ParseRecovery(const Json::Value& value,
                   RecoveryConfig* recovery,
                   std::string* error) {
  if (!CheckObject(
          value, "recovery",
          {"nack_enabled", "nack_history_ms", "rtx_enabled", "fec_mode",
           "pli_min_interval_ms", "no_decoded_frame_timeout_ms",
           "decoder_recreate_after_failed_pli",
           "sender_reset_after_failed_pli"},
          error)) {
    return false;
  }
  return ReadBool(value, "nack_enabled", "recovery", &recovery->nack_enabled,
                  error) &&
         ReadInt(value, "nack_history_ms", "recovery",
                 &recovery->nack_history_ms, error) &&
         ReadBool(value, "rtx_enabled", "recovery", &recovery->rtx_enabled,
                  error) &&
         ReadEnum(value, "fec_mode", "recovery",
                  {{"DISABLED", FecMode::kDisabled},
                   {"ULPFEC", FecMode::kUlpfec},
                   {"FLEXFEC", FecMode::kFlexfec}},
                  &recovery->fec_mode, error) &&
         ReadInt(value, "pli_min_interval_ms", "recovery",
                 &recovery->pli_min_interval_ms, error) &&
         ReadInt(value, "no_decoded_frame_timeout_ms", "recovery",
                 &recovery->no_decoded_frame_timeout_ms, error) &&
         ReadInt(value, "decoder_recreate_after_failed_pli", "recovery",
                 &recovery->decoder_recreate_after_failed_pli, error) &&
         ReadInt(value, "sender_reset_after_failed_pli", "recovery",
                 &recovery->sender_reset_after_failed_pli, error);
}

bool ParseTelemetry(const Json::Value& value,
                    TelemetryConfig* telemetry,
                    std::string* error) {
  if (!CheckObject(value, "telemetry",
                   {"sample_interval_ms", "jsonl_path", "rtc_event_log"},
                   error)) {
    return false;
  }
  return ReadInt(value, "sample_interval_ms", "telemetry",
                 &telemetry->sample_interval_ms, error) &&
         ReadString(value, "jsonl_path", "telemetry", &telemetry->jsonl_path,
                    error) &&
         ReadBool(value, "rtc_event_log", "telemetry",
                  &telemetry->rtc_event_log, error);
}

bool ParseExperimental(const Json::Value& value,
                       ExperimentalConfig* experimental,
                       std::string* error) {
  if (!CheckObject(value, "experimental",
                   {"allow_raw_field_trials", "raw_field_trials"}, error)) {
    return false;
  }
  if (value.isMember("allow_raw_field_trials")) {
    if (!value["allow_raw_field_trials"].isBool()) {
      *error = "experimental.allow_raw_field_trials must be boolean";
      return false;
    }
    experimental->allow_raw_field_trials =
        value["allow_raw_field_trials"].asBool();
  }
  if (value.isMember("raw_field_trials")) {
    const Json::Value& trials = value["raw_field_trials"];
    if (!trials.isObject()) {
      *error = "experimental.raw_field_trials must be an object";
      return false;
    }
    for (const std::string& key : trials.getMemberNames()) {
      if (!trials[key].isString()) {
        *error = "experimental.raw_field_trials." + key + " must be a string";
        return false;
      }
      experimental->raw_field_trials[key] = trials[key].asString();
    }
  }
  return true;
}

}  // namespace

std::optional<CastTuningConfig> CastTuningConfig::ParseJson(
    const std::string& json,
    std::string* error) {
  if (error == nullptr)
    return std::nullopt;
  error->clear();
  Json::Value root;
  if (!ParseDocument(json, &root, error)) {
    return std::nullopt;
  }
  if (!CheckObject(
          root, "",
          {"schema_version", "profile", "sender", "transport", "pacing",
           "encoder", "receiver", "recovery", "telemetry", "experimental"},
          error)) {
    return std::nullopt;
  }
  if (!root.isMember("schema_version") || !root["schema_version"].isInt()) {
    *error = "schema_version must be an integer";
    return std::nullopt;
  }
  const int schema_version = root["schema_version"].asInt();
  if (schema_version < kMinimumTuningSchemaVersion ||
      schema_version > kTuningSchemaVersion) {
    *error = "schema_version must be 1 or 2";
    return std::nullopt;
  }
  std::optional<Profile> profile = ParseProfile(root, error);
  if (!profile)
    return std::nullopt;
  CastTuningConfig config = ForProfile(*profile, schema_version);
  config.enabled = *profile != Profile::kUpstream || root.size() > 2;
  if ((root.isMember("sender") &&
       !ParseSender(root["sender"], &config.sender, error)) ||
      (root.isMember("transport") &&
       !ParseTransport(root["transport"], &config.transport, error)) ||
      (root.isMember("pacing") &&
       !ParsePacing(root["pacing"], &config.pacing, error)) ||
      (root.isMember("encoder") &&
       !ParseEncoder(root["encoder"], &config.encoder, error)) ||
      (root.isMember("receiver") &&
       !ParseReceiver(root["receiver"], &config.receiver, error)) ||
      (root.isMember("recovery") &&
       !ParseRecovery(root["recovery"], &config.recovery, error)) ||
      (root.isMember("telemetry") &&
       !ParseTelemetry(root["telemetry"], &config.telemetry, error)) ||
      (root.isMember("experimental") &&
       !ParseExperimental(root["experimental"], &config.experimental, error))) {
    return std::nullopt;
  }
  ValidationResult validation = config.Validate();
  if (!validation.ok()) {
    *error = validation.error;
    return std::nullopt;
  }
  return config;
}

std::optional<CastTuningConfig> CastTuningConfig::ParseJsonWithOverrides(
    const std::string& json,
    const std::string& profile_override,
    const std::string& overrides_json,
    std::string* error) {
  if (error == nullptr)
    return std::nullopt;
  Json::Value root;
  if (!ParseDocument(json, &root, error) || !root.isObject()) {
    if (error->empty())
      *error = "base CastTuning JSON must be an object";
    return std::nullopt;
  }
  if (!profile_override.empty())
    root["profile"] = profile_override;
  if (!overrides_json.empty()) {
    Json::Value overrides;
    if (!ParseDocument(overrides_json, &overrides, error) ||
        !overrides.isObject()) {
      if (error->empty())
        *error = "CastTuning overrides JSON must be an object";
      return std::nullopt;
    }
    MergeObject(overrides, &root);
  }
  // M150's JsonValueToString() unconditionally removes one trailing byte,
  // while the rolled JsonCpp writer no longer emits a trailing newline.
  // Serialize directly here so the closing object delimiter is preserved.
  Json::StreamWriterBuilder writer;
  return ParseJson(Json::writeString(writer, root), error);
}

}  // namespace webrtc::cast_tuning
