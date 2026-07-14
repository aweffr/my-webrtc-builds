#import "RTCCastTuning.h"

#include <memory>
#include <optional>
#include <string>

#import "RTCPeerConnection+Private.h"
#import "RTCRtpReceiver+Private.h"
#import "RTCRtpSender+Private.h"
#import "RTCVideoTrack+Private.h"
#import "components/video_codec/RTCVideoEncoderH264.h"

#include "api/cast_tuning/cast_tuning_config.h"
#include "api/cast_tuning/cast_tuning_controller.h"
#include "api/cast_tuning/webrtc_cast_tuning_backend.h"
#include "api/rtc_error.h"

namespace {

NSString *const RTCCastTuningErrorDomain = @"org.webrtc.CastTuning";

NSError *CastError(NSString *message) {
  return [NSError errorWithDomain:RTCCastTuningErrorDomain
                             code:1
                         userInfo:@{NSLocalizedDescriptionKey : message}];
}

}  // namespace

@interface RTCCastTuningEncoderEvidence : NSObject
- (instancetype)initWithTelemetryPath:(nullable NSString *)telemetryPath;
- (void)setConfigHash:(NSString *)configHash;
- (void)recordEvent:(NSDictionary<NSString *, id> *)event;
- (NSDictionary<NSString *, id> *)snapshot;
@end

@implementation RTCCastTuningEncoderEvidence {
  NSLock *_lock;
  NSDictionary<NSString *, id> *_latest;
  BOOL _profileMismatch;
  NSString *_telemetryPath;
  NSString *_sessionId;
  NSString *_configHash;
}

- (instancetype)initWithTelemetryPath:(NSString *)telemetryPath {
  if ((self = [super init])) {
    _lock = [[NSLock alloc] init];
    _latest = @{};
    _telemetryPath = [telemetryPath copy];
    _sessionId = [NSUUID UUID].UUIDString;
    _configHash = @"";
  }
  return self;
}

- (void)setConfigHash:(NSString *)configHash {
  [_lock lock];
  _configHash = [configHash copy];
  [_lock unlock];
}

- (void)recordEvent:(NSDictionary<NSString *, id> *)event {
  [_lock lock];
  _latest = [event copy];
  _profileMismatch =
      _profileMismatch || [event[@"profile_mismatch"] boolValue];
  if (_telemetryPath.length > 0) {
    NSMutableDictionary<NSString *, id> *line = [event mutableCopy];
    line[@"schema_version"] = @1;
    line[@"session_id"] = _sessionId;
    line[@"config_hash"] = _configHash;
    NSData *json = [NSJSONSerialization dataWithJSONObject:line
                                                       options:0
                                                         error:nil];
    if (json) {
      NSMutableData *payload = [json mutableCopy];
      [payload appendData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
      if (![[NSFileManager defaultManager] fileExistsAtPath:_telemetryPath]) {
        [[NSFileManager defaultManager] createFileAtPath:_telemetryPath
                                                contents:nil
                                              attributes:nil];
      }
      NSFileHandle *file = [NSFileHandle fileHandleForWritingAtPath:_telemetryPath];
      [file seekToEndOfFile];
      [file writeData:payload];
      [file closeFile];
    }
  }
  [_lock unlock];
}

- (NSDictionary<NSString *, id> *)snapshot {
  [_lock lock];
  NSMutableDictionary<NSString *, id> *result = [_latest mutableCopy];
  result[@"profile_mismatch"] = @(_profileMismatch);
  [_lock unlock];
  return result;
}

@end

namespace {

NSDictionary<NSString *, id> *EncoderOptions(
    const webrtc::cast_tuning::CastTuningConfig &config) {
  NSMutableDictionary<NSString *, id> *options =
      [NSMutableDictionary dictionary];
  using webrtc::cast_tuning::HardwarePolicy;
  switch (config.encoder.hardware_policy) {
    case HardwarePolicy::kPreferHardware:
      options[@"hardware_policy"] = @"PREFER_HARDWARE";
      break;
    case HardwarePolicy::kRequireHardware:
      options[@"hardware_policy"] = @"REQUIRE_HARDWARE";
      break;
    case HardwarePolicy::kAllowSoftware:
      options[@"hardware_policy"] = @"ALLOW_SOFTWARE";
      break;
  }
#define RTC_CAST_NUMBER_OPTION(field, key)          \
  if (config.encoder.field) {                       \
    options[key] = @(config.encoder.field.value()); \
  }
  RTC_CAST_NUMBER_OPTION(realtime, @"realtime")
  RTC_CAST_NUMBER_OPTION(allow_frame_reordering, @"allow_frame_reordering")
  RTC_CAST_NUMBER_OPTION(periodic_idr_seconds, @"periodic_idr_seconds")
  RTC_CAST_NUMBER_OPTION(max_h264_slice_bytes, @"max_h264_slice_bytes")
  RTC_CAST_NUMBER_OPTION(data_rate_limit_factor, @"data_rate_limit_factor")
  RTC_CAST_NUMBER_OPTION(data_rate_window_ms, @"data_rate_window_ms")
  RTC_CAST_NUMBER_OPTION(max_frame_delay_count, @"max_frame_delay_count")
  RTC_CAST_NUMBER_OPTION(max_qp, @"max_qp")
  RTC_CAST_NUMBER_OPTION(video_toolbox_low_latency_rate_control,
                         @"video_toolbox_low_latency_rate_control")
#undef RTC_CAST_NUMBER_OPTION
  if (config.encoder.h264_profile) {
    options[@"h264_profile"] =
        [NSString stringWithUTF8String:config.encoder.h264_profile->c_str()];
  }
  if (config.encoder.h264_level) {
    options[@"h264_level"] =
        [NSString stringWithUTF8String:config.encoder.h264_level->c_str()];
  }
  return options;
}

class ObjCVideoSourceAdapter final
    : public webrtc::cast_tuning::CastVideoSourceAdapter {
 public:
  explicit ObjCVideoSourceAdapter(RTC_OBJC_TYPE(RTCVideoSource) * source)
      : source_(source) {}

  bool AdaptOutput(int width,
                   int height,
                   int max_fps,
                   std::string *error) override {
    RTC_OBJC_TYPE(RTCVideoSource) *source = source_;
    if (!source) {
      *error = "RTCVideoSource was released";
      return false;
    }
    [source adaptOutputFormatToWidth:width height:height fps:max_fps];
    return true;
  }

 private:
  __weak RTC_OBJC_TYPE(RTCVideoSource) * source_;
};

}  // namespace

@interface RTC_OBJC_TYPE (RTCPeerConnectionFactory)
(RTCCastTuningPrivate) -
    (instancetype)initWithEncoderFactory
    : (nullable id<RTC_OBJC_TYPE(RTCVideoEncoderFactory)>)
          encoderFactory decoderFactory
    : (nullable id<RTC_OBJC_TYPE(RTCVideoDecoderFactory)>)
          decoderFactory audioDevice
    : (nullable id<RTC_OBJC_TYPE(RTCAudioDevice)>)audioDevice fieldTrials
    : (nullable NSString *)fieldTrials;
@end

@interface RTCCastTuningConfiguration () {
  std::optional<webrtc::cast_tuning::CastTuningConfig> _nativeConfig;
  RTCCastTuningEncoderEvidence *_encoderEvidence;
}
- (const webrtc::cast_tuning::CastTuningConfig &)nativeConfig;
- (RTCCastTuningEncoderEvidence *)encoderEvidence;
@end

@implementation RTCCastTuningConfiguration

+ (instancetype)configurationWithJSONData:(NSData *)data
                              environment:
                                  (NSDictionary<NSString *, NSString *> *)
                                      environment
                                    error:(NSError **)error {
  NSString *json = [[NSString alloc] initWithData:data
                                         encoding:NSUTF8StringEncoding];
  if (!json) {
    if (error) *error = CastError(@"CastTuning JSON is not UTF-8");
    return nil;
  }
  std::string nativeError;
  NSString *profile = environment[@"CAST_TUNING_PROFILE"] ?: @"";
  NSString *overrides = environment[@"CAST_TUNING_OVERRIDES_JSON"] ?: @"";
  std::optional<webrtc::cast_tuning::CastTuningConfig> config =
      webrtc::cast_tuning::CastTuningConfig::ParseJsonWithOverrides(
          json.UTF8String,
          profile.UTF8String,
          overrides.UTF8String,
          &nativeError);
  if (!config) {
    if (error)
      *error = CastError([NSString stringWithUTF8String:nativeError.c_str()]);
    return nil;
  }
  RTCCastTuningConfiguration *result = [[self alloc] init];
  result->_nativeConfig = std::move(*config);
  NSString *telemetryPath = result->_nativeConfig->telemetry.jsonl_path
                                 ? [NSString stringWithUTF8String:
                                       result->_nativeConfig->telemetry.jsonl_path
                                           ->c_str()]
                                 : nil;
  result->_encoderEvidence =
      [[RTCCastTuningEncoderEvidence alloc] initWithTelemetryPath:telemetryPath];
  return result;
}

+ (instancetype)configurationWithJSONData:(NSData *)data
                                    error:(NSError **)error {
  return [self configurationWithJSONData:data
                             environment:NSProcessInfo.processInfo.environment
                                   error:error];
}

+ (instancetype)configurationFromProcessEnvironmentWithError:(NSError **)error {
  NSString *path = NSProcessInfo.processInfo.environment[@"CAST_TUNING_CONFIG"];
  if (path.length == 0) {
    if (error) *error = CastError(@"CAST_TUNING_CONFIG is not set");
    return nil;
  }
  NSData *data = [NSData dataWithContentsOfFile:path options:0 error:error];
  return data ? [self configurationWithJSONData:data error:error] : nil;
}

- (const webrtc::cast_tuning::CastTuningConfig &)nativeConfig {
  return _nativeConfig.value();
}

- (RTCCastTuningEncoderEvidence *)encoderEvidence {
  return _encoderEvidence;
}

- (NSString *)profile {
  return [NSString stringWithUTF8String:webrtc::cast_tuning::ProfileName(
                                            _nativeConfig->profile)];
}

- (NSString *)fieldTrials {
  std::string trials = _nativeConfig->FieldTrialString();
  return [NSString stringWithUTF8String:trials.c_str()];
}

- (NSString *)effectiveConfigHash {
  webrtc::cast_tuning::WebRtcCastTuningBackend backend(*_nativeConfig);
  webrtc::cast_tuning::CastTuningController controller(*_nativeConfig,
                                                       &backend);
  return [NSString
      stringWithUTF8String:controller.snapshot().effective_config_hash.c_str()];
}

- (void)applyToRTCConfiguration:
    (RTC_OBJC_TYPE(RTCConfiguration) *)configuration {
  if (_nativeConfig->transport.relay_only) {
    configuration.iceTransportPolicy = *_nativeConfig->transport.relay_only ?
        RTCIceTransportPolicyRelay :
        RTCIceTransportPolicyAll;
  }
  if (_nativeConfig->transport.disable_tcp_candidates) {
    configuration.tcpCandidatePolicy =
        *_nativeConfig->transport.disable_tcp_candidates ?
        RTCTcpCandidatePolicyDisabled :
        RTCTcpCandidatePolicyEnabled;
  }
}

@end

@implementation RTCCastTuningLivePatch
@end

@interface RTCCastTuningApplyResult ()
@property(nonatomic) RTCCastTuningApplyStatus status;
@property(nonatomic) RTCCastTuningApplyScope requiredScope;
@property(nonatomic) NSString *effectiveConfigHash;
@property(nonatomic, nullable) NSString *errorMessage;
@property(nonatomic) NSArray<NSString *> *warnings;
@end

@implementation RTCCastTuningApplyResult
@end

@interface RTCCastTuningSnapshot ()
@property(nonatomic) NSString *sessionId;
@property(nonatomic) NSString *effectiveConfigHash;
@property(nonatomic) uint64_t revision;
@property(nonatomic) BOOL recreateRequired;
@property(nonatomic) BOOL profileMismatch;
@property(nonatomic, nullable) NSString *expectedH264Profile;
@property(nonatomic, nullable) NSString *actualH264Profile;
@property(nonatomic, nullable) NSString *videoToolboxEncoderId;
@property(nonatomic, nullable) NSString *encoderSessionId;
@end

@implementation RTCCastTuningSnapshot
@end

@interface RTCCastTuningVideoEncoderFactory
    : NSObject <RTC_OBJC_TYPE (RTCVideoEncoderFactory)>
- (instancetype)initWithBase:(id<RTC_OBJC_TYPE(RTCVideoEncoderFactory)>)base
                     options:(NSDictionary<NSString *, id> *)options;
@end

@implementation RTCCastTuningVideoEncoderFactory {
  id<RTC_OBJC_TYPE(RTCVideoEncoderFactory)> _base;
  NSDictionary<NSString *, id> *_options;
}

- (instancetype)initWithBase:(id<RTC_OBJC_TYPE(RTCVideoEncoderFactory)>)base
                     options:(NSDictionary<NSString *, id> *)options {
  if ((self = [super init])) {
    _base = base;
    _options = [options copy];
  }
  return self;
}

- (NSArray<RTC_OBJC_TYPE(RTCVideoCodecInfo) *> *)supportedCodecs {
  NSString *profile = _options[@"h264_profile"];
  NSString *level = _options[@"h264_level"];
  if (!profile && !level) return [_base supportedCodecs];

  NSDictionary<NSString *, NSString *> *levelIds = @{
    @"1.0" : @"0a",
    @"1.1" : @"0b",
    @"1.2" : @"0c",
    @"1.3" : @"0d",
    @"2.0" : @"14",
    @"2.1" : @"15",
    @"2.2" : @"16",
    @"3.0" : @"1e",
    @"3.1" : @"1f",
    @"3.2" : @"20",
    @"4.0" : @"28",
    @"4.1" : @"29",
    @"4.2" : @"2a",
    @"5.0" : @"32",
    @"5.1" : @"33",
    @"5.2" : @"34",
  };
  NSMutableArray<RTC_OBJC_TYPE(RTCVideoCodecInfo) *> *result =
      [NSMutableArray array];
  for (RTC_OBJC_TYPE(RTCVideoCodecInfo) * info in [_base supportedCodecs]) {
    if ([info.name caseInsensitiveCompare:@"H264"] != NSOrderedSame) {
      [result addObject:info];
      continue;
    }
    NSMutableDictionary<NSString *, NSString *> *parameters =
        [info.parameters mutableCopy];
    NSString *current = parameters[@"profile-level-id"];
    NSString *prefix =
        current.length == 6 ? [current substringToIndex:4] : @"42e0";
    if ([profile isEqualToString:@"CONSTRAINED_BASELINE"])
      prefix = @"42e0";
    else if ([profile isEqualToString:@"CONSTRAINED_HIGH"])
      prefix = @"640c";
    NSString *levelId = level ?
        levelIds[level] :
        (current.length == 6 ? [current substringFromIndex:4] : @"1f");
    parameters[@"profile-level-id"] = [prefix stringByAppendingString:levelId];
    [result addObject:[[RTC_OBJC_TYPE(RTCVideoCodecInfo) alloc]
                              initWithName:info.name
                                parameters:parameters
                          scalabilityModes:info.scalabilityModes]];
  }
  return result;
}

- (id<RTC_OBJC_TYPE(RTCVideoEncoder)>)createEncoder:
    (RTC_OBJC_TYPE(RTCVideoCodecInfo) *)info {
  if ([info.name caseInsensitiveCompare:@"H264"] == NSOrderedSame) {
    return
        [[RTC_OBJC_TYPE(RTCVideoEncoderH264) alloc] initWithCodecInfo:info
                                                    castTuningOptions:_options];
  }
  return [_base createEncoder:info];
}

@end

@implementation RTCCastTuningFactoryBuilder

+ (RTC_OBJC_TYPE(RTCPeerConnectionFactory) *)
    peerConnectionFactoryWithEncoderFactory:
        (id<RTC_OBJC_TYPE(RTCVideoEncoderFactory)>)encoderFactory
                             decoderFactory:
                                 (id<RTC_OBJC_TYPE(RTCVideoDecoderFactory)>)
                                     decoderFactory
                              configuration:
                                  (RTCCastTuningConfiguration *)configuration
                                      error:(NSError **)error {
  if (!encoderFactory) {
    if (error)
      *error = CastError(
          @"CastTuning requires an explicit hardware-capable encoder factory");
    return nil;
  }
  id<RTC_OBJC_TYPE(RTCVideoEncoderFactory)> base = encoderFactory;
  NSMutableDictionary<NSString *, id> *options =
      [EncoderOptions(configuration.nativeConfig) mutableCopy];
  options[@"config_hash"] = configuration.effectiveConfigHash;
  RTCCastTuningEncoderEvidence *evidence = configuration.encoderEvidence;
  [evidence setConfigHash:configuration.effectiveConfigHash];
  options[@"encoder_evidence_handler"] =
      [^(NSDictionary<NSString *, id> *event) {
        [evidence recordEvent:event];
      } copy];
  id<RTC_OBJC_TYPE(RTCVideoEncoderFactory)> tuned =
      [[RTCCastTuningVideoEncoderFactory alloc]
          initWithBase:base
               options:options];
  RTC_OBJC_TYPE(RTCPeerConnectionFactory) *factory =
      [[RTC_OBJC_TYPE(RTCPeerConnectionFactory) alloc]
          initWithEncoderFactory:tuned
                  decoderFactory:decoderFactory
                     audioDevice:nil
                     fieldTrials:configuration.fieldTrials];
  if (!factory && error)
    *error =
        CastError(@"Failed to create a per-factory CastTuning environment");
  return factory;
}

@end

@implementation RTCCastTuningController {
  std::unique_ptr<webrtc::cast_tuning::WebRtcCastTuningBackend> _backend;
  std::unique_ptr<webrtc::cast_tuning::CastTuningController> _controller;
  std::unique_ptr<ObjCVideoSourceAdapter> _sourceAdapter;
  RTCCastTuningEncoderEvidence *_encoderEvidence;
}

- (instancetype)initWithConfiguration:
    (RTCCastTuningConfiguration *)configuration {
  if ((self = [super init])) {
    _backend = std::make_unique<webrtc::cast_tuning::WebRtcCastTuningBackend>(
        configuration.nativeConfig);
    _controller = std::make_unique<webrtc::cast_tuning::CastTuningController>(
        configuration.nativeConfig, _backend.get());
    _encoderEvidence = configuration.encoderEvidence;
  }
  return self;
}

- (void)attachPeerConnection:
    (RTC_OBJC_TYPE(RTCPeerConnection) *)peerConnection {
  _backend->AttachPeerConnection(peerConnection.nativePeerConnection);
}

- (void)attachSender:(RTC_OBJC_TYPE(RTCRtpSender) *)sender
               track:(RTC_OBJC_TYPE(RTCVideoTrack) *)track
              source:(RTC_OBJC_TYPE(RTCVideoSource) *)source {
  _sourceAdapter =
      source ? std::make_unique<ObjCVideoSourceAdapter>(source) : nullptr;
  _backend->AttachSender(
      sender.nativeRtpSender, track.nativeVideoTrack, _sourceAdapter.get());
}

- (void)attachReceiver:(RTC_OBJC_TYPE(RTCRtpReceiver) *)receiver {
  _backend->AttachReceiver(receiver.nativeRtpReceiver);
}

- (RTCCastTuningApplyResult *)applyLivePatch:(RTCCastTuningLivePatch *)patch {
  webrtc::cast_tuning::CastTuningLivePatch native;
#define RTC_CAST_PATCH_INT(property, field) \
  if (patch.property) native.field = patch.property.intValue
  RTC_CAST_PATCH_INT(maxWidth, max_width);
  RTC_CAST_PATCH_INT(maxHeight, max_height);
  RTC_CAST_PATCH_INT(maxFps, max_fps);
  RTC_CAST_PATCH_INT(minBitrateBps, min_bitrate_bps);
  RTC_CAST_PATCH_INT(startBitrateBps, start_bitrate_bps);
  RTC_CAST_PATCH_INT(maxBitrateBps, max_bitrate_bps);
  RTC_CAST_PATCH_INT(jitterMinimumMs, jitter_minimum_ms);
  RTC_CAST_PATCH_INT(staleDecodedFrameMs, stale_decoded_frame_ms);
#undef RTC_CAST_PATCH_INT
  if ([patch.contentMode isEqualToString:@"TEXT"])
    native.content_mode = webrtc::cast_tuning::ContentMode::kText;
  else if ([patch.contentMode isEqualToString:@"FLUID"])
    native.content_mode = webrtc::cast_tuning::ContentMode::kFluid;
  if ([patch.degradationPreference isEqualToString:@"MAINTAIN_RESOLUTION"])
    native.degradation_preference =
        webrtc::cast_tuning::DegradationPreference::kMaintainResolution;
  else if ([patch.degradationPreference isEqualToString:@"MAINTAIN_FRAMERATE"])
    native.degradation_preference =
        webrtc::cast_tuning::DegradationPreference::kMaintainFramerate;

  webrtc::cast_tuning::CastApplyResult result =
      _controller->ApplyLivePatch(native);
  RTCCastTuningApplyResult *objcResult =
      [[RTCCastTuningApplyResult alloc] init];
  objcResult.status = static_cast<RTCCastTuningApplyStatus>(result.status);
  objcResult.requiredScope =
      static_cast<RTCCastTuningApplyScope>(result.required_scope);
  objcResult.effectiveConfigHash =
      [NSString stringWithUTF8String:result.effective_config_hash.c_str()];
  objcResult.errorMessage = result.error.empty() ?
      nil :
      [NSString stringWithUTF8String:result.error.c_str()];
  NSMutableArray<NSString *> *warnings = [NSMutableArray array];
  for (const std::string &warning : result.warnings)
    [warnings addObject:[NSString stringWithUTF8String:warning.c_str()]];
  objcResult.warnings = warnings;
  return objcResult;
}

- (BOOL)forceKeyFrameWithError:(NSError **)error {
  webrtc::RTCError result = _backend->ForceKeyFrame();
  if (!result.ok() && error) {
    std::string message(result.message());
    *error = CastError([NSString stringWithUTF8String:message.c_str()]);
  }
  return result.ok();
}

- (RTCCastTuningSnapshot *)snapshot {
  const webrtc::cast_tuning::CastTuningSnapshot &native =
      _controller->snapshot();
  RTCCastTuningSnapshot *snapshot = [[RTCCastTuningSnapshot alloc] init];
  snapshot.sessionId =
      [NSString stringWithUTF8String:native.session_id.c_str()];
  snapshot.effectiveConfigHash =
      [NSString stringWithUTF8String:native.effective_config_hash.c_str()];
  snapshot.revision = native.revision;
  snapshot.recreateRequired = native.recreate_required;
  NSDictionary<NSString *, id> *evidence = [_encoderEvidence snapshot];
  snapshot.profileMismatch = [evidence[@"profile_mismatch"] boolValue];
  snapshot.expectedH264Profile = evidence[@"expected_profile"];
  snapshot.actualH264Profile = evidence[@"actual_profile"];
  snapshot.videoToolboxEncoderId = evidence[@"encoder_id"];
  snapshot.encoderSessionId = evidence[@"encoder_session_id"];
  return snapshot;
}

@end
