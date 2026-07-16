#ifndef API_CAST_TUNING_WEBRTC_CAST_TUNING_BACKEND_H_
#define API_CAST_TUNING_WEBRTC_CAST_TUNING_BACKEND_H_

#include <string>

#include "api/cast_tuning/cast_tuning_controller.h"
#include "api/media_stream_interface.h"
#include "api/peer_connection_interface.h"
#include "api/rtp_receiver_interface.h"
#include "api/rtp_sender_interface.h"
#include "api/scoped_refptr.h"

namespace webrtc::cast_tuning {

class CastVideoSourceAdapter {
 public:
  virtual ~CastVideoSourceAdapter() = default;
  virtual bool AdaptOutput(int width,
                           int height,
                           int max_fps,
                           std::string* error) = 0;
};

class CastEncoderRuntimeAdapter {
 public:
  virtual ~CastEncoderRuntimeAdapter() = default;
  virtual bool ApplyMaxQp(int max_qp, std::string* error) = 0;
};

class WebRtcCastTuningBackend final : public CastTuningBackend {
 public:
  explicit WebRtcCastTuningBackend(
      const CastTuningConfig& config,
      CastEncoderRuntimeAdapter* encoder_runtime_adapter = nullptr);

  void AttachPeerConnection(
      scoped_refptr<PeerConnectionInterface> peer_connection);
  void AttachSender(scoped_refptr<RtpSenderInterface> sender,
                    scoped_refptr<VideoTrackInterface> track,
                    CastVideoSourceAdapter* source_adapter);
  void AttachReceiver(scoped_refptr<RtpReceiverInterface> receiver);

  BackendState CaptureState() const override;
  bool ApplyBitrate(const BackendState& state, std::string* error) override;
  bool ApplySender(const BackendState& state, std::string* error) override;
  bool ApplyEncoder(const BackendState& state, std::string* error) override;
  bool ApplyReceiver(const BackendState& state, std::string* error) override;
  RTCError ForceKeyFrame();

 private:
  void RecordInitialApplyResult(bool success,
                                const char* component,
                                const std::string& error);

  bool has_initial_bitrate_config_ = false;
  bool has_initial_sender_config_ = false;
  bool has_initial_receiver_config_ = false;
  BackendState state_;
  std::string last_initial_apply_error_;
  scoped_refptr<PeerConnectionInterface> peer_connection_;
  scoped_refptr<RtpSenderInterface> sender_;
  scoped_refptr<VideoTrackInterface> track_;
  scoped_refptr<RtpReceiverInterface> receiver_;
  CastVideoSourceAdapter* source_adapter_ = nullptr;
  CastEncoderRuntimeAdapter* encoder_runtime_adapter_ = nullptr;
};

}  // namespace webrtc::cast_tuning

#endif  // API_CAST_TUNING_WEBRTC_CAST_TUNING_BACKEND_H_
