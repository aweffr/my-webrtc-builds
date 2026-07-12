#include "api/cast_tuning/webrtc_cast_tuning_backend.h"

#include <optional>
#include <utility>
#include <vector>

#include "api/rtp_parameters.h"
#include "api/transport/bitrate_settings.h"
#include "rtc_base/logging.h"

namespace webrtc::cast_tuning {
namespace {

std::optional<webrtc::DegradationPreference> ToWebRtcDegradation(
    DegradationPreference preference) {
  switch (preference) {
    case DegradationPreference::kMaintainResolution:
      return webrtc::DegradationPreference::MAINTAIN_RESOLUTION;
    case DegradationPreference::kMaintainFramerate:
      return webrtc::DegradationPreference::MAINTAIN_FRAMERATE;
    case DegradationPreference::kUnspecified:
      return std::nullopt;
  }
  return std::nullopt;
}

Priority ToWebRtcPriority(NetworkPriority priority) {
  switch (priority) {
    case NetworkPriority::kLow:
      return Priority::kLow;
    case NetworkPriority::kMedium:
      return Priority::kMedium;
    case NetworkPriority::kHigh:
      return Priority::kHigh;
    case NetworkPriority::kUnspecified:
      return Priority::kLow;
  }
  return Priority::kLow;
}

VideoTrackInterface::ContentHint ToContentHint(ContentMode mode) {
  switch (mode) {
    case ContentMode::kText:
      return VideoTrackInterface::ContentHint::kText;
    case ContentMode::kFluid:
      return VideoTrackInterface::ContentHint::kFluid;
    case ContentMode::kUnspecified:
      return VideoTrackInterface::ContentHint::kNone;
  }
  return VideoTrackInterface::ContentHint::kNone;
}

}  // namespace

WebRtcCastTuningBackend::WebRtcCastTuningBackend(const CastTuningConfig& config)
    : has_initial_bitrate_config_(config.sender.min_bitrate_bps ||
                                  config.sender.start_bitrate_bps ||
                                  config.sender.max_bitrate_bps),
      has_initial_sender_config_(
          has_initial_bitrate_config_ || config.sender.max_width ||
          config.sender.max_height || config.sender.max_fps ||
          config.sender.content_mode || config.sender.degradation_preference ||
          config.sender.network_priority),
      has_initial_receiver_config_(config.receiver.jitter_minimum_ms) {
  state_.min_bitrate_bps = config.sender.min_bitrate_bps.value_or(0);
  state_.start_bitrate_bps = config.sender.start_bitrate_bps.value_or(0);
  state_.max_bitrate_bps = config.sender.max_bitrate_bps.value_or(0);
  state_.max_width = config.sender.max_width.value_or(0);
  state_.max_height = config.sender.max_height.value_or(0);
  state_.max_fps = config.sender.max_fps.value_or(0);
  state_.content_mode =
      config.sender.content_mode.value_or(ContentMode::kUnspecified);
  state_.degradation_preference = config.sender.degradation_preference.value_or(
      DegradationPreference::kUnspecified);
  state_.network_priority =
      config.sender.network_priority.value_or(NetworkPriority::kUnspecified);
  state_.jitter_minimum_ms = config.receiver.jitter_minimum_ms.value_or(0);
  state_.stale_decoded_frame_ms =
      config.receiver.stale_decoded_frame_ms.value_or(0);
}

void WebRtcCastTuningBackend::AttachPeerConnection(
    scoped_refptr<PeerConnectionInterface> peer_connection) {
  peer_connection_ = std::move(peer_connection);
  if (has_initial_bitrate_config_) {
    std::string error;
    const bool success = ApplyBitrate(state_, &error);
    RecordInitialApplyResult(success, "bitrate", error);
  }
}

void WebRtcCastTuningBackend::AttachSender(
    scoped_refptr<RtpSenderInterface> sender,
    scoped_refptr<VideoTrackInterface> track,
    CastVideoSourceAdapter* source_adapter) {
  sender_ = std::move(sender);
  track_ = std::move(track);
  source_adapter_ = source_adapter;
  if (has_initial_sender_config_) {
    std::string error;
    const bool success = ApplySender(state_, &error);
    RecordInitialApplyResult(success, "sender", error);
  }
}

void WebRtcCastTuningBackend::AttachReceiver(
    scoped_refptr<RtpReceiverInterface> receiver) {
  receiver_ = std::move(receiver);
  if (has_initial_receiver_config_) {
    std::string error;
    const bool success = ApplyReceiver(state_, &error);
    RecordInitialApplyResult(success, "receiver", error);
  }
}

void WebRtcCastTuningBackend::RecordInitialApplyResult(
    bool success,
    const char* component,
    const std::string& error) {
  if (success)
    return;
  last_initial_apply_error_ = std::string(component) + ": " + error;
  RTC_LOG(LS_WARNING) << "CastTuning initial apply failed for " << component
                      << ": " << error;
}

BackendState WebRtcCastTuningBackend::CaptureState() const {
  return state_;
}

bool WebRtcCastTuningBackend::ApplyBitrate(const BackendState& state,
                                           std::string* error) {
  if (!peer_connection_) {
    if (state.min_bitrate_bps == state_.min_bitrate_bps &&
        state.max_bitrate_bps == state_.max_bitrate_bps) {
      return true;
    }
    *error = "PeerConnection is not attached";
    return false;
  }
  BitrateSettings bitrate;
  if (state.min_bitrate_bps > 0)
    bitrate.min_bitrate_bps = state.min_bitrate_bps;
  if (state.start_bitrate_bps > 0)
    bitrate.start_bitrate_bps = state.start_bitrate_bps;
  if (state.max_bitrate_bps > 0)
    bitrate.max_bitrate_bps = state.max_bitrate_bps;
  RTCError result = peer_connection_->SetBitrate(bitrate);
  if (!result.ok()) {
    *error = std::string(result.message());
    return false;
  }
  state_.min_bitrate_bps = state.min_bitrate_bps;
  // start_bitrate_bps seeds a new estimate once; live min/max changes must not
  // reset an established bandwidth estimate.
  state_.start_bitrate_bps = 0;
  state_.max_bitrate_bps = state.max_bitrate_bps;
  return true;
}

bool WebRtcCastTuningBackend::ApplySender(const BackendState& state,
                                          std::string* error) {
  if (!sender_) {
    if (state.max_fps == state_.max_fps &&
        state.max_width == state_.max_width &&
        state.max_height == state_.max_height &&
        state.content_mode == state_.content_mode &&
        state.degradation_preference == state_.degradation_preference) {
      return true;
    }
    *error = "RtpSender is not attached";
    return false;
  }
  RtpParameters parameters = sender_->GetParameters();
  if (parameters.encodings.empty()) {
    *error = "RtpSender has no encoding parameters";
    return false;
  }
  RtpEncodingParameters& encoding = parameters.encodings.front();
  if (state.min_bitrate_bps > 0)
    encoding.min_bitrate_bps = state.min_bitrate_bps;
  if (state.max_bitrate_bps > 0)
    encoding.max_bitrate_bps = state.max_bitrate_bps;
  if (state.max_fps > 0)
    encoding.max_framerate = state.max_fps;
  if (state.network_priority != NetworkPriority::kUnspecified)
    encoding.network_priority = ToWebRtcPriority(state.network_priority);
  if (state.degradation_preference != DegradationPreference::kUnspecified) {
    parameters.degradation_preference =
        ToWebRtcDegradation(state.degradation_preference);
  }
  RTCError result = sender_->SetParameters(parameters);
  if (!result.ok()) {
    *error = std::string(result.message());
    return false;
  }
  if (track_ && state.content_mode != ContentMode::kUnspecified)
    track_->set_content_hint(ToContentHint(state.content_mode));
  if (source_adapter_ &&
      (state.max_width > 0 || state.max_height > 0 || state.max_fps > 0) &&
      !source_adapter_->AdaptOutput(state.max_width, state.max_height,
                                    state.max_fps, error)) {
    return false;
  }
  state_ = state;
  return true;
}

bool WebRtcCastTuningBackend::ApplyReceiver(const BackendState& state,
                                            std::string* error) {
  if (!receiver_) {
    if (state.jitter_minimum_ms == state_.jitter_minimum_ms) {
      state_.stale_decoded_frame_ms = state.stale_decoded_frame_ms;
      return true;
    }
    *error = "RtpReceiver is not attached";
    return false;
  }
  receiver_->SetJitterBufferMinimumDelay(state.jitter_minimum_ms / 1000.0);
  state_.jitter_minimum_ms = state.jitter_minimum_ms;
  state_.stale_decoded_frame_ms = state.stale_decoded_frame_ms;
  return true;
}

RTCError WebRtcCastTuningBackend::ForceKeyFrame() {
  if (!sender_)
    return RTCError(RTCErrorType::INVALID_STATE, "RtpSender is not attached");
  return sender_->GenerateKeyFrame({});
}

}  // namespace webrtc::cast_tuning
