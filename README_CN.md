# WebRTC CastKit

[English](README.md)

WebRTC CastKit 是面向低延迟办公投屏的 WebRTC 运行时与可复现构建产物项目。它发布固定版本的 Android、iOS、macOS WebRTC M150 二进制，并在 Android 和 macOS 中加入 CastTuning runtime shim，使应用团队可以反复调整投屏参数，而不必每次都重新编译 WebRTC。

项目关注文字清晰度、交互反馈速度和可控恢复行为，而不是提供一个泛化的媒体预设。

## 项目提供什么

- 固定版本的 M150 构建产物：Android arm64、iOS device/simulator arm64、macOS x64/arm64 静态库；macOS 同时提供 framework/XCFramework。
- Android/macOS 的 CastTuning schema `1`：typed API、JSON 配置、macOS 环境变量、Android Intent override、live patch 与 snapshot。
- 内置 `UPSTREAM`、`DETAIL_IDLE`、`DETAIL_ACTIVE`、`MOTION`、`RECOVERY` 五个 profile。
- per-factory Field Trials、sender/receiver 调参、VideoToolbox 与 Android MediaCodec 低延迟 hook，以及 NACK/RTX/FEC advertisement 控制。
- 产物溯源、overlay hash、checksum 和可用于排障的诊断信息。

上游固定为 WebRTC M150 branch-head `7871` 的 commit
`1f975dfd761af6e5d76d28333191973b258d82a8`。构建时不接受任意 WebRTC
版本输入。

## 如何使用 CastTuning

从 [`examples/cast-tuning-detail-idle.json`](examples/cast-tuning-detail-idle.json) 开始。有效配置的优先级固定为：

```text
WebRTC upstream defaults → 内置 profile → JSON → 平台 override → live patch
```

默认 profile 是 `UPSTREAM`：不会生成 CastTuning Field Trial，也不会调用任何调参 setter，严格保持 upstream 行为。

macOS 支持以下环境变量：

```bash
export CAST_TUNING_CONFIG=/absolute/path/cast-tuning.json
export CAST_TUNING_PROFILE=DETAIL_ACTIVE
export CAST_TUNING_OVERRIDES_JSON='{"sender":{"max_fps":20}}'
```

macOS framework 提供 `RTCCastTuningConfiguration`、
`RTCCastTuningFactoryBuilder`、`RTCCastTuningController`。Android 提供
`CastTuningConfig`、`CastTuningAndroidConfig`、`CastTuningController`：

macOS factory builder 必须显式传入支持硬件加速的
`RTCVideoEncoderFactory`（例如 VideoToolbox H264 factory），不会隐式引入
WebRTC software codec factory。

```java
CastTuningConfig config = CastTuningAndroidConfig.fromIntent(baseJson, intent);
try (CastTuningController tuning = new CastTuningController(config)) {
  PeerConnectionFactory.Builder factoryBuilder =
      tuning.configureFactory(PeerConnectionFactory.builder());
  tuning.configurePeerConnection(rtcConfiguration);
  tuning.attachReceiver(videoReceiver);
  VideoDecoderFactory decoders = tuning.createVideoDecoderFactory(eglContext);
}
```

Android Intent extra 为 `org.webrtc.cast_tuning.PROFILE` 和
`org.webrtc.cast_tuning.OVERRIDES_JSON`。

| 生效域 | 示例 | 生效方式 |
| --- | --- | --- |
| `LIVE` | bitrate 边界、FPS、content hint、minimum jitter delay | 应用已校验的 live patch |
| `SESSION` | start bitrate/BWE reset、encoder/decoder 创建参数 | 重建 session |
| `FACTORY` | Field Trials、pacer、recovery advertisement | 重建 factory 和 session |

live patch 会整体预校验。setter 失败时，CastTuning 会回滚旧值；如果回滚失败，结果会返回 `SESSION_RECREATE_REQUIRED`，不会伪装成局部成功。

办公投屏的第一轮建议使用：NACK+RTX、关闭 FEC、minimum jitter delay 为 0、关闭 prerender smoothing、开启 VideoToolbox realtime、禁止 frame reorder。每次只改变一个变量，并记录 session ID、effective config hash、revision 与测量数据。

完整设计与边界见
[`docs/superpowers/specs/2026-07-12-cast-tuning-shim-design.md`](docs/superpowers/specs/2026-07-12-cast-tuning-shim-design.md)。

## 构建产物

| 平台 | 产物 | 内容 |
| --- | --- | --- |
| Android | `webrtc-m150-android-arm64-v8a.tar.gz` | arm64 静态库、C++ headers、`webrtc.jar`、CastTuning Java/JNI API |
| iOS | `webrtc-m150-ios.tar.gz` | 分离的 device/simulator arm64 静态库和 headers |
| macOS x64 | `webrtc-m150-macos-x64.tar.gz` | x64 静态库、headers、thin `WebRTC.framework`、CastTuning ObjC API |
| macOS arm64 | `webrtc-m150-macos-arm64.tar.gz` | arm64 静态库、headers、thin `WebRTC.framework`、CastTuning ObjC API |
| macOS universal | `WebRTC-m150-macos-universal.xcframework.zip` | universal `WebRTC.xcframework` |

静态包都包含 resolved GN arguments、metadata schema `2`、patch/overlay hash、上游 license/notice 和 `SHA256SUMS`。

## 构建与发布运维

GitHub Actions 的触发、XCFramework 合并、release 发布、本地验证及失败诊断请见 [`docs/runbook.md`](docs/runbook.md)。

每个 hosted build 即使失败也会上传 diagnostics，包含完整 builder log、JSONL phase journal、按架构保存的 GN arguments、patch hash、source identity、toolchain/disk 状态和完整 output inventory。

## Codec 与许可证说明

- macOS 静态库包含 OpenH264 encoder 与 FFmpeg H.264 decoder。
- Apple framework 使用 VideoToolbox H.264/H.265；Android 通过 WebRTC Java/JNI 使用 MediaCodec H.264/H.265。
- 项目编译 codec capability，但不修改 upstream runtime codec-factory selection，也不提供 H.265 software fallback。

发行方负责满足 H.264/H.265 的产品与专利许可要求。项目自研代码采用 Apache-2.0；patch 来源见 [`patches/m150/SOURCES.md`](patches/m150/SOURCES.md)。
