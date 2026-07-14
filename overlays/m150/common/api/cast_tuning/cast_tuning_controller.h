#ifndef API_CAST_TUNING_CAST_TUNING_CONTROLLER_H_
#define API_CAST_TUNING_CAST_TUNING_CONTROLLER_H_

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "api/cast_tuning/cast_tuning_config.h"

namespace webrtc::cast_tuning {

class CastTelemetryWriter;

enum class ApplyStatus {
  kApplied,
  kRejected,
  kUnsupported,
  kSessionRecreateRequired,
};

struct BackendState {
  int min_bitrate_bps = 0;
  int start_bitrate_bps = 0;
  int max_bitrate_bps = 0;
  int max_width = 0;
  int max_height = 0;
  int max_fps = 0;
  ContentMode content_mode = ContentMode::kUnspecified;
  DegradationPreference degradation_preference =
      DegradationPreference::kUnspecified;
  NetworkPriority network_priority = NetworkPriority::kUnspecified;
  int jitter_minimum_ms = 0;
  int stale_decoded_frame_ms = 0;
};

class CastTuningBackend {
 public:
  virtual ~CastTuningBackend() = default;
  virtual BackendState CaptureState() const = 0;
  virtual bool ApplyBitrate(const BackendState& state, std::string* error) = 0;
  virtual bool ApplySender(const BackendState& state, std::string* error) = 0;
  virtual bool ApplyReceiver(const BackendState& state, std::string* error) = 0;
};

struct CastApplyResult {
  ApplyStatus status = ApplyStatus::kRejected;
  ApplyScope required_scope = ApplyScope::kLive;
  std::string effective_config_hash;
  std::string error;
  std::vector<std::string> warnings;
};

struct CastTuningSnapshot {
  std::string session_id;
  std::string effective_config_hash;
  Profile profile = Profile::kUpstream;
  uint64_t revision = 0;
  bool recreate_required = false;
};

class CastTuningObserver {
 public:
  virtual ~CastTuningObserver() = default;
  virtual void OnConfigApplied(const CastTuningSnapshot& snapshot) = 0;
  virtual void OnConfigRejected(const CastApplyResult& result) = 0;
};

class CastTuningController {
 public:
  CastTuningController(
      CastTuningConfig config,
      CastTuningBackend* backend,
      std::shared_ptr<CastTelemetryWriter> telemetry_writer = nullptr,
      bool emit_initial_telemetry = true);
  ~CastTuningController();

  CastApplyResult ApplyLivePatch(const CastTuningLivePatch& patch);
  const CastTuningConfig& config() const { return config_; }
  const CastTuningSnapshot& snapshot() const { return snapshot_; }
  void SetObserver(CastTuningObserver* observer) { observer_ = observer; }

 private:
  CastApplyResult Reject(ApplyScope scope, std::string error);
  bool RollBackBitrate(const BackendState& old_state, CastApplyResult* result);
  bool RollBackSenderAndBitrate(const BackendState& old_state,
                                CastApplyResult* result);
  void EmitConfigEvent(const char* event_type, const std::string& detail);

  CastTuningConfig config_;
  CastTuningBackend* backend_;
  CastTuningObserver* observer_ = nullptr;
  CastTuningSnapshot snapshot_;
  std::unique_ptr<CastTelemetryWriter> telemetry_writer_;
  std::shared_ptr<CastTelemetryWriter> shared_telemetry_writer_;
};

}  // namespace webrtc::cast_tuning

#endif  // API_CAST_TUNING_CAST_TUNING_CONTROLLER_H_
