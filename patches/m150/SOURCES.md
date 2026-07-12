# M150 patch sources

These files originate from
[`shiguredo-webrtc-build/webrtc-build` tag `m150.7871.3.0`](https://github.com/shiguredo-webrtc-build/webrtc-build/tree/m150.7871.3.0/patches).
They retain the upstream repository's Apache-2.0 license and any per-file
notices embedded in added source files.

`h265_ios.patch` omits the hunk for
`RTCVideoEncoderFactorySimulcast.mm` because that file is introduced by
Shiguredo's separate `ios_simulcast.patch`, which is intentionally outside this
project's scope. All other approved patch content is unchanged.

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

| File | SHA-256 |
| --- | --- |
| `add_deps.patch` | `835b09d756f9dc3cbf2286476d654b08c82fbcc141a40f15ecf6145d789d272b` |
| `h265.patch` | `5c1e1d169e59050722b5e329a47bbea889f8194e099b175703fda32c1b36b2e7` |
| `h265_android.patch` | `9598c581d937fc9e15c34eafa6d42f707e40df65999453cdd8e7659d29eb7d8e` |
| `h265_ios.patch` | `13cb55f38774a6312ca0b965779f8c48e581d23ae31680e813f7418966c5482a` |
| `codec_licenses.patch` | `96766489dd4f6fb5cf2db77befcf53863c7a5431c5995d6658ff846a78baf71b` |
| `macos_h265_framework.patch` | `948a39aad68e4d579bb948ca05fcbcdf40bbe1bfccb4f42419754982fe870ff4` |
