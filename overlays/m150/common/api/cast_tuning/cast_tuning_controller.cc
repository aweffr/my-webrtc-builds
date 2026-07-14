#include "api/cast_tuning/cast_tuning_controller.h"

#include <atomic>
#include <chrono>
#include <iomanip>
#include <sstream>
#include <utility>

#include "api/cast_tuning/cast_tuning_telemetry.h"

namespace webrtc::cast_tuning {
namespace {

template <typename T>
void AppendOptional(std::ostringstream& output, const std::optional<T>& value) {
  if (value) {
    output << '1' << ':' << *value;
  } else {
    output << '0';
  }
  output << '|';
}

template <typename Enum>
void AppendEnum(std::ostringstream& output, Enum value) {
  output << static_cast<int>(value) << '|';
}

template <typename Enum>
void AppendOptionalEnum(std::ostringstream& output,
                        const std::optional<Enum>& value) {
  if (value) {
    output << '1' << ':' << static_cast<int>(*value);
  } else {
    output << '0';
  }
  output << '|';
}

std::string NewSessionId() {
  static std::atomic<uint64_t> sequence{0};
  const uint64_t timestamp = static_cast<uint64_t>(
      std::chrono::steady_clock::now().time_since_epoch().count());
  std::ostringstream value;
  value << "cast-" << std::hex << timestamp << '-'
        << sequence.fetch_add(1, std::memory_order_relaxed);
  return value.str();
}

int64_t NowMilliseconds() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

std::string ConfigFingerprint(const CastTuningConfig& config) {
  std::ostringstream canonical;
  canonical << config.schema_version << '|' << config.enabled << '|';
  AppendEnum(canonical, config.profile);
  AppendOptional(canonical, config.sender.max_width);
  AppendOptional(canonical, config.sender.max_height);
  AppendOptional(canonical, config.sender.min_fps);
  AppendOptional(canonical, config.sender.max_fps);
  AppendOptional(canonical, config.sender.latest_frame_only);
  AppendOptionalEnum(canonical, config.sender.content_mode);
  AppendOptional(canonical, config.sender.min_bitrate_bps);
  AppendOptional(canonical, config.sender.start_bitrate_bps);
  AppendOptional(canonical, config.sender.max_bitrate_bps);
  AppendOptionalEnum(canonical, config.sender.degradation_preference);
  AppendOptionalEnum(canonical, config.sender.network_priority);
  AppendOptional(canonical, config.transport.relay_only);
  AppendOptional(canonical, config.transport.disable_tcp_candidates);
  AppendOptional(canonical, config.transport.screencast_min_bitrate_bps);
  AppendOptional(canonical, config.transport.allow_probe_without_media);
  AppendOptional(canonical, config.pacing.screenshare_alr_probing);
  AppendOptional(canonical, config.pacing.factor);
  AppendOptional(canonical, config.pacing.max_queue_ms);
  AppendEnum(canonical, config.encoder.hardware_policy);
  AppendOptional(canonical, config.encoder.realtime);
  AppendOptional(canonical, config.encoder.allow_frame_reordering);
  AppendOptional(canonical, config.encoder.h264_profile);
  AppendOptional(canonical, config.encoder.h264_level);
  AppendOptional(canonical, config.encoder.periodic_idr_seconds);
  AppendOptional(canonical, config.encoder.max_h264_slice_bytes);
  AppendOptional(canonical, config.encoder.data_rate_limit_factor);
  AppendOptional(canonical, config.encoder.data_rate_window_ms);
  AppendOptional(canonical, config.encoder.max_frame_delay_count);
  AppendOptional(canonical, config.encoder.max_qp);
  AppendOptional(canonical,
                 config.encoder.video_toolbox_low_latency_rate_control);
  AppendOptional(canonical, config.receiver.jitter_minimum_ms);
  AppendOptional(canonical, config.receiver.prerender_smoothing);
  AppendOptional(canonical, config.receiver.render_lead_ms);
  AppendOptional(canonical, config.receiver.android_decoder_low_latency);
  AppendOptional(canonical, config.receiver.stale_decoded_frame_ms);
  AppendOptional(canonical, config.recovery.nack_enabled);
  AppendOptional(canonical, config.recovery.nack_history_ms);
  AppendOptional(canonical, config.recovery.rtx_enabled);
  AppendOptionalEnum(canonical, config.recovery.fec_mode);
  AppendOptional(canonical, config.recovery.pli_min_interval_ms);
  AppendOptional(canonical, config.recovery.no_decoded_frame_timeout_ms);
  AppendOptional(canonical, config.recovery.decoder_recreate_after_failed_pli);
  AppendOptional(canonical, config.recovery.sender_reset_after_failed_pli);
  AppendOptional(canonical, config.telemetry.sample_interval_ms);
  AppendOptional(canonical, config.telemetry.jsonl_path);
  AppendOptional(canonical, config.telemetry.rtc_event_log);
  canonical << config.experimental.allow_raw_field_trials << '|';
  for (const auto& [name, value] : config.experimental.raw_field_trials) {
    canonical << name.size() << ':' << name << value.size() << ':' << value
              << '|';
  }
  uint64_t hash = 1469598103934665603ULL;
  for (unsigned char byte : canonical.str()) {
    hash ^= byte;
    hash *= 1099511628211ULL;
  }
  std::ostringstream rendered;
  rendered << std::hex << std::setfill('0') << std::setw(16) << hash;
  return rendered.str();
}

BackendState MergeState(const BackendState& current,
                        const CastTuningLivePatch& patch) {
  BackendState result = current;
  if (patch.min_bitrate_bps)
    result.min_bitrate_bps = *patch.min_bitrate_bps;
  if (patch.max_bitrate_bps)
    result.max_bitrate_bps = *patch.max_bitrate_bps;
  if (patch.max_width)
    result.max_width = *patch.max_width;
  if (patch.max_height)
    result.max_height = *patch.max_height;
  if (patch.max_fps)
    result.max_fps = *patch.max_fps;
  if (patch.content_mode)
    result.content_mode = *patch.content_mode;
  if (patch.degradation_preference)
    result.degradation_preference = *patch.degradation_preference;
  if (patch.jitter_minimum_ms)
    result.jitter_minimum_ms = *patch.jitter_minimum_ms;
  if (patch.stale_decoded_frame_ms)
    result.stale_decoded_frame_ms = *patch.stale_decoded_frame_ms;
  return result;
}

void MergeConfig(CastTuningConfig* config, const CastTuningLivePatch& patch) {
  config->enabled = true;
  if (patch.min_bitrate_bps)
    config->sender.min_bitrate_bps = patch.min_bitrate_bps;
  if (patch.max_bitrate_bps)
    config->sender.max_bitrate_bps = patch.max_bitrate_bps;
  if (patch.max_width)
    config->sender.max_width = patch.max_width;
  if (patch.max_height)
    config->sender.max_height = patch.max_height;
  if (patch.max_fps)
    config->sender.max_fps = patch.max_fps;
  if (patch.content_mode)
    config->sender.content_mode = patch.content_mode;
  if (patch.degradation_preference)
    config->sender.degradation_preference = patch.degradation_preference;
  if (patch.jitter_minimum_ms)
    config->receiver.jitter_minimum_ms = patch.jitter_minimum_ms;
  if (patch.stale_decoded_frame_ms)
    config->receiver.stale_decoded_frame_ms = patch.stale_decoded_frame_ms;
}

}  // namespace

CastTuningController::CastTuningController(CastTuningConfig config,
                                           CastTuningBackend* backend,
                                           std::shared_ptr<CastTelemetryWriter>
                                               telemetry_writer)
    : config_(std::move(config)),
      backend_(backend),
      shared_telemetry_writer_(std::move(telemetry_writer)) {
  snapshot_.session_id = NewSessionId();
  snapshot_.profile = config_.profile;
  snapshot_.effective_config_hash = ConfigFingerprint(config_);
  if (shared_telemetry_writer_) {
    EmitConfigEvent("config_applied", "initial");
  } else if (config_.telemetry.jsonl_path && !config_.telemetry.jsonl_path->empty()) {
    telemetry_writer_ =
        std::make_unique<CastTelemetryWriter>(*config_.telemetry.jsonl_path);
    EmitConfigEvent("config_applied", "initial");
  }
}

CastTuningController::~CastTuningController() = default;

void CastTuningController::EmitConfigEvent(const char* event_type,
                                           const std::string& detail) {
  CastTelemetryWriter* writer = shared_telemetry_writer_
                                    ? shared_telemetry_writer_.get()
                                    : telemetry_writer_.get();
  if (!writer)
    return;
  std::ostringstream payload;
  payload << "{\"profile\":\"" << ProfileName(snapshot_.profile)
          << "\",\"detail\":\"" << detail << "\"}";
  writer->Emit({.event_type = event_type,
                .timestamp_ms = NowMilliseconds(),
                .session_id = snapshot_.session_id,
                .config_hash = snapshot_.effective_config_hash,
                .revision = snapshot_.revision,
                .payload_json = payload.str()});
}

CastApplyResult CastTuningController::Reject(ApplyScope scope,
                                             std::string error) {
  CastApplyResult result;
  result.status = ApplyStatus::kRejected;
  result.required_scope = scope;
  result.effective_config_hash = snapshot_.effective_config_hash;
  result.error = std::move(error);
  EmitConfigEvent("config_rejected", "validation_or_backend_error");
  if (observer_)
    observer_->OnConfigRejected(result);
  return result;
}

bool CastTuningController::RollBackBitrate(const BackendState& old_state,
                                           CastApplyResult* result) {
  std::string rollback_error;
  if (backend_->ApplyBitrate(old_state, &rollback_error))
    return true;
  result->status = ApplyStatus::kSessionRecreateRequired;
  result->required_scope = ApplyScope::kSession;
  result->warnings.push_back(std::move(rollback_error));
  snapshot_.recreate_required = true;
  return false;
}

bool CastTuningController::RollBackSenderAndBitrate(
    const BackendState& old_state,
    CastApplyResult* result) {
  std::string rollback_error;
  bool success = true;
  if (!backend_->ApplySender(old_state, &rollback_error)) {
    result->warnings.push_back(rollback_error);
    success = false;
  }
  if (!backend_->ApplyBitrate(old_state, &rollback_error)) {
    result->warnings.push_back(rollback_error);
    success = false;
  }
  if (!success) {
    result->status = ApplyStatus::kSessionRecreateRequired;
    result->required_scope = ApplyScope::kSession;
    snapshot_.recreate_required = true;
  }
  return success;
}

CastApplyResult CastTuningController::ApplyLivePatch(
    const CastTuningLivePatch& patch) {
  const ApplyScope scope = patch.RequiredScope();
  if (scope != ApplyScope::kLive) {
    return Reject(scope, "patch contains values that cannot be changed live");
  }
  CastTuningConfig candidate = config_;
  MergeConfig(&candidate, patch);
  const ValidationResult validation = candidate.Validate();
  if (!validation.ok())
    return Reject(ApplyScope::kLive, validation.error);

  const BackendState old_state = backend_->CaptureState();
  const BackendState new_state = MergeState(old_state, patch);
  CastApplyResult result;
  result.status = ApplyStatus::kRejected;
  result.required_scope = ApplyScope::kLive;
  result.effective_config_hash = snapshot_.effective_config_hash;
  EmitConfigEvent("config_applied", "live_patch");

  std::string error;
  if (!backend_->ApplyBitrate(new_state, &error)) {
    result.error = std::move(error);
    if (observer_)
      observer_->OnConfigRejected(result);
    return result;
  }
  if (!backend_->ApplySender(new_state, &error)) {
    result.error = std::move(error);
    RollBackBitrate(old_state, &result);
    if (observer_)
      observer_->OnConfigRejected(result);
    return result;
  }
  if (!backend_->ApplyReceiver(new_state, &error)) {
    result.error = std::move(error);
    RollBackSenderAndBitrate(old_state, &result);
    if (observer_)
      observer_->OnConfigRejected(result);
    return result;
  }

  config_ = std::move(candidate);
  snapshot_.effective_config_hash = ConfigFingerprint(config_);
  ++snapshot_.revision;
  result.status = ApplyStatus::kApplied;
  result.effective_config_hash = snapshot_.effective_config_hash;
  if (observer_)
    observer_->OnConfigApplied(snapshot_);
  return result;
}

}  // namespace webrtc::cast_tuning
