# WebRTC M150 reference sources

This directory keeps the small subset of upstream WebRTC sources used to
reason about the published M150 artifacts and downstream screen-casting
integration. It is an inspection aid, not an alternate source checkout and not
part of the build input.

## Source identity

- Upstream: `https://webrtc.googlesource.com/src`
- Milestone: M150
- Branch head: `7871`
- Commit: `1f975dfd761af6e5d76d28333191973b258d82a8`
- Related release:
  `webrtc-m150.7871.3-eeca1bc-20260713-all`

The files below `upstream/` are unmodified copies fetched from that exact
commit. `upstream/SHA256SUMS` records their local content hashes. The upstream
BSD license is preserved as `upstream/LICENSE`.

## Why these files are retained

### Android Java 8 package contract

- `build/android/gyp/compile_java.py`
- `build/android/gyp/turbine.py`
- `sdk/android/api/org/webrtc/EglRenderer.java`
- `sdk/android/api/org/webrtc/NetworkMonitorAutoDetect.java`
- `third_party/jni_zero/java/src/org/jni_zero/CommonApis.java`

Together with the JNI generator files below, these are every upstream source
modified by `android_java8.patch`. The two build files come from Chromium build
commit `d296a9fec6186f2c109758c7d3f93cbef936dfc3`; the SDK files come from the
pinned WebRTC commit; and `CommonApis.java` comes from Chromium third-party
commit `7c92732938de0ef7e28f5da231994723f938f407`.

### Android JNI Zero Java generation

- `third_party/jni_zero/codegen/proxy_impl_java.py`
- `third_party/jni_zero/codegen/placeholder_java_type.py`
- `third_party/jni_zero/codegen/gen_jni_java.py`
- `third_party/jni_zero/codegen/placeholder_gen_jni_java.py`

These four unmodified files come from Chromium `third_party` commit
`7c92732938de0ef7e28f5da231994723f938f407`, pinned by the M150 checkout. They
cover every generator path that emits `@Generated` into JNI Java sources and
are retained because Java language scans alone cannot reveal generated-source
compatibility failures.

### Capture cadence and zero-hertz behavior

- `video/frame_cadence_adapter.cc`
- `video/frame_cadence_adapter.h`
- `video/video_stream_encoder.cc`
- `media/base/video_adapter.cc`

These files define the conditions that enable zero-hertz screen-share mode,
its one-second idle repeat cadence, source frame-rate adaptation, and the point
where screen content enables the cadence adapter.

### macOS capture-to-encoder path

- `sdk/objc/api/peerconnection/RTCVideoSource.mm`
- `sdk/objc/native/src/objc_video_track_source.mm`
- `sdk/objc/components/video_codec/RTCVideoEncoderH264.mm`
- `media/engine/webrtc_video_engine.cc`

These files show how `RTCVideoFrame` timestamps and `CVPixelBuffer` objects enter
the native video source, how output adaptation is applied, which VideoToolbox
H.264 properties stock M150 sets, and how screen-content mode changes encoder
and degradation behavior.

### Observability

- `api/stats/rtcstats_objects.h`
- `pc/rtc_stats_collector.cc`
- `sdk/objc/api/peerconnection/RTCPeerConnection+Stats.mm`
- `sdk/objc/api/peerconnection/RTCStatisticsReport.mm`

These files are the local reference for M150 `RTCStats` fields, collection
semantics, and the Objective-C bridge exposed by the released framework.

## Verification

Run from this directory:

```bash
cd upstream
shasum -a 256 -c SHA256SUMS
```

When the pinned WebRTC or Chromium third-party commit changes, replace the
corresponding retained files and regenerate `SHA256SUMS` in the same change. Do
not silently mix files from different upstream revisions.
