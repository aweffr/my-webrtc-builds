#ifndef API_CAST_TUNING_CAST_TUNING_CONFIG_H_
#define API_CAST_TUNING_CAST_TUNING_CONFIG_H_

#include <map>
#include <optional>
#include <string>

namespace webrtc::cast_tuning {

inline constexpr int kTuningSchemaVersion = 3;
inline constexpr int kMinimumTuningSchemaVersion = 1;

enum class Profile {
  kUpstream,
  kDetailIdle,
  kDetailActive,
  kMotion,
  kRecovery
};
enum class ApplyScope { kLive, kSession, kFactory };
enum class ContentMode { kUnspecified, kText, kFluid };
enum class DegradationPreference {
  kUnspecified,
  kMaintainResolution,
  kMaintainFramerate,
};
enum class NetworkPriority { kUnspecified, kLow, kMedium, kHigh };
enum class HardwarePolicy { kPreferHardware, kRequireHardware, kAllowSoftware };
enum class FecMode { kDisabled, kUlpfec, kFlexfec };
enum class SpatialAdaptiveQpMode { kDefault, kDisable };

struct ValidationResult {
  std::string error;
  bool ok() const { return error.empty(); }
  static ValidationResult Ok() { return {}; }
  static ValidationResult Error(std::string message) {
    return {.error = std::move(message)};
  }
};

struct SenderConfig {
  std::optional<int> max_width;
  std::optional<int> max_height;
  std::optional<int> min_fps;
  std::optional<int> max_fps;
  std::optional<bool> latest_frame_only;
  std::optional<ContentMode> content_mode;
  std::optional<int> min_bitrate_bps;
  std::optional<int> start_bitrate_bps;
  std::optional<int> max_bitrate_bps;
  std::optional<DegradationPreference> degradation_preference;
  std::optional<NetworkPriority> network_priority;
};

struct TransportConfig {
  std::optional<bool> relay_only;
  std::optional<bool> disable_tcp_candidates;
  std::optional<int> screencast_min_bitrate_bps;
  std::optional<bool> allow_probe_without_media;
};

struct PacingConfig {
  std::optional<bool> screenshare_alr_probing;
  std::optional<double> factor;
  std::optional<int> max_queue_ms;
};

struct EncoderConfig {
  HardwarePolicy hardware_policy = HardwarePolicy::kPreferHardware;
  std::optional<bool> realtime;
  std::optional<bool> allow_frame_reordering;
  std::optional<std::string> h264_profile;
  std::optional<std::string> h264_level;
  std::optional<int> periodic_idr_seconds;
  std::optional<int> max_h264_slice_bytes;
  std::optional<double> data_rate_limit_factor;
  std::optional<int> data_rate_window_ms;
  std::optional<int> max_frame_delay_count;
  std::optional<int> max_qp;
  std::optional<bool> video_toolbox_low_latency_rate_control;
  std::optional<SpatialAdaptiveQpMode> video_toolbox_spatial_adaptive_qp;
};

struct ReceiverConfig {
  std::optional<int> jitter_minimum_ms;
  std::optional<bool> prerender_smoothing;
  std::optional<int> render_lead_ms;
  std::optional<bool> android_decoder_low_latency;
  std::optional<int> stale_decoded_frame_ms;
};

struct RecoveryConfig {
  std::optional<bool> nack_enabled;
  std::optional<int> nack_history_ms;
  std::optional<bool> rtx_enabled;
  std::optional<FecMode> fec_mode;
  std::optional<int> pli_min_interval_ms;
  std::optional<int> no_decoded_frame_timeout_ms;
  std::optional<int> decoder_recreate_after_failed_pli;
  std::optional<int> sender_reset_after_failed_pli;
};

struct TelemetryConfig {
  std::optional<int> sample_interval_ms;
  std::optional<std::string> jsonl_path;
  std::optional<bool> rtc_event_log;
};

struct ExperimentalConfig {
  bool allow_raw_field_trials = false;
  std::map<std::string, std::string> raw_field_trials;
};

struct CastTuningConfig {
  int schema_version = kTuningSchemaVersion;
  Profile profile = Profile::kUpstream;
  bool enabled = false;
  SenderConfig sender;
  TransportConfig transport;
  PacingConfig pacing;
  EncoderConfig encoder;
  ReceiverConfig receiver;
  RecoveryConfig recovery;
  TelemetryConfig telemetry;
  ExperimentalConfig experimental;

  static CastTuningConfig ForProfile(
      Profile profile,
      int schema_version = kTuningSchemaVersion);
  static std::optional<CastTuningConfig> ParseJson(const std::string& json,
                                                   std::string* error);
  static std::optional<CastTuningConfig> ParseJsonWithOverrides(
      const std::string& json,
      const std::string& profile_override,
      const std::string& overrides_json,
      std::string* error);
  bool IsUpstream() const;
  ValidationResult Validate() const;
  std::string FieldTrialString() const;
};

struct CastTuningLivePatch {
  std::optional<int> max_width;
  std::optional<int> max_height;
  std::optional<int> max_fps;
  std::optional<ContentMode> content_mode;
  std::optional<int> min_bitrate_bps;
  std::optional<int> start_bitrate_bps;
  std::optional<int> max_bitrate_bps;
  std::optional<DegradationPreference> degradation_preference;
  std::optional<int> jitter_minimum_ms;
  std::optional<int> stale_decoded_frame_ms;
  std::optional<int> max_qp;
  std::optional<double> pacing_factor;
  std::optional<int> periodic_idr_seconds;
  bool reset_bwe_estimate = false;

  ApplyScope RequiredScope() const;
};

const char* ProfileName(Profile profile);

}  // namespace webrtc::cast_tuning

#endif  // API_CAST_TUNING_CAST_TUNING_CONFIG_H_
