#ifndef API_CAST_TUNING_CAST_TUNING_RECOVERY_H_
#define API_CAST_TUNING_CAST_TUNING_RECOVERY_H_

#include <cstdint>

#include "api/cast_tuning/cast_tuning_config.h"

namespace webrtc::cast_tuning {

enum class RecoveryAction {
  kNone,
  kPliRequested,
  kDecoderRecreateRequired,
  kSenderResetAndKeyframeRequired,
};

// Turns a lack of decoded frames into rate-limited recovery instructions. The
// caller owns the actual PLI, decoder recreation, and cross-end signalling.
class CastRecoveryStateMachine {
 public:
  explicit CastRecoveryStateMachine(const RecoveryConfig& config);

  void Start(int64_t now_ms);
  void OnDecodedFrame(int64_t now_ms);
  RecoveryAction Evaluate(int64_t now_ms);

  int failed_recovery_count() const { return failed_recovery_count_; }

 private:
  int no_decoded_frame_timeout_ms_;
  int pli_min_interval_ms_;
  int decoder_recreate_threshold_;
  int sender_reset_threshold_;
  int64_t last_decoded_frame_ms_ = 0;
  int64_t last_recovery_action_ms_ = 0;
  int failed_recovery_count_ = 0;
  bool started_ = false;
};

const char* RecoveryActionName(RecoveryAction action);

}  // namespace webrtc::cast_tuning

#endif  // API_CAST_TUNING_CAST_TUNING_RECOVERY_H_
