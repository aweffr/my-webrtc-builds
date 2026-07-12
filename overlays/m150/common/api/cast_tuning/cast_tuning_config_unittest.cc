#include "api/cast_tuning/cast_tuning_config.h"

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>

#include "api/cast_tuning/cast_tuning_controller.h"
#include "api/cast_tuning/cast_tuning_recovery.h"
#include "api/cast_tuning/cast_tuning_telemetry.h"

namespace {

void Expect(bool condition, const char* message) {
  if (!condition) {
    std::cerr << message << '\n';
    std::exit(1);
  }
}

}  // namespace

class FakeBackend final : public webrtc::cast_tuning::CastTuningBackend {
 public:
  bool fail_sender = false;
  bool fail_rollback = false;
  int bitrate = 6000000;
  int fps = 15;

  webrtc::cast_tuning::BackendState CaptureState() const override {
    return {.max_bitrate_bps = bitrate, .max_fps = fps};
  }

  bool ApplyBitrate(const webrtc::cast_tuning::BackendState& state,
                    std::string* error) override {
    if (fail_rollback && state.max_bitrate_bps == 4000000) {
      *error = "rollback bitrate failed";
      return false;
    }
    bitrate = state.max_bitrate_bps;
    return true;
  }

  bool ApplySender(const webrtc::cast_tuning::BackendState& state,
                   std::string* error) override {
    if (fail_sender) {
      *error = "sender failed";
      return false;
    }
    fps = state.max_fps;
    return true;
  }

  bool ApplyReceiver(const webrtc::cast_tuning::BackendState&,
                     std::string*) override {
    return true;
  }
};

#if defined(CAST_TUNING_WITH_JSON_TESTS)
int RunCastTuningJsonContractTests();
#endif

int main() {
  using webrtc::cast_tuning::ApplyScope;
  using webrtc::cast_tuning::CastTuningConfig;
  using webrtc::cast_tuning::CastTuningLivePatch;
  using webrtc::cast_tuning::FecMode;
  using webrtc::cast_tuning::Profile;

  const CastTuningConfig upstream =
      CastTuningConfig::ForProfile(Profile::kUpstream);
  Expect(upstream.IsUpstream(), "UPSTREAM must not override WebRTC defaults");
  Expect(upstream.FieldTrialString().empty(),
         "UPSTREAM field trials must be empty");

  const CastTuningConfig detail =
      CastTuningConfig::ForProfile(Profile::kDetailIdle);
  Expect(detail.sender.max_width == 1920, "DETAIL_IDLE width");
  Expect(detail.sender.max_height == 1080, "DETAIL_IDLE height");
  Expect(detail.sender.max_fps == 15, "DETAIL_IDLE fps");
  Expect(detail.sender.start_bitrate_bps == 2500000,
         "DETAIL_IDLE start bitrate");
  Expect(detail.sender.max_bitrate_bps == 6000000, "DETAIL_IDLE max bitrate");
  Expect(detail.Validate().ok(), "DETAIL_IDLE must validate");

  CastTuningConfig invalid = detail;
  invalid.sender.min_bitrate_bps = 7000000;
  Expect(!invalid.Validate().ok(), "min bitrate above max must fail");
  invalid = detail;
  invalid.encoder.periodic_idr_seconds = 1;
  Expect(!invalid.Validate().ok(), "sub-10-second IDR must fail");
  invalid = detail;
  invalid.encoder.h264_profile = "MAIN";
  Expect(!invalid.Validate().ok(), "unsupported H264 profile must fail");
  invalid = detail;
  invalid.encoder.h264_level = "9.9";
  Expect(!invalid.Validate().ok(), "unsupported H264 level must fail");
  invalid = detail;
  invalid.recovery.nack_enabled = false;
  invalid.recovery.rtx_enabled = true;
  Expect(!invalid.Validate().ok(), "RTX without NACK must fail");
  invalid = detail;
  invalid.recovery.fec_mode = static_cast<FecMode>(99);
  Expect(!invalid.Validate().ok(), "unknown FEC mode must fail");
  invalid = detail;
  invalid.recovery.decoder_recreate_after_failed_pli = 4;
  invalid.recovery.sender_reset_after_failed_pli = 3;
  Expect(!invalid.Validate().ok(),
         "sender reset threshold must not precede decoder recreation");

  CastTuningConfig transport = detail;
  transport.pacing.screenshare_alr_probing = true;
  transport.pacing.factor = 1.3;
  transport.pacing.max_queue_ms = 100;
  const std::string trials = transport.FieldTrialString();
  Expect(trials.find("WebRTC-ProbingScreenshareBwe/") != std::string::npos,
         "ALR field trial missing");
  Expect(trials.find("WebRTC-Video-Pacing/factor:1.3,max_delay:100ms/") !=
             std::string::npos,
         "pacing field trial missing");

  CastTuningLivePatch live;
  live.max_bitrate_bps = 4000000;
  Expect(live.RequiredScope() == ApplyScope::kLive,
         "max bitrate should be LIVE");
  live.start_bitrate_bps = 2000000;
  Expect(live.RequiredScope() == ApplyScope::kSession,
         "start bitrate should require SESSION");

  FakeBackend backend;
  webrtc::cast_tuning::CastTuningController controller(detail, &backend);
  Expect(!controller.snapshot().session_id.empty(),
         "controller must allocate a session id");
  CastTuningConfig fluid_config = detail;
  fluid_config.sender.content_mode = webrtc::cast_tuning::ContentMode::kFluid;
  FakeBackend fluid_backend;
  webrtc::cast_tuning::CastTuningController fluid_controller(fluid_config,
                                                             &fluid_backend);
  Expect(controller.snapshot().effective_config_hash !=
             fluid_controller.snapshot().effective_config_hash,
         "effective hash must cover every tuning value");
  CastTuningLivePatch successful_patch;
  successful_patch.max_bitrate_bps = 4000000;
  successful_patch.max_fps = 20;
  const auto applied = controller.ApplyLivePatch(successful_patch);
  Expect(applied.status == webrtc::cast_tuning::ApplyStatus::kApplied,
         "valid LIVE patch should apply");
  Expect(backend.bitrate == 4000000 && backend.fps == 20,
         "backend should receive LIVE values");
  Expect(controller.snapshot().revision == 1,
         "successful patch increments revision");

  backend.fail_sender = true;
  CastTuningLivePatch failing_patch;
  failing_patch.max_bitrate_bps = 3000000;
  failing_patch.max_fps = 30;
  const auto rejected = controller.ApplyLivePatch(failing_patch);
  Expect(rejected.status == webrtc::cast_tuning::ApplyStatus::kRejected,
         "failed sender update should reject patch");
  Expect(backend.bitrate == 4000000 && backend.fps == 20,
         "failed patch must roll back backend state");
  Expect(controller.snapshot().revision == 1,
         "failed patch must not increment revision");

  backend.fail_rollback = true;
  const auto degraded = controller.ApplyLivePatch(failing_patch);
  Expect(degraded.status ==
             webrtc::cast_tuning::ApplyStatus::kSessionRecreateRequired,
         "rollback failure should require session recreation");

  using webrtc::cast_tuning::CastRecoveryStateMachine;
  using webrtc::cast_tuning::RecoveryAction;
  using webrtc::cast_tuning::RecoveryConfig;
  RecoveryConfig recovery_config;
  recovery_config.no_decoded_frame_timeout_ms = 150;
  recovery_config.pli_min_interval_ms = 500;
  recovery_config.decoder_recreate_after_failed_pli = 2;
  recovery_config.sender_reset_after_failed_pli = 3;
  CastRecoveryStateMachine recovery(recovery_config);
  recovery.Start(1000);
  Expect(recovery.Evaluate(1149) == RecoveryAction::kNone,
         "recovery must wait for the no-frame timeout");
  Expect(recovery.Evaluate(1150) == RecoveryAction::kPliRequested,
         "first recovery action should request PLI");
  Expect(recovery.Evaluate(1649) == RecoveryAction::kNone,
         "PLI requests must be rate limited");
  Expect(recovery.Evaluate(1650) == RecoveryAction::kDecoderRecreateRequired,
         "second failed PLI should recreate the decoder");
  Expect(recovery.Evaluate(2150) ==
             RecoveryAction::kSenderResetAndKeyframeRequired,
         "third failed PLI should escalate to sender reset");
  recovery.OnDecodedFrame(2200);
  Expect(recovery.failed_recovery_count() == 0,
         "a decoded frame must reset recovery escalation");
  Expect(recovery.Evaluate(2349) == RecoveryAction::kNone,
         "decoded frame resets the no-frame timeout");

  const std::string telemetry_path =
      "/tmp/cast_tuning_telemetry_contract.jsonl";
  std::string telemetry_line;
  std::remove(telemetry_path.c_str());

  const std::string controller_telemetry_path =
      "/tmp/cast_tuning_controller_telemetry_contract.jsonl";
  std::remove(controller_telemetry_path.c_str());
  {
    CastTuningConfig observed = detail;
    observed.telemetry.jsonl_path = controller_telemetry_path;
    FakeBackend observed_backend;
    webrtc::cast_tuning::CastTuningController observed_controller(
        observed, &observed_backend);
    CastTuningLivePatch observed_patch;
    observed_patch.max_fps = 18;
    Expect(observed_controller.ApplyLivePatch(observed_patch).status ==
               webrtc::cast_tuning::ApplyStatus::kApplied,
           "observed patch should apply");
  }
  std::ifstream controller_telemetry_file(controller_telemetry_path);
  int config_applied_events = 0;
  while (std::getline(controller_telemetry_file, telemetry_line)) {
    if (telemetry_line.find("\"event_type\":\"config_applied\"") !=
        std::string::npos) {
      ++config_applied_events;
    }
  }
  Expect(config_applied_events == 2,
         "controller must log initial and live config application");
  std::remove(controller_telemetry_path.c_str());
  {
    webrtc::cast_tuning::CastTelemetryWriter writer(telemetry_path);
    writer.Emit({.event_type = "config_applied",
                 .timestamp_ms = 1000,
                 .session_id = controller.snapshot().session_id,
                 .config_hash = controller.snapshot().effective_config_hash,
                 .revision = controller.snapshot().revision,
                 .payload_json = "{\"profile\":\"DETAIL_IDLE\"}"});
    writer.Emit({.event_type = "telemetry_sample",
                 .timestamp_ms = 2000,
                 .session_id = controller.snapshot().session_id,
                 .config_hash = controller.snapshot().effective_config_hash,
                 .revision = controller.snapshot().revision,
                 .payload_json =
                     "{\"decode_ms\":null,\"decode_ms_unavailable_reason\":"
                     "\"receiver_not_attached\"}"});
    writer.Flush();
    Expect(writer.write_failures() == 0, "telemetry writer should flush JSONL");
  }
  std::ifstream telemetry_file(telemetry_path);
  int telemetry_lines = 0;
  while (std::getline(telemetry_file, telemetry_line)) {
    ++telemetry_lines;
    Expect(telemetry_line.find("\"schema_version\":1") != std::string::npos,
           "telemetry must include schema version");
    Expect(telemetry_line.find("\"session_id\":") != std::string::npos,
           "telemetry must include session id");
  }
  Expect(telemetry_lines == 2, "telemetry writer must preserve event ordering");
  std::remove(telemetry_path.c_str());

#if defined(CAST_TUNING_WITH_JSON_TESTS)
  RunCastTuningJsonContractTests();
#endif

  std::cout << "CastTuning config tests passed\n";
  return 0;
}
