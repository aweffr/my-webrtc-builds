#include <jni.h>

#include <memory>
#include <optional>
#include <string>

#include "api/cast_tuning/cast_tuning_config.h"
#include "api/cast_tuning/cast_tuning_controller.h"
#include "sdk/android/generated_peerconnection_jni/CastTuningController_jni.h"
#include "sdk/android/native_api/jni/java_types.h"
#include "sdk/android/native_api/jni/scoped_java_ref.h"
#include "sdk/android/src/jni/jni_helpers.h"

namespace webrtc::jni {
namespace {

class ConfigOnlyBackend final : public cast_tuning::CastTuningBackend {
 public:
  explicit ConfigOnlyBackend(const cast_tuning::CastTuningConfig& config) {
    state_.min_bitrate_bps = config.sender.min_bitrate_bps.value_or(0);
    state_.start_bitrate_bps = config.sender.start_bitrate_bps.value_or(0);
    state_.max_bitrate_bps = config.sender.max_bitrate_bps.value_or(0);
    state_.max_width = config.sender.max_width.value_or(0);
    state_.max_height = config.sender.max_height.value_or(0);
    state_.max_fps = config.sender.max_fps.value_or(0);
    state_.jitter_minimum_ms = config.receiver.jitter_minimum_ms.value_or(0);
  }

  cast_tuning::BackendState CaptureState() const override { return state_; }
  bool ApplyBitrate(const cast_tuning::BackendState& state,
                    std::string*) override {
    state_ = state;
    return true;
  }
  bool ApplySender(const cast_tuning::BackendState& state,
                   std::string*) override {
    state_ = state;
    return true;
  }
  bool ApplyReceiver(const cast_tuning::BackendState& state,
                     std::string*) override {
    state_ = state;
    return true;
  }

 private:
  cast_tuning::BackendState state_;
};

struct AndroidCastTuningState {
  explicit AndroidCastTuningState(cast_tuning::CastTuningConfig value)
      : config(std::move(value)),
        field_trials(config.FieldTrialString()),
        backend(config),
        controller(config, &backend) {}

  cast_tuning::CastTuningConfig config;
  std::string field_trials;
  ConfigOnlyBackend backend;
  cast_tuning::CastTuningController controller;
};

AndroidCastTuningState* State(jlong pointer) {
  return reinterpret_cast<AndroidCastTuningState*>(pointer);
}

int OptionalBool(const std::optional<bool>& value) {
  return value ? (*value ? 1 : 0) : -1;
}

}  // namespace

static jlong JNI_CastTuningController_Create(
    JNIEnv* env,
    const jni_zero::JavaRef<jstring>& base_json,
    const jni_zero::JavaRef<jstring>& profile_override,
    const jni_zero::JavaRef<jstring>& overrides_json) {
  std::string error;
  std::optional<cast_tuning::CastTuningConfig> config =
      cast_tuning::CastTuningConfig::ParseJsonWithOverrides(
          JavaToNativeString(env, base_json),
          profile_override.is_null() ? std::string()
                                     : JavaToNativeString(env, profile_override),
          overrides_json.is_null() ? std::string()
                                   : JavaToNativeString(env, overrides_json),
          &error);
  if (!config)
    return 0;
  return jlongFromPointer(new AndroidCastTuningState(std::move(*config)));
}

static jni_zero::ScopedJavaLocalRef<jstring>
JNI_CastTuningController_GetFieldTrials(JNIEnv* env, jlong pointer) {
  return NativeToJavaString(env, State(pointer)->field_trials);
}

static jint JNI_CastTuningController_GetPrerendererSmoothing(JNIEnv*,
                                                              jlong pointer) {
  return OptionalBool(State(pointer)->config.receiver.prerender_smoothing);
}

static jint JNI_CastTuningController_GetRelayOnly(JNIEnv*, jlong pointer) {
  return OptionalBool(State(pointer)->config.transport.relay_only);
}

static jint JNI_CastTuningController_GetDisableTcpCandidates(JNIEnv*,
                                                              jlong pointer) {
  return OptionalBool(State(pointer)->config.transport.disable_tcp_candidates);
}

static jint JNI_CastTuningController_GetScreencastMinBitrateBps(JNIEnv*,
                                                                jlong pointer) {
  return State(pointer)
      ->config.transport.screencast_min_bitrate_bps.value_or(-1);
}

static jint JNI_CastTuningController_GetRenderLeadMs(JNIEnv*, jlong pointer) {
  return State(pointer)->config.receiver.render_lead_ms.value_or(-1);
}

static jint JNI_CastTuningController_GetJitterMinimumMs(JNIEnv*,
                                                         jlong pointer) {
  return State(pointer)->config.receiver.jitter_minimum_ms.value_or(-1);
}

static jboolean JNI_CastTuningController_GetAndroidDecoderLowLatency(
    JNIEnv*,
    jlong pointer) {
  return State(pointer)
      ->config.receiver.android_decoder_low_latency.value_or(false);
}

static jni_zero::ScopedJavaLocalRef<jstring>
JNI_CastTuningController_GetSessionId(JNIEnv* env, jlong pointer) {
  return NativeToJavaString(env, State(pointer)->controller.snapshot().session_id);
}

static jni_zero::ScopedJavaLocalRef<jstring>
JNI_CastTuningController_GetEffectiveConfigHash(JNIEnv* env, jlong pointer) {
  return NativeToJavaString(
      env, State(pointer)->controller.snapshot().effective_config_hash);
}

static jlong JNI_CastTuningController_GetRevision(JNIEnv*, jlong pointer) {
  return State(pointer)->controller.snapshot().revision;
}

static jboolean JNI_CastTuningController_GetRecreateRequired(JNIEnv*,
                                                              jlong pointer) {
  return State(pointer)->controller.snapshot().recreate_required;
}

static void JNI_CastTuningController_Free(JNIEnv*, jlong pointer) {
  delete State(pointer);
}

}  // namespace webrtc::jni
