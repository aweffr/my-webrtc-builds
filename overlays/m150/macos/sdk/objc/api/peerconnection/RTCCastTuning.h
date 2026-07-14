#import <Foundation/Foundation.h>

#import "RTCConfiguration.h"
#import "RTCPeerConnection.h"
#import "RTCPeerConnectionFactory.h"
#import "RTCRtpReceiver.h"
#import "RTCRtpSender.h"
#import "RTCVideoSource.h"
#import "RTCVideoTrack.h"
#import "sdk/objc/base/RTCMacros.h"
#import "sdk/objc/base/RTCVideoDecoderFactory.h"
#import "sdk/objc/base/RTCVideoEncoderFactory.h"

NS_ASSUME_NONNULL_BEGIN

typedef NS_ENUM(NSInteger, RTCCastTuningApplyStatus) {
  RTCCastTuningApplyStatusApplied,
  RTCCastTuningApplyStatusRejected,
  RTCCastTuningApplyStatusUnsupported,
  RTCCastTuningApplyStatusSessionRecreateRequired,
};

typedef NS_ENUM(NSInteger, RTCCastTuningApplyScope) {
  RTCCastTuningApplyScopeLive,
  RTCCastTuningApplyScopeSession,
  RTCCastTuningApplyScopeFactory,
};

RTC_OBJC_EXPORT
@interface RTCCastTuningConfiguration : NSObject

@property(nonatomic, readonly) NSString *profile;
@property(nonatomic, readonly) NSString *fieldTrials;
@property(nonatomic, readonly) NSString *effectiveConfigHash;

+ (nullable instancetype)
    configurationWithJSONData:(NSData *)data
                  environment:
                      (NSDictionary<NSString *, NSString *> *)environment
                        error:(NSError **)error;
+ (nullable instancetype)configurationWithJSONData:(NSData *)data
                                             error:(NSError **)error;
+ (nullable instancetype)configurationFromProcessEnvironmentWithError:
    (NSError **)error;
- (void)applyToRTCConfiguration:
    (RTC_OBJC_TYPE(RTCConfiguration) *)configuration;

@end

RTC_OBJC_EXPORT
@interface RTCCastTuningLivePatch : NSObject

@property(nonatomic, nullable) NSNumber *maxWidth;
@property(nonatomic, nullable) NSNumber *maxHeight;
@property(nonatomic, nullable) NSNumber *maxFps;
@property(nonatomic, nullable) NSNumber *minBitrateBps;
@property(nonatomic, nullable) NSNumber *startBitrateBps;
@property(nonatomic, nullable) NSNumber *maxBitrateBps;
@property(nonatomic, nullable) NSNumber *jitterMinimumMs;
@property(nonatomic, nullable) NSNumber *staleDecodedFrameMs;
@property(nonatomic, nullable) NSString *contentMode;
@property(nonatomic, nullable) NSString *degradationPreference;

@end

RTC_OBJC_EXPORT
@interface RTCCastTuningApplyResult : NSObject

@property(nonatomic, readonly) RTCCastTuningApplyStatus status;
@property(nonatomic, readonly) RTCCastTuningApplyScope requiredScope;
@property(nonatomic, readonly) NSString *effectiveConfigHash;
@property(nonatomic, readonly, nullable) NSString *errorMessage;
@property(nonatomic, readonly) NSArray<NSString *> *warnings;

@end

RTC_OBJC_EXPORT
@interface RTCCastTuningSnapshot : NSObject

@property(nonatomic, readonly) NSString *sessionId;
@property(nonatomic, readonly) NSString *effectiveConfigHash;
@property(nonatomic, readonly) uint64_t revision;
@property(nonatomic, readonly) BOOL recreateRequired;
@property(nonatomic, readonly) BOOL profileMismatch;
@property(nonatomic, readonly, nullable) NSString *expectedH264Profile;
@property(nonatomic, readonly, nullable) NSString *actualH264Profile;
@property(nonatomic, readonly, nullable) NSString *videoToolboxEncoderId;
@property(nonatomic, readonly, nullable) NSString *encoderSessionId;

@end

RTC_OBJC_EXPORT
@interface RTCCastTuningFactoryBuilder : NSObject

+ (nullable RTC_OBJC_TYPE(RTCPeerConnectionFactory) *)
    peerConnectionFactoryWithEncoderFactory:
        (nonnull id<RTC_OBJC_TYPE(RTCVideoEncoderFactory)>)encoderFactory
                             decoderFactory:
                                 (nullable
                                      id<RTC_OBJC_TYPE(RTCVideoDecoderFactory)>)
                                     decoderFactory
                              configuration:
                                  (RTCCastTuningConfiguration *)configuration
                                      error:(NSError **)error;

@end

RTC_OBJC_EXPORT
@interface RTCCastTuningController : NSObject

- (instancetype)initWithConfiguration:
    (RTCCastTuningConfiguration *)configuration;
- (void)attachPeerConnection:(RTC_OBJC_TYPE(RTCPeerConnection) *)peerConnection;
- (void)attachSender:(RTC_OBJC_TYPE(RTCRtpSender) *)sender
               track:(RTC_OBJC_TYPE(RTCVideoTrack) *)track
              source:(nullable RTC_OBJC_TYPE(RTCVideoSource) *)source;
- (void)attachReceiver:(RTC_OBJC_TYPE(RTCRtpReceiver) *)receiver;
- (RTCCastTuningApplyResult *)applyLivePatch:(RTCCastTuningLivePatch *)patch;
- (BOOL)forceKeyFrameWithError:(NSError **)error;
- (RTCCastTuningSnapshot *)snapshot;

@end

NS_ASSUME_NONNULL_END
