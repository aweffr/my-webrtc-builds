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

`android_java8.patch` is maintained by this project. M150 pins Chromium build
revision `d296a9fec6186f2c109758c7d3f93cbef936dfc3`, whose Android Java compiler
and Turbine wrapper target Java 21. The public M150 Android source closure uses
Java 8 language features except for three Java 10 local-variable `var` usages.
The patch changes those local variables to their explicit types and changes
both matching `--release` values to Java 8. The resulting public
`webrtc.jar`/AAR contract is classfile major 52; the JDK used to run a consumer's
Android Gradle Plugin remains a separate concern. The exact inspected sources
are
[`compile_java.py`](https://chromium.googlesource.com/chromium/src/build/+/d296a9fec6186f2c109758c7d3f93cbef936dfc3/android/gyp/compile_java.py)
(`543f5ce3c37cfc599d4a7d7a09b5fda04657c879a68c1673924a60961507a4ac`) and
[`turbine.py`](https://chromium.googlesource.com/chromium/src/build/+/d296a9fec6186f2c109758c7d3f93cbef936dfc3/android/gyp/turbine.py)
(`21ddf67fc8a68faec646c30e3069f8f1fa60f186f32d571b82125c495376555e`),
[`EglRenderer.java`](https://webrtc.googlesource.com/src/+/1f975dfd761af6e5d76d28333191973b258d82a8/sdk/android/api/org/webrtc/EglRenderer.java)
(`3d4721a546db219917283d86ef0567b6d28b647c230aa95039f2a087e9912d87`),
[`NetworkMonitorAutoDetect.java`](https://webrtc.googlesource.com/src/+/1f975dfd761af6e5d76d28333191973b258d82a8/sdk/android/api/org/webrtc/NetworkMonitorAutoDetect.java)
(`4bd82c6314050f43f43591eeead7f74b6eb611b70a9b007b554e47ce9b40b7c2`),
and
[`CommonApis.java`](https://chromium.googlesource.com/chromium/src/third_party/+/7c92732938de0ef7e28f5da231994723f938f407/jni_zero/java/src/org/jni_zero/CommonApis.java)
(`ab105e273deddaa1601b75b5f2c22d62ff890dd94f42dc57e0a20ba3898e8100`).

| File | SHA-256 |
| --- | --- |
| `add_deps.patch` | `835b09d756f9dc3cbf2286476d654b08c82fbcc141a40f15ecf6145d789d272b` |
| `windows_add_deps.patch` | `1877878571707079ec53989e5f17b9585f106cc6935908104c2245ec89a15104` |
| `h265.patch` | `5c1e1d169e59050722b5e329a47bbea889f8194e099b175703fda32c1b36b2e7` |
| `h265_android.patch` | `9598c581d937fc9e15c34eafa6d42f707e40df65999453cdd8e7659d29eb7d8e` |
| `h265_ios.patch` | `13cb55f38774a6312ca0b965779f8c48e581d23ae31680e813f7418966c5482a` |
| `codec_licenses.patch` | `96766489dd4f6fb5cf2db77befcf53863c7a5431c5995d6658ff846a78baf71b` |
| `macos_h265_framework.patch` | `948a39aad68e4d579bb948ca05fcbcdf40bbe1bfccb4f42419754982fe870ff4` |
| `android_java8.patch` | `81b32c48a6c3df3de581d2344cbc897236bc927c327b4db7478cbda49fee722b` |

`cast_tuning_hooks.patch` is authored by this project under Apache-2.0. It
contains only the M150 GN wiring and source hooks required by the versioned
`overlays/m150` CastTuning shim.

| Project patch | SHA-256 |
| --- | --- |
| `cast_tuning_hooks.patch` | `5c5bbdfb1ccff2886afb824c8a7438356d8f36de78cf88e1a362bd5888e1b5ec` |
