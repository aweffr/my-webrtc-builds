#include "api/cast_tuning/cast_tuning_recovery.h"

#include <algorithm>

namespace webrtc::cast_tuning {

CastRecoveryStateMachine::CastRecoveryStateMachine(const RecoveryConfig& config)
    : no_decoded_frame_timeout_ms_(
          config.no_decoded_frame_timeout_ms.value_or(150)),
      pli_min_interval_ms_(config.pli_min_interval_ms.value_or(500)),
      decoder_recreate_threshold_(
          config.decoder_recreate_after_failed_pli.value_or(2)),
      sender_reset_threshold_(
          config.sender_reset_after_failed_pli.value_or(3)) {}

void CastRecoveryStateMachine::Start(int64_t now_ms) {
  last_decoded_frame_ms_ = now_ms;
  last_recovery_action_ms_ = 0;
  failed_recovery_count_ = 0;
  started_ = true;
}

void CastRecoveryStateMachine::OnDecodedFrame(int64_t now_ms) {
  Start(now_ms);
}

RecoveryAction CastRecoveryStateMachine::Evaluate(int64_t now_ms) {
  if (!started_ || now_ms < last_decoded_frame_ms_ ||
      now_ms - last_decoded_frame_ms_ < no_decoded_frame_timeout_ms_) {
    return RecoveryAction::kNone;
  }
  if (last_recovery_action_ms_ != 0 &&
      now_ms - last_recovery_action_ms_ < pli_min_interval_ms_) {
    return RecoveryAction::kNone;
  }

  last_recovery_action_ms_ = now_ms;
  ++failed_recovery_count_;
  if (failed_recovery_count_ >= sender_reset_threshold_) {
    return RecoveryAction::kSenderResetAndKeyframeRequired;
  }
  if (failed_recovery_count_ >= decoder_recreate_threshold_) {
    return RecoveryAction::kDecoderRecreateRequired;
  }
  return RecoveryAction::kPliRequested;
}

const char* RecoveryActionName(RecoveryAction action) {
  switch (action) {
    case RecoveryAction::kNone:
      return "NONE";
    case RecoveryAction::kPliRequested:
      return "PLI_REQUESTED";
    case RecoveryAction::kDecoderRecreateRequired:
      return "DECODER_RECREATE_REQUIRED";
    case RecoveryAction::kSenderResetAndKeyframeRequired:
      return "SENDER_RESET_AND_KEYFRAME_REQUIRED";
  }
  return "UNKNOWN";
}

}  // namespace webrtc::cast_tuning
