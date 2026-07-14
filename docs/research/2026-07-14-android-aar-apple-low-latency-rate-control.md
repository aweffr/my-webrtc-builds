# Android AAR 与 Apple Low-Latency Rate Control 调研

## 调研范围

本文只处理两个 M150 binary/release contract：Android 产物必须可被 Android
App 直接消费；Apple H.264 VideoToolbox encoder 必须能显式请求并证明
low-latency rate control。Android TV 应用和 macOS 投屏应用不在本次范围内。

## Android 产物现状

当前 Android GN build 已同时构建：

- `lib.java/sdk/android/libwebrtc.jar`
- `libjingle_peerconnection_so.so`
- 聚合的 `libwebrtc.a`

2026-07-13 的成功 Actions run `29234927974` 在 build log 中包含
`SOLINK ./libjingle_peerconnection_so.so`，output inventory 也同时包含 stripped
和 unstripped `.so`。问题发生在本仓库的 staging：`builder/package.py` 只复制
`libwebrtc.a` 和 `libwebrtc.jar`，因此已发布的
`webrtc-m150-android-arm64-v8a.tar.gz` 丢失 Java API 默认加载的 JNI shared
library。

Exact M150 自带的
[`tools_webrtc/android/build_aar.py`](https://webrtc.googlesource.com/src/+/1f975dfd761af6e5d76d28333191973b258d82a8/tools_webrtc/android/build_aar.py)
定义了标准 app-consumable 结构：

```text
AndroidManifest.xml
classes.jar
jni/arm64-v8a/libjingle_peerconnection_so.so
```

因此不需要在应用仓库重新链接 `libwebrtc.a`，也不应再运行一套独立的 GN
build。采用的 release contract 是：

1. raw tar 保留 C++ headers/static library，并补入 stripped JNI `.so`；
2. Release 新增独立 arm64-v8a AAR；
3. AAR 的 `classes.jar`/`.so` 与 raw tar 来自同一个 BuildUnit；
4. verifier 比较两种容器内 payload 的 SHA-256，并检查 AArch64、动态依赖、
   `JNI_OnLoad`、CastTuning Java/JNI API 和 archive path safety；
5. release manifest、`SHA256SUMS` 和 GitHub Release 同时列出 tar 与 AAR。

## Apple API 的准确含义

准确的 API 名称是
`kVTVideoEncoderSpecification_EnableLowLatencyRateControl`。它不是创建后的
compression property，而是传入 `VTCompressionSessionCreate` 的
`encoderSpecification`。本机 Xcode 26.5 SDK 声明其从 macOS 11.3、iOS/tvOS
14.5 起可用；项目最低 macOS 14，因此 macOS framework 不需要弱链接兼容。

[Apple 文档](https://developer.apple.com/documentation/videotoolbox/kvtvideoencoderspecification_enablelowlatencyratecontrol)
称该模式要求支持低延迟的 encoder，并带来 infinite GOP、无 B-frame/lookahead、
High profile family 和 temporal-layer structure。Apple 的
[low-latency conferencing sample](https://developer.apple.com/documentation/videotoolbox/encoding-video-for-low-latency-conferencing)
同样要求在创建 compression session 时传入该 key。

Exact M150 的 `RTCVideoEncoderH264.mm` 只请求 hardware acceleration，创建后设置
`RealTime=true`、协商的 H.264 profile、`AllowFrameReordering=false` 和 bitrate；
没有引用 low-latency rate-control key。对已发布 universal XCFramework 执行
undefined-symbol/strings inspection 也只能找到 `RealTime` 和 hardware property，
找不到 `EnableLowLatencyRateControl`，所以“当前 binary 未启用”已由源码和 binary
两侧确认。

## 本机 VideoToolbox 实测

在 macOS 26.5.2、Apple M5 Pro 上用 1920×1080 H.264 session 直接测试：

| Session | 创建 | 实际 SPS profile | Encoder ID |
| --- | --- | --- | --- |
| 普通 + Constrained Baseline | 成功 | `42c0` | `com.apple.videotoolbox.videoencoder.ave.avc` |
| Low latency + Constrained Baseline | 成功 | `42c0` | `com.apple.videotoolbox.videoencoder.h264.rtvc` |
| Low latency + Constrained High | 成功 | `640c` | `com.apple.videotoolbox.videoencoder.h264.rtvc` |
| Low latency + High | 成功 | `6400` | `com.apple.videotoolbox.videoencoder.h264.rtvc` |

结果说明当前 M5/macOS 26 的 RTVC encoder 实际接受 Constrained Baseline，且
输出 SPS 与请求 profile 一致；这与 Apple 文档“only High profiles”的概括存在
版本/实现差异，不能只依赖文档推断所有部署环境。Low-latency session 查询
`UsingHardwareAcceleratedVideoEncoder` 返回 property-not-supported，但
`EncoderID` 明确切换到 `h264.rtvc`；因此现有代码会把这类 session 错记为
“hardware disabled”，需要同步修正观测逻辑。

同一 probe 中 `AverageBitRate` 和 `DataRateLimits` 在当前系统均返回成功。不过
[Chromium 的 VideoToolbox encoder](https://github.com/chromium/chromium/blob/3fcfd4c44664cca79c269a09879c864cad6f78c4/media/gpu/mac/vt_video_encode_accelerator_mac.mm)
在 low-latency mode 下刻意不使用 `DataRateLimits`，并记录该组合会导致 bitrate
undershoot；这属于需要真实媒体基线验证的行为风险，不能仅凭 `OSStatus == 0`
判定无影响。

## 已比较的 Apple 接入方式

### 全局修改所有 Apple H.264 encoder

直接修改 upstream encoder，使所有使用 framework 默认 H.264 factory 的调用方都
请求 low-latency mode。优点是应用无需配置；缺点是改变 `UPSTREAM` 行为、影响
iOS/macOS 所有消费者，并需要定义不支持硬件、Simulator 和 profile 差异时的
fallback/failure contract。

### 作为 CastTuning session setting

在共享 schema 增加一个 VideoToolbox-specific、session-scoped Bool，由 macOS
CastTuning encoder wrapper 在创建 session 时传入。非 `UPSTREAM` casting profiles
可默认启用，`UPSTREAM` 保持 exact M150 行为。优点是语义、effective-config hash
和实验可重复性完整；缺点是没有使用 CastTuning factory 的 Apple 调用方不会自动
获得该模式。

采用第二种：它符合本仓库“UPSTREAM 不注入 setter/field trial”的既有 contract，
并允许 fail-closed 地区分“明确要求 low latency”与“允许兼容 fallback”。本轮仅
覆盖已有 CastTuning binding 的 macOS x64/arm64 framework 和 universal
XCFramework；iOS artifact 保持原样，不扩展 iOS binding。

该字段进入 CastTuning schema `2`。新 binary 继续接受 schema `1` 并保留其旧
默认值；只有 schema `2` 接受该字段并让非 `UPSTREAM` profiles 默认启用。这样
同一个 schema `1` 配置不会在新旧 binary 中产生不同编码行为，旧 binary 也会对
schema `2` 明确失败。

Schema `2` 的 low-latency profiles 同时从 Constrained Baseline 切换到
Constrained High level 4.1；Schema `1` 继续使用 Constrained Baseline。调用方仍可
在 schema `2` 中显式请求 Constrained Baseline 作为兼容模式。该选择遵循 Apple 的
公开 contract，并要求 runtime probe 对照 SDP 与 SPS；本机上 Baseline 可工作的经验
不作为跨系统保证。

若出现 SDP/SPS profile mismatch，采用 `WARN_AND_CONTINUE`：每个 encoder session
只记录一次包含 expected/actual profile、encoder ID、session/config hash 的 structured
event，在 telemetry/snapshot 持续标记 `profile_mismatch`，并继续发送 low-latency
bitstream。Binary 不改写 SDP、不自动重建普通 encoder，也不静默关闭 low latency；
需要严格 Baseline 输出的调用方应显式关闭该 setting。

Schema `2` 同时将 low-latency rate control 与 `DataRateLimits` hard window
定义为互斥：low-latency profiles 不再提供 `data_rate_limit_factor/window_ms`
默认值，只通过 `AverageBitRate` 接收 WebRTC/GoogCC 目标；显式组合在 validation
阶段失败。Schema `1` 保留旧行为。

## 验证要求

实现完成不能只检查源码文本或 linked symbol。至少需要：

- common schema/parser/hash/profile tests；
- GitHub Actions 构建并上传 AAR，再使用该 AAR 编译 minimal consumer APK，
  并确认 APK 内含 `arm64-v8a/libjingle_peerconnection_so.so`；
- 发布前从 workflow 下载原始 artifact 到本机，不做本地重打包，并在 arm64
  API 31 emulator 运行 E2E smoke，完成
  `PeerConnectionFactory.initialize()`、factory 创建与 H.264 codec capability
  查询；证据将 workflow run ID、artifact digest 与待发布 AAR SHA-256 绑定，
  同时记录 ABI、API level 和关键日志，且通过验证的 AAR 原字节才可进入
  pre-release；该项只验证 app-consumable package runtime，不扩展为 Android TV
  UI 或端到端投屏测试；
- patched Objective-C encoder options 与 session-creation failure tests；
- macOS arm64/x64 real hosted builds；
- framework/static binary 引用 low-latency key 的 symbol verification；
- 在有真实 VideoToolbox hardware 的 Mac 上运行 1080p H.264 probe，记录
  normal/low-latency session create、Encoder ID、协商 profile、输出 SPS profile
  与 profile mismatch 日志；probe 必须面向最终 arm64 Framework/XCFramework
  slice；x64 只做 hosted build、link/symbol 和 package verification，并显式记录
  缺少 Intel hardware runtime coverage，不能以 hosted-runner VM 代替；
- downstream media baseline 另行比较 encode latency、QP/bitrate 和画质，且不把
  property 设置成功等同于端到端收益。

## 本轮发布边界

本轮不为 unchanged iOS/Windows artifacts 重跑完整 `-all` release。稳定
all-platform contract 保持不变；Android tar/AAR 与 macOS x64/arm64/XCFramework
使用同一新 builder commit 发布为 scoped GitHub pre-release。该 pre-release 不混入
旧 builder commit 的产物、不宣称全平台完成，并在上传后重新下载所有 assets 校验
release manifest 与 SHA-256。macOS 与 Android 使用一个联合 manifest/tag：
`webrtc-m150.7871.3-<builder-short-sha>-YYYYMMDD-macos-android-preview.N`，不拆成
两个平台 release。
