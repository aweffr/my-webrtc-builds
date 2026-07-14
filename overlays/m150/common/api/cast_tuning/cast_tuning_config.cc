#include "api/cast_tuning/cast_tuning_config.h"

#include <algorithm>
#include <iomanip>
#include <set>
#include <sstream>
#include <utility>

namespace webrtc::cast_tuning {
namespace {

template <typename T>
bool InRange(const std::optional<T>& value, T minimum, T maximum) {
  return !value || (*value >= minimum && *value <= maximum);
}

std::string CompactDouble(double value) {
  std::ostringstream stream;
  stream << std::setprecision(4) << value;
  return stream.str();
}

const char* FecModeName(FecMode mode) {
  switch (mode) {
    case FecMode::kDisabled:
      return "disabled";
    case FecMode::kUlpfec:
      return "ulpfec";
    case FecMode::kFlexfec:
      return "flexfec";
  }
  return nullptr;
}

}  // namespace

CastTuningConfig CastTuningConfig::ForProfile(Profile selected_profile,
                                              int schema_version) {
  CastTuningConfig config;
  config.schema_version = schema_version;
  config.profile = selected_profile;
  if (selected_profile == Profile::kUpstream) {
    return config;
  }

  config.enabled = true;
  config.sender.max_width = 1920;
  config.sender.max_height = 1080;
  config.sender.min_fps = 0;
  config.sender.latest_frame_only = true;
  config.sender.min_bitrate_bps = 250000;
  config.sender.degradation_preference =
      DegradationPreference::kMaintainResolution;
  config.sender.network_priority = NetworkPriority::kHigh;
  config.transport.disable_tcp_candidates = true;
  config.transport.screencast_min_bitrate_bps = 150000;
  config.pacing.screenshare_alr_probing = true;
  config.pacing.factor = 1.1;
  config.pacing.max_queue_ms = 100;
  config.encoder.realtime = true;
  config.encoder.allow_frame_reordering = false;
  config.encoder.h264_profile = schema_version >= 2 ? "CONSTRAINED_HIGH"
                                                    : "CONSTRAINED_BASELINE";
  config.encoder.h264_level = "4.1";
  if (schema_version >= 2) {
    config.encoder.video_toolbox_low_latency_rate_control = true;
  } else {
    config.encoder.data_rate_limit_factor = 1.5;
    config.encoder.data_rate_window_ms = 1000;
  }
  config.receiver.jitter_minimum_ms = 0;
  config.receiver.prerender_smoothing = false;
  config.receiver.render_lead_ms = 10;
  config.receiver.android_decoder_low_latency = true;
  config.receiver.stale_decoded_frame_ms = 150;
  config.recovery.nack_enabled = true;
  config.recovery.nack_history_ms = 1000;
  config.recovery.rtx_enabled = true;
  config.recovery.fec_mode = FecMode::kDisabled;
  config.recovery.pli_min_interval_ms = 500;
  config.recovery.no_decoded_frame_timeout_ms = 150;
  config.recovery.decoder_recreate_after_failed_pli = 2;
  config.recovery.sender_reset_after_failed_pli = 3;
  config.telemetry.sample_interval_ms = 1000;

  switch (selected_profile) {
    case Profile::kDetailIdle:
      config.sender.max_fps = 15;
      config.sender.content_mode = ContentMode::kText;
      config.sender.start_bitrate_bps = 2500000;
      config.sender.max_bitrate_bps = 6000000;
      break;
    case Profile::kDetailActive:
      config.sender.max_fps = 20;
      config.sender.content_mode = ContentMode::kText;
      config.sender.start_bitrate_bps = 3000000;
      config.sender.max_bitrate_bps = 6000000;
      break;
    case Profile::kMotion:
      config.sender.max_fps = 30;
      config.sender.content_mode = ContentMode::kFluid;
      config.sender.start_bitrate_bps = 4000000;
      config.sender.max_bitrate_bps = 8000000;
      config.sender.degradation_preference =
          DegradationPreference::kMaintainFramerate;
      break;
    case Profile::kRecovery:
      config.sender.max_width = 1280;
      config.sender.max_height = 720;
      config.sender.max_fps = 15;
      config.sender.content_mode = ContentMode::kFluid;
      config.sender.start_bitrate_bps = 1500000;
      config.sender.max_bitrate_bps = 3000000;
      break;
    case Profile::kUpstream:
      break;
  }
  return config;
}

bool CastTuningConfig::IsUpstream() const {
  return !enabled && profile == Profile::kUpstream;
}

ValidationResult CastTuningConfig::Validate() const {
  if (schema_version < kMinimumTuningSchemaVersion ||
      schema_version > kTuningSchemaVersion) {
    return ValidationResult::Error("schema_version must be 1 or 2");
  }
  if (IsUpstream()) {
    return ValidationResult::Ok();
  }
  if (!InRange(sender.max_width, 320, 3840) ||
      !InRange(sender.max_height, 180, 2160)) {
    return ValidationResult::Error("sender dimensions are out of range");
  }
  if (!InRange(sender.min_fps, 0, 60) || !InRange(sender.max_fps, 1, 60) ||
      (sender.min_fps && sender.max_fps && *sender.min_fps > *sender.max_fps)) {
    return ValidationResult::Error("sender fps values are invalid");
  }
  const int minimum = sender.min_bitrate_bps.value_or(0);
  const int start = sender.start_bitrate_bps.value_or(minimum);
  const int maximum = sender.max_bitrate_bps.value_or(std::max(start, minimum));
  if (minimum < 0 || start < minimum || maximum < start) {
    return ValidationResult::Error(
        "bitrate values must satisfy min <= start <= max");
  }
  if (!InRange(pacing.factor, 1.0, 3.0) ||
      !InRange(pacing.max_queue_ms, 10, 2000)) {
    return ValidationResult::Error("pacing values are out of range");
  }
  if (encoder.periodic_idr_seconds && (*encoder.periodic_idr_seconds < 10 ||
                                       *encoder.periodic_idr_seconds > 240)) {
    return ValidationResult::Error(
        "periodic IDR must be between 10 and 240 seconds");
  }
  const std::set<std::string> h264_profiles = {"CONSTRAINED_BASELINE",
                                               "CONSTRAINED_HIGH"};
  const std::set<std::string> h264_levels = {
      "1.0", "1.1", "1.2", "1.3", "2.0", "2.1", "2.2", "3.0",
      "3.1", "3.2", "4.0", "4.1", "4.2", "5.0", "5.1", "5.2"};
  if (encoder.h264_profile && h264_profiles.count(*encoder.h264_profile) == 0) {
    return ValidationResult::Error("unsupported H264 profile");
  }
  if (encoder.h264_level && h264_levels.count(*encoder.h264_level) == 0) {
    return ValidationResult::Error("unsupported H264 level");
  }
  if (!InRange(encoder.max_h264_slice_bytes, 512, 65535) ||
      !InRange(encoder.data_rate_limit_factor, 1.0, 3.0) ||
      !InRange(encoder.data_rate_window_ms, 100, 5000) ||
      !InRange(encoder.max_frame_delay_count, 0, 8) ||
      !InRange(encoder.max_qp, 0, 51)) {
    return ValidationResult::Error("encoder values are out of range");
  }
  if (schema_version == 1 &&
      encoder.video_toolbox_low_latency_rate_control.has_value()) {
    return ValidationResult::Error(
        "encoder.video_toolbox_low_latency_rate_control requires schema_version 2");
  }
  if (encoder.video_toolbox_low_latency_rate_control.value_or(false) &&
      (encoder.data_rate_limit_factor || encoder.data_rate_window_ms)) {
    return ValidationResult::Error(
        "encoder VideoToolbox low-latency rate control is mutually exclusive "
        "with DataRateLimits");
  }
  if (!InRange(receiver.jitter_minimum_ms, 0, 500) ||
      !InRange(receiver.render_lead_ms, 0, 100) ||
      !InRange(receiver.stale_decoded_frame_ms, 0, 5000)) {
    return ValidationResult::Error("receiver values are out of range");
  }
  if (recovery.rtx_enabled.value_or(false) &&
      !recovery.nack_enabled.value_or(false)) {
    return ValidationResult::Error("RTX requires NACK");
  }
  if (recovery.fec_mode && FecModeName(*recovery.fec_mode) == nullptr) {
    return ValidationResult::Error("unknown FEC mode");
  }
  if (!InRange(recovery.nack_history_ms, 0, 5000) ||
      !InRange(recovery.pli_min_interval_ms, 100, 5000) ||
      !InRange(recovery.no_decoded_frame_timeout_ms, 50, 5000) ||
      !InRange(recovery.decoder_recreate_after_failed_pli, 1, 20) ||
      !InRange(recovery.sender_reset_after_failed_pli, 1, 20)) {
    return ValidationResult::Error("recovery values are out of range");
  }
  if (recovery.decoder_recreate_after_failed_pli &&
      recovery.sender_reset_after_failed_pli &&
      *recovery.sender_reset_after_failed_pli <
          *recovery.decoder_recreate_after_failed_pli) {
    return ValidationResult::Error(
        "sender reset threshold must be at least the decoder recreate "
        "threshold");
  }
  if (!experimental.allow_raw_field_trials &&
      !experimental.raw_field_trials.empty()) {
    return ValidationResult::Error("raw field trials require explicit opt-in");
  }
  const std::set<std::string> typed_trials = {
      "WebRTC-ProbingScreenshareBwe", "WebRTC-Video-Pacing",
      "WebRTC-CastTuning-Recovery", "WebRTC-CastTuning-VideoToolbox"};
  for (const auto& [key, value] : experimental.raw_field_trials) {
    if (key.empty() || value.empty()) {
      return ValidationResult::Error(
          "raw field trial keys and values must be non-empty");
    }
    if (typed_trials.count(key) != 0) {
      return ValidationResult::Error(
          "raw field trial conflicts with typed field trial");
    }
  }
  return ValidationResult::Ok();
}

std::string CastTuningConfig::FieldTrialString() const {
  if (IsUpstream() || !Validate().ok()) {
    return {};
  }
  std::ostringstream trials;
  if (pacing.screenshare_alr_probing.value_or(false)) {
    trials << "WebRTC-ProbingScreenshareBwe/"
           << CompactDouble(pacing.factor.value_or(1.1)) << ','
           << pacing.max_queue_ms.value_or(100) << ",85,20,-20,1/";
  }
  if (pacing.factor || pacing.max_queue_ms) {
    trials << "WebRTC-Video-Pacing/factor:"
           << CompactDouble(pacing.factor.value_or(1.1))
           << ",max_delay:" << pacing.max_queue_ms.value_or(100) << "ms/";
  }
  if (recovery.nack_enabled || recovery.rtx_enabled || recovery.fec_mode) {
    trials << "WebRTC-CastTuning-Recovery/nack:"
           << (recovery.nack_enabled.value_or(true) ? 1 : 0)
           << ",nack_history_ms:" << recovery.nack_history_ms.value_or(1000)
           << ",rtx:" << (recovery.rtx_enabled.value_or(true) ? 1 : 0)
           << ",fec:"
           << FecModeName(recovery.fec_mode.value_or(FecMode::kDisabled))
           << ",pli_min_interval_ms:"
           << recovery.pli_min_interval_ms.value_or(500) << '/';
  }
  if (encoder.realtime || encoder.allow_frame_reordering ||
      encoder.periodic_idr_seconds || encoder.max_h264_slice_bytes ||
      encoder.data_rate_limit_factor || encoder.data_rate_window_ms ||
      encoder.max_frame_delay_count || encoder.max_qp ||
      encoder.video_toolbox_low_latency_rate_control) {
    trials << "WebRTC-CastTuning-VideoToolbox/realtime:"
           << (encoder.realtime.value_or(true) ? 1 : 0) << ",reorder:"
           << (encoder.allow_frame_reordering.value_or(false) ? 1 : 0)
           << ",idr_s:" << encoder.periodic_idr_seconds.value_or(0)
           << ",slice_bytes:" << encoder.max_h264_slice_bytes.value_or(0)
           << ",rate_factor:"
           << CompactDouble(encoder.data_rate_limit_factor.value_or(1.5))
           << ",rate_window_ms:" << encoder.data_rate_window_ms.value_or(1000)
           << ",frame_delay:" << encoder.max_frame_delay_count.value_or(-1)
           << ",max_qp:" << encoder.max_qp.value_or(-1)
           << ",low_latency_rate_control:"
           << (encoder.video_toolbox_low_latency_rate_control.value_or(false)
                   ? 1
                   : 0)
           << '/';
  }
  for (const auto& [key, value] : experimental.raw_field_trials) {
    trials << key << '/' << value << '/';
  }
  return trials.str();
}

ApplyScope CastTuningLivePatch::RequiredScope() const {
  if (pacing_factor) {
    return ApplyScope::kFactory;
  }
  if (start_bitrate_bps || periodic_idr_seconds || reset_bwe_estimate) {
    return ApplyScope::kSession;
  }
  return ApplyScope::kLive;
}

const char* ProfileName(Profile profile) {
  switch (profile) {
    case Profile::kUpstream:
      return "UPSTREAM";
    case Profile::kDetailIdle:
      return "DETAIL_IDLE";
    case Profile::kDetailActive:
      return "DETAIL_ACTIVE";
    case Profile::kMotion:
      return "MOTION";
    case Profile::kRecovery:
      return "RECOVERY";
  }
  return "UNKNOWN";
}

}  // namespace webrtc::cast_tuning
