# M150 patch sources

These files originate from
[`shiguredo-webrtc-build/webrtc-build` tag `m150.7871.3.0`](https://github.com/shiguredo-webrtc-build/webrtc-build/tree/m150.7871.3.0/patches).
They retain the upstream repository's Apache-2.0 license and any per-file
notices embedded in added source files.

`h265_ios.patch` omits the hunk for
`RTCVideoEncoderFactorySimulcast.mm` because that file is introduced by
Shiguredo's separate `ios_simulcast.patch`, which is intentionally outside this
project's scope. All other approved patch content is unchanged.

`windows_add_deps.patch` retains Shiguredo's dependency additions, with hunk
context adjusted to apply to this project's pinned M150 source commit.

`codec_licenses.patch` is maintained by this project. It extends M150's
license generator with the pinned FFmpeg LGPL 2.1 text and Cisco OpenH264
license after those dependencies are introduced by the codec patches. It does
not change codec behavior.

`macos_h265_framework.patch` is maintained by this project. The Shiguredo H.265
patch wires the codec implementation into the shared Apple targets but adds
the public H.265 headers only to the iOS framework target. This small follow-up
adds the same headers to M150's macOS framework target and fixes the M150 macOS
framework template so its generated public headers are copied beside the
umbrella header.

`android_java17.patch` is maintained by this project. M150 pins Chromium build
revision `d296a9fec6186f2c109758c7d3f93cbef936dfc3`, whose Android Java compiler
and Turbine wrapper target Java 21. The patch changes both matching `--release`
values to Java 17 so the public `webrtc.jar`/AAR can be consumed by the
repository's documented JDK 17 Android toolchain. The exact inspected sources
are
[`compile_java.py`](https://chromium.googlesource.com/chromium/src/build/+/d296a9fec6186f2c109758c7d3f93cbef936dfc3/android/gyp/compile_java.py)
(`543f5ce3c37cfc599d4a7d7a09b5fda04657c879a68c1673924a60961507a4ac`) and
[`turbine.py`](https://chromium.googlesource.com/chromium/src/build/+/d296a9fec6186f2c109758c7d3f93cbef936dfc3/android/gyp/turbine.py)
(`21ddf67fc8a68faec646c30e3069f8f1fa60f186f32d571b82125c495376555e`).

| File | SHA-256 |
| --- | --- |
| `add_deps.patch` | `835b09d756f9dc3cbf2286476d654b08c82fbcc141a40f15ecf6145d789d272b` |
| `windows_add_deps.patch` | `1877878571707079ec53989e5f17b9585f106cc6935908104c2245ec89a15104` |
| `h265.patch` | `5c1e1d169e59050722b5e329a47bbea889f8194e099b175703fda32c1b36b2e7` |
| `h265_android.patch` | `9598c581d937fc9e15c34eafa6d42f707e40df65999453cdd8e7659d29eb7d8e` |
| `h265_ios.patch` | `13cb55f38774a6312ca0b965779f8c48e581d23ae31680e813f7418966c5482a` |
| `codec_licenses.patch` | `96766489dd4f6fb5cf2db77befcf53863c7a5431c5995d6658ff846a78baf71b` |
| `macos_h265_framework.patch` | `948a39aad68e4d579bb948ca05fcbcdf40bbe1bfccb4f42419754982fe870ff4` |
| `android_java17.patch` | `5f058d9a482d4c5fbee77425dad501c4e6bf699128cc54e2b9b26ca230aadfd6` |

`cast_tuning_hooks.patch` is authored by this project under Apache-2.0. It
contains only the M150 GN wiring and source hooks required by the versioned
`overlays/m150` CastTuning shim.

| Project patch | SHA-256 |
| --- | --- |
| `cast_tuning_hooks.patch` | `5c5bbdfb1ccff2886afb824c8a7438356d8f36de78cf88e1a362bd5888e1b5ec` |
