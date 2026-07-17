#import <CoreVideo/CoreVideo.h>
#import <Foundation/Foundation.h>
#import <WebRTC/RTCCVPixelBuffer.h>
#import <WebRTC/RTCEncodedImage.h>
#import <WebRTC/RTCLogging.h>
#import <WebRTC/RTCVideoCodecInfo.h>
#import <WebRTC/RTCVideoEncoder.h>
#import <WebRTC/RTCVideoEncoderH264.h>
#import <WebRTC/RTCVideoEncoderH265.h>
#import <WebRTC/RTCVideoEncoderSettings.h>
#import <WebRTC/RTCVideoFrame.h>

#include <cstdint>
#include <cstring>

namespace {

NSString *ProfileFamilyForAnnexB(NSData *encoded) {
  const uint8_t *bytes = static_cast<const uint8_t *>(encoded.bytes);
  const size_t size = encoded.length;
  for (size_t index = 0; index + 5 < size; ++index) {
    size_t prefix = 0;
    if (bytes[index] == 0 && bytes[index + 1] == 0 && bytes[index + 2] == 1) {
      prefix = 3;
    } else if (index + 6 < size && bytes[index] == 0 &&
               bytes[index + 1] == 0 && bytes[index + 2] == 0 &&
               bytes[index + 3] == 1) {
      prefix = 4;
    }
    if (prefix == 0 || index + prefix + 2 >= size)
      continue;
    const uint8_t nalType = bytes[index + prefix] & 0x1f;
    if (nalType != 7)
      continue;
    switch (bytes[index + prefix + 1]) {
      case 66:
        return @"BASELINE";
      case 77:
        return @"MAIN";
      case 100:
        return @"HIGH";
      default:
        return [NSString
            stringWithFormat:@"PROFILE_IDC_%u", bytes[index + prefix + 1]];
    }
  }
  return @"UNKNOWN";
}

RTCVideoCodecInfo *Codec(BOOL lowLatency) {
  return [[RTCVideoCodecInfo alloc]
      initWithName:@"H264"
        parameters:@{
          @"profile-level-id" : lowLatency ? @"640c29" : @"42e029",
          @"level-asymmetry-allowed" : @"1",
          @"packetization-mode" : @"1",
        }];
}

CVPixelBufferRef CreateFrameBuffer() {
  CVPixelBufferRef pixelBuffer = nullptr;
  NSDictionary *attributes = @{
    (NSString *)kCVPixelBufferIOSurfacePropertiesKey : @{},
  };
  CVReturn result = CVPixelBufferCreate(
      kCFAllocatorDefault,
      1920,
      1080,
      kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
      (__bridge CFDictionaryRef)attributes,
      &pixelBuffer);
  if (result != kCVReturnSuccess)
    return nullptr;
  CVPixelBufferLockBaseAddress(pixelBuffer, 0);
  memset(CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0),
         16,
         CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0) *
             CVPixelBufferGetHeightOfPlane(pixelBuffer, 0));
  memset(CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 1),
         128,
         CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 1) *
             CVPixelBufferGetHeightOfPlane(pixelBuffer, 1));
  CVPixelBufferUnlockBaseAddress(pixelBuffer, 0);
  return pixelBuffer;
}

NSDictionary<NSString *, id> *RunMode(BOOL lowLatency) {
  NSString *mode = lowLatency ? @"low_latency" : @"normal";
  NSString *expectedProfile = lowLatency ? @"HIGH" : @"BASELINE";
  RTCVideoCodecInfo *codec = Codec(lowLatency);
  if (!codec) {
    return @{
      @"mode" : mode,
      @"requested_low_latency" : @(lowLatency),
      @"session_status" : @"codec_unavailable",
    };
  }

  __block NSMutableDictionary<NSString *, id> *encoderEvidence =
      [NSMutableDictionary dictionary];
  __block NSDictionary<NSString *, id> *runtimeRequest = @{
    @"generation" : @1,
    @"requested_max_qp" : @32,
  };
  __block NSMutableDictionary<NSNumber *, NSMutableDictionary<NSString *, id> *>
      *runtimeEvidence = [NSMutableDictionary dictionary];
  NSObject *runtimeLock = [[NSObject alloc] init];
  void (^evidenceHandler)(NSDictionary<NSString *, id> *) =
      ^(NSDictionary<NSString *, id> *event) {
        @synchronized(encoderEvidence) {
          [encoderEvidence addEntriesFromDictionary:event];
        }
      };
  NSDictionary<NSString *, id> *(^runtimeProvider)(void) =
      ^NSDictionary<NSString *, id> * {
        @synchronized(runtimeLock) {
          return [runtimeRequest copy];
        }
      };
  void (^runtimeResultHandler)(NSDictionary<NSString *, id> *) =
      ^(NSDictionary<NSString *, id> *event) {
        NSNumber *generation = event[@"generation"];
        if (![generation isKindOfClass:[NSNumber class]])
          return;
        @synchronized(runtimeLock) {
          NSMutableDictionary<NSString *, id> *record =
              runtimeEvidence[generation];
          if (!record) {
            record = [NSMutableDictionary dictionary];
            runtimeEvidence[generation] = record;
          }
          [record addEntriesFromDictionary:event];
          NSString *eventType = event[@"event_type"];
          if ([eventType isEqualToString:@"encoder_runtime_qp_applied"])
            record[@"apply_state"] = @"applied";
          else if ([eventType
                       isEqualToString:@"encoder_runtime_qp_unsupported"])
            record[@"apply_state"] = @"unsupported";
          else if ([eventType isEqualToString:@"encoder_runtime_qp_failed"])
            record[@"apply_state"] = @"failed";
        }
      };
  NSDictionary<NSString *, id> *options = @{
    @"hardware_policy" : @"REQUIRE_HARDWARE",
    @"realtime" : @(YES),
    @"allow_frame_reordering" : @(NO),
    @"video_toolbox_low_latency_rate_control" : @(lowLatency),
    @"config_hash" : [NSString stringWithFormat:@"probe-%@", mode],
    @"encoder_evidence_handler" : [evidenceHandler copy],
    @"encoder_runtime_qp_provider" : [runtimeProvider copy],
    @"encoder_runtime_qp_result_handler" : [runtimeResultHandler copy],
  };
  RTCVideoEncoderH264 *encoder =
      [[RTCVideoEncoderH264 alloc] initWithCodecInfo:codec
                                  castTuningOptions:options];
  dispatch_semaphore_t encodedSemaphore = dispatch_semaphore_create(0);
  __block NSData *encoded = nil;
  [encoder setCallback:^BOOL(RTCEncodedImage *image, id info) {
    if (image.frameType == RTCFrameTypeVideoFrameKey) {
      if (!encoded)
        encoded = [image.buffer copy];
      dispatch_semaphore_signal(encodedSemaphore);
    }
    return YES;
  }];

  RTCVideoEncoderSettings *settings = [[RTCVideoEncoderSettings alloc] init];
  settings.name = @"H264";
  settings.width = 1920;
  settings.height = 1080;
  settings.startBitrate = 4000;
  settings.maxBitrate = 8000;
  settings.minBitrate = 250;
  settings.maxFramerate = 30;
  settings.qpMax = 51;
  settings.mode = RTCVideoCodecModeScreensharing;

  const NSInteger startStatus =
      [encoder startEncodeWithSettings:settings numberOfCores:4];
  if (startStatus != 0) {
    [encoder releaseEncoder];
    return @{
      @"mode" : mode,
      @"requested_low_latency" : @(lowLatency),
      @"session_status" : @"create_failed",
      @"start_status" : @(startStatus),
    };
  }

  NSArray<NSNumber *> *requestedQps = @[ @32, @24, @32 ];
  NSMutableArray<NSDictionary<NSString *, id> *> *runtimeQp =
      [NSMutableArray arrayWithCapacity:requestedQps.count];
  NSInteger encodeStatus = 0;
  long waitStatus = 0;
  for (NSUInteger index = 0; index < requestedQps.count; ++index) {
    NSNumber *generation = @(index + 1);
    NSNumber *requestedMaxQp = requestedQps[index];
    @synchronized(runtimeLock) {
      runtimeRequest = @{
        @"generation" : generation,
        @"requested_max_qp" : requestedMaxQp,
      };
    }

    CVPixelBufferRef pixelBuffer = CreateFrameBuffer();
    if (!pixelBuffer) {
      encodeStatus = -1;
      break;
    }
    RTCCVPixelBuffer *buffer =
        [[RTCCVPixelBuffer alloc] initWithPixelBuffer:pixelBuffer];
    RTCVideoFrame *frame = [[RTCVideoFrame alloc]
        initWithBuffer:buffer
              rotation:RTCVideoRotation_0
           timeStampNs:static_cast<int64_t>(index + 1) * 1'000'000];
    frame.timeStamp = static_cast<uint32_t>((index + 1) * 90);
    encodeStatus = [encoder
        encode:frame
        codecSpecificInfo:nil
        frameTypes:@[ @(RTCFrameTypeVideoFrameKey) ]];
    CVPixelBufferRelease(pixelBuffer);
    if (encodeStatus != 0)
      break;
    waitStatus = dispatch_semaphore_wait(
        encodedSemaphore,
        dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC));
    if (waitStatus != 0)
      break;

    @synchronized(runtimeLock) {
      NSMutableDictionary<NSString *, id> *record =
          [runtimeEvidence[generation] mutableCopy] ?: [NSMutableDictionary dictionary];
      record[@"generation"] = generation;
      record[@"requested_max_qp"] = requestedMaxQp;
      [runtimeQp addObject:record];
    }
  }
  [encoder releaseEncoder];
  if (encodeStatus != 0 || waitStatus != 0 || !encoded ||
      runtimeQp.count != requestedQps.count) {
    return @{
      @"mode" : mode,
      @"requested_low_latency" : @(lowLatency),
      @"session_status" : @"encode_failed",
      @"encode_status" : @(encodeStatus),
      @"callback_timed_out" : @(waitStatus != 0),
    };
  }

  NSString *actualProfile = ProfileFamilyForAnnexB(encoded);
  const BOOL mismatch = ![expectedProfile isEqualToString:actualProfile];
  NSMutableDictionary<NSString *, id> *result = [@{
    @"mode" : mode,
    @"requested_low_latency" : @(lowLatency),
    @"session_status" : @"success",
    @"negotiated_profile" : expectedProfile,
    @"sps_profile" : actualProfile,
    @"profile_mismatch" : @(mismatch),
    @"encoded_bytes" : @(encoded.length),
    @"runtime_qp" : runtimeQp,
  } mutableCopy];
  @synchronized(encoderEvidence) {
    result[@"encoder_id"] = encoderEvidence[@"encoder_id"] ?: @"UNKNOWN";
    result[@"encoder_session_id"] =
        encoderEvidence[@"encoder_session_id"] ?: @"UNKNOWN";
    result[@"reported_expected_profile"] =
        encoderEvidence[@"expected_profile"] ?: @"UNKNOWN";
    result[@"reported_actual_profile"] =
        encoderEvidence[@"actual_profile"] ?: @"UNKNOWN";
    result[@"reported_profile_mismatch"] =
        encoderEvidence[@"profile_mismatch"] ?: @(NO);
  }
  return result;
}

NSDictionary<NSString *, id> *RunHevcMode(NSString *mode,
                                           NSString *spatialAdaptiveQp,
                                           BOOL lowLatency) {
  RTCVideoCodecInfo *codec =
      [[RTCVideoCodecInfo alloc] initWithName:@"H265" parameters:@{}];
  __block NSMutableDictionary<NSString *, id> *encoderEvidence =
      [NSMutableDictionary dictionary];
  __block NSDictionary<NSString *, id> *runtimeRequest = @{
    @"generation" : @1,
    @"requested_max_qp" : @32,
  };
  __block NSMutableDictionary<NSNumber *, NSMutableDictionary<NSString *, id> *>
      *runtimeEvidence = [NSMutableDictionary dictionary];
  NSObject *runtimeLock = [[NSObject alloc] init];
  void (^evidenceHandler)(NSDictionary<NSString *, id> *) =
      ^(NSDictionary<NSString *, id> *event) {
        @synchronized(encoderEvidence) {
          [encoderEvidence addEntriesFromDictionary:event];
        }
      };
  NSDictionary<NSString *, id> *(^runtimeProvider)(void) =
      ^NSDictionary<NSString *, id> * {
        @synchronized(runtimeLock) {
          return [runtimeRequest copy];
        }
      };
  void (^runtimeResultHandler)(NSDictionary<NSString *, id> *) =
      ^(NSDictionary<NSString *, id> *event) {
        NSNumber *generation = event[@"generation"];
        if (![generation isKindOfClass:[NSNumber class]])
          return;
        @synchronized(runtimeLock) {
          NSMutableDictionary<NSString *, id> *record =
              runtimeEvidence[generation];
          if (!record) {
            record = [NSMutableDictionary dictionary];
            runtimeEvidence[generation] = record;
          }
          [record addEntriesFromDictionary:event];
          NSString *eventType = event[@"event_type"];
          if ([eventType isEqualToString:@"encoder_runtime_qp_applied"])
            record[@"apply_state"] = @"applied";
          else if ([eventType
                       isEqualToString:@"encoder_runtime_qp_unsupported"])
            record[@"apply_state"] = @"unsupported";
          else if ([eventType isEqualToString:@"encoder_runtime_qp_failed"])
            record[@"apply_state"] = @"failed";
        }
      };

  NSMutableDictionary<NSString *, id> *options = [@{
    @"hardware_policy" : @"REQUIRE_HARDWARE",
    @"realtime" : @(YES),
    @"allow_frame_reordering" : @(NO),
    @"video_toolbox_low_latency_rate_control" : @(lowLatency),
    @"config_hash" : [NSString stringWithFormat:@"probe-%@", mode],
    @"encoder_evidence_handler" : [evidenceHandler copy],
    @"encoder_runtime_qp_provider" : [runtimeProvider copy],
    @"encoder_runtime_qp_result_handler" : [runtimeResultHandler copy],
  } mutableCopy];
  if (spatialAdaptiveQp) {
    options[@"video_toolbox_spatial_adaptive_qp"] = spatialAdaptiveQp;
  }
  RTCVideoEncoderH265 *encoder =
      [[RTCVideoEncoderH265 alloc] initWithCodecInfo:codec
                                  castTuningOptions:options];
  dispatch_semaphore_t encodedSemaphore = dispatch_semaphore_create(0);
  __block NSUInteger encodedBytes = 0;
  [encoder setCallback:^BOOL(RTCEncodedImage *image, id info) {
    if (image.frameType == RTCFrameTypeVideoFrameKey) {
      encodedBytes = image.buffer.length;
      dispatch_semaphore_signal(encodedSemaphore);
    }
    return YES;
  }];

  RTCVideoEncoderSettings *settings = [[RTCVideoEncoderSettings alloc] init];
  settings.name = @"H265";
  settings.width = 1920;
  settings.height = 1080;
  settings.startBitrate = 4000;
  settings.maxBitrate = 8000;
  settings.minBitrate = 250;
  settings.maxFramerate = 30;
  settings.qpMax = 51;
  settings.mode = RTCVideoCodecModeScreensharing;

  const NSInteger startStatus =
      [encoder startEncodeWithSettings:settings numberOfCores:4];
  if (startStatus != 0) {
    [encoder releaseEncoder];
    return @{
      @"codec" : @"H265",
      @"mode" : mode,
      @"session_status" : @"create_failed",
      @"start_status" : @(startStatus),
    };
  }

  NSArray<NSNumber *> *requestedQps = @[ @32, @22, @32 ];
  NSMutableArray<NSDictionary<NSString *, id> *> *runtimeQp =
      [NSMutableArray arrayWithCapacity:requestedQps.count];
  NSInteger encodeStatus = 0;
  long waitStatus = 0;
  for (NSUInteger index = 0; index < requestedQps.count; ++index) {
    NSNumber *generation = @(index + 1);
    NSNumber *requestedMaxQp = requestedQps[index];
    @synchronized(runtimeLock) {
      runtimeRequest = @{
        @"generation" : generation,
        @"requested_max_qp" : requestedMaxQp,
      };
    }
    CVPixelBufferRef pixelBuffer = CreateFrameBuffer();
    if (!pixelBuffer) {
      encodeStatus = -1;
      break;
    }
    RTCCVPixelBuffer *buffer =
        [[RTCCVPixelBuffer alloc] initWithPixelBuffer:pixelBuffer];
    RTCVideoFrame *frame = [[RTCVideoFrame alloc]
        initWithBuffer:buffer
              rotation:RTCVideoRotation_0
           timeStampNs:static_cast<int64_t>(index + 1) * 1'000'000];
    frame.timeStamp = static_cast<uint32_t>((index + 1) * 90);
    encodeStatus = [encoder
        encode:frame
        codecSpecificInfo:nil
        frameTypes:@[ @(RTCFrameTypeVideoFrameKey) ]];
    CVPixelBufferRelease(pixelBuffer);
    if (encodeStatus != 0)
      break;
    waitStatus = dispatch_semaphore_wait(
        encodedSemaphore,
        dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC));
    if (waitStatus != 0)
      break;
    @synchronized(runtimeLock) {
      NSMutableDictionary<NSString *, id> *record =
          [runtimeEvidence[generation] mutableCopy] ?:
              [NSMutableDictionary dictionary];
      record[@"generation"] = generation;
      record[@"requested_max_qp"] = requestedMaxQp;
      [runtimeQp addObject:record];
    }
  }
  [encoder releaseEncoder];
  if (encodeStatus != 0 || waitStatus != 0 || encodedBytes == 0 ||
      runtimeQp.count != requestedQps.count) {
    return @{
      @"codec" : @"H265",
      @"mode" : mode,
      @"session_status" : @"encode_failed",
      @"encode_status" : @(encodeStatus),
      @"callback_timed_out" : @(waitStatus != 0),
    };
  }

  NSMutableDictionary<NSString *, id> *result = [@{
    @"codec" : @"H265",
    @"mode" : mode,
    @"requested_low_latency" : @(lowLatency),
    @"requested_spatial_adaptive_qp" : spatialAdaptiveQp ?: [NSNull null],
    @"session_status" : @"success",
    @"encoded_bytes" : @(encodedBytes),
    @"runtime_qp" : runtimeQp,
  } mutableCopy];
  @synchronized(encoderEvidence) {
    result[@"encoder_id"] = encoderEvidence[@"encoder_id"] ?: @"UNKNOWN";
    result[@"encoder_session_id"] =
        encoderEvidence[@"encoder_session_id"] ?: @"UNKNOWN";
    result[@"spatial_event_type"] =
        encoderEvidence[@"event_type"] ?: @"not_requested";
    result[@"effective_spatial_adaptive_qp_level"] =
        encoderEvidence[@"effective_spatial_adaptive_qp_level"] ?:
            [NSNull null];
    result[@"spatial_os_status"] =
        encoderEvidence[@"os_status"] ?: [NSNull null];
    result[@"effective_realtime"] =
        encoderEvidence[@"effective_realtime"] ?: [NSNull null];
    result[@"realtime_os_status"] =
        encoderEvidence[@"realtime_os_status"] ?: [NSNull null];
    result[@"effective_allow_frame_reordering"] =
        encoderEvidence[@"effective_allow_frame_reordering"] ?:
            [NSNull null];
    result[@"allow_frame_reordering_os_status"] =
        encoderEvidence[@"allow_frame_reordering_os_status"] ?:
            [NSNull null];
  }
  return result;
}

void PrintJson(NSDictionary<NSString *, id> *value) {
  NSError *error = nil;
  NSData *data = [NSJSONSerialization dataWithJSONObject:value
                                                 options:0
                                                   error:&error];
  if (!data) {
    fprintf(stderr, "cannot serialize probe result: %s\n",
            error.localizedDescription.UTF8String);
    return;
  }
  fwrite(data.bytes, 1, data.length, stdout);
  fputc('\n', stdout);
}

}  // namespace

int main() {
  @autoreleasepool {
    RTCSetMinDebugLogLevel(RTCLoggingSeverityInfo);
    NSDictionary<NSString *, id> *normal = RunMode(NO);
    NSDictionary<NSString *, id> *lowLatency = RunMode(YES);
    NSDictionary<NSString *, id> *hevcDefault =
        RunHevcMode(@"hevc_spatial_default", @"DEFAULT", NO);
    NSDictionary<NSString *, id> *hevcDisable =
        RunHevcMode(@"hevc_spatial_disable", @"DISABLE", NO);
    NSDictionary<NSString *, id> *hevcLowLatency =
        RunHevcMode(@"hevc_low_latency", nil, YES);
    PrintJson(normal);
    PrintJson(lowLatency);
    PrintJson(hevcDefault);
    PrintJson(hevcDisable);
    PrintJson(hevcLowLatency);
    return [normal[@"session_status"] isEqualToString:@"success"] &&
            [lowLatency[@"session_status"] isEqualToString:@"success"] &&
            [hevcDefault[@"session_status"] isEqualToString:@"success"] &&
            [hevcDisable[@"session_status"] isEqualToString:@"success"] &&
            [hevcLowLatency[@"session_status"] isEqualToString:@"success"]
        ? 0
        : 1;
  }
}
