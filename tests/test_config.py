import unittest

from builder.config import SOURCE_VERSION, TARGETS, UnknownTargetError, get_target


class SourceVersionTests(unittest.TestCase):
    def test_m150_source_is_immutable_and_exact(self) -> None:
        self.assertEqual(SOURCE_VERSION.milestone, 150)
        self.assertEqual(SOURCE_VERSION.branch_head, 7871)
        self.assertEqual(SOURCE_VERSION.commit_position, 3)
        self.assertEqual(
            SOURCE_VERSION.commit,
            "1f975dfd761af6e5d76d28333191973b258d82a8",
        )
        self.assertEqual(SOURCE_VERSION.release_base, "m150.7871.3")


class TargetConfigTests(unittest.TestCase):
    def test_each_target_pins_complete_source_snapshot_contract(self) -> None:
        expected = {
            "android": (
                "m150.7871.3-source-poc1",
                "c41249db84fbdbb0c3ac96fbf25553dda4f50b3ac3d685213245d0ca6dadda4c",
                "296bc53ec884627d0b73953b6ed46451d04271af1aec89cd999c110cc987ed39",
                5,
            ),
            "ios": (
                "m150.7871.3-source-poc1",
                "1e6dc50a6d96b0801650aa08c01c06ff7f71c28dd58ce812f3a7b03edee20a59",
                "ad37db58fbdba7f6d98b8081376944df7b12e82fe433646a639bbb6a517c7ac1",
                2,
            ),
            "macos-x64": (
                "m150.7871.3-source-poc1",
                "79ea1e952d79f1d4b99f1bd2447757b33806995bffcabf84b63e632d8ec7b0ab",
                "a7924bc6aec1d396bb4d0b293e70d9363b1195c6605f1d2eddfab68d0a6d9ef5",
                2,
            ),
            "macos-arm64": (
                "m150.7871.3-source-poc1",
                "ffedc6bc27c66d7c83d683829ae37a31b17050983e9af801a0c96d1fd8de842c",
                "66fbda6adb79a6fb9dc4c204611ab78f028a71745ae212c7437cb2c5b700543e",
                2,
            ),
            "windows-x64": (
                "m150.7871.3-source-windows-x64",
                "4a5e8f2dbb25cce3ed884c03f28422a609e87cb4b87f0e5ddfcd94926c11db50",
                "95062aa7044e0343edf08d2b869133e9e748ee3b5c1dad8a26ae109d89d445d1",
                2,
            ),
        }

        for target_name, contract in expected.items():
            release_tag, manifest_sha256, archive_sha256, part_count = contract
            snapshot = get_target(target_name).snapshot
            with self.subTest(target=target_name):
                self.assertEqual(snapshot.repository, "aweffr/webrtc-source-snapshots")
                self.assertEqual(snapshot.release_tag, release_tag)
                self.assertEqual(snapshot.manifest_sha256, manifest_sha256)
                self.assertEqual(snapshot.archive_sha256, archive_sha256)
                self.assertEqual(len(snapshot.parts), part_count)
                self.assertEqual(
                    snapshot.archive_size_bytes,
                    sum(part.size_bytes for part in snapshot.parts),
                )
                self.assertTrue(all(len(part.sha256) == 64 for part in snapshot.parts))

    def test_exact_supported_target_set(self) -> None:
        self.assertEqual(
            set(TARGETS),
            {"android", "ios", "macos-x64", "macos-arm64", "windows-x64"},
        )

    def test_platform_runner_and_architecture_contract(self) -> None:
        android = get_target("android")
        self.assertEqual(android.runner, "ubuntu-24.04")
        self.assertEqual(android.architectures, ("arm64-v8a",))

        ios = get_target("ios")
        self.assertEqual(ios.runner, "macos-26")
        self.assertEqual(ios.architectures, ("device:arm64", "simulator:arm64"))
        self.assertEqual(ios.deployment_target, "14.0")

        mac_x64 = get_target("macos-x64")
        self.assertEqual(mac_x64.runner, "macos-26-intel")
        self.assertEqual(mac_x64.architectures, ("x64",))
        self.assertEqual(mac_x64.deployment_target, "14.0")

        mac_arm64 = get_target("macos-arm64")
        self.assertEqual(mac_arm64.runner, "macos-26")
        self.assertEqual(mac_arm64.architectures, ("arm64",))

        windows = get_target("windows-x64")
        self.assertEqual(windows.runner, "windows-2022")
        self.assertEqual(windows.architectures, ("x64",))

    def test_cast_tuning_is_overlaid_for_windows_macos_and_android(self) -> None:
        android = get_target("android")
        self.assertEqual(android.overlays, ("common", "android"))
        self.assertIn("android_java8.patch", android.patches)
        self.assertEqual(android.patches[-1], "cast_tuning_hooks.patch")
        self.assertEqual(
            android.validation_targets,
            ("api/cast_tuning:cast_tuning_native_tests",),
        )

        for name in ("macos-x64", "macos-arm64"):
            target = get_target(name)
            self.assertEqual(target.overlays, ("common", "macos"))
            self.assertEqual(target.patches[-2:], (
                "cast_tuning_hooks.patch",
                "macos_hevc_cast_tuning.patch",
            ))
            self.assertEqual(
                target.validation_targets,
                ("api/cast_tuning:cast_tuning_native_tests",),
            )

        windows = get_target("windows-x64")
        self.assertEqual(windows.overlays, ("common",))
        self.assertEqual(windows.patches[-1], "cast_tuning_hooks.patch")
        self.assertEqual(
            windows.validation_targets,
            ("api/cast_tuning:cast_tuning_native_tests",),
        )

        self.assertEqual(get_target("ios").overlays, ())
        self.assertEqual(get_target("ios").validation_targets, ())
        self.assertNotIn("cast_tuning_hooks.patch", get_target("ios").patches)

    def test_macos_bundles_software_h264_while_mobile_does_not(self) -> None:
        for name in ("macos-x64", "macos-arm64", "windows-x64"):
            args = get_target(name).gn_args_for(get_target(name).architectures[0])
            self.assertIn("rtc_use_h264=true", args)
            self.assertIn("rtc_system_openh264=false", args)
            self.assertIn('ffmpeg_branding="Chrome"', args)
            self.assertIn("rtc_use_h265=true", args)
            if name.startswith("macos"):
                self.assertIn("rtc_enable_objc_symbol_export=true", args)

        for name in ("android", "ios"):
            args = get_target(name).gn_args_for(get_target(name).architectures[0])
            self.assertIn("rtc_use_h264=false", args)
            self.assertIn("rtc_use_h265=true", args)

    def test_macos_applies_codec_license_mapping_patch(self) -> None:
        self.assertIn("codec_licenses.patch", get_target("macos-x64").patches)
        self.assertIn("codec_licenses.patch", get_target("macos-arm64").patches)
        self.assertIn("macos_h265_framework.patch", get_target("macos-x64").patches)
        self.assertIn("macos_h265_framework.patch", get_target("macos-arm64").patches)
        self.assertNotIn("codec_licenses.patch", get_target("android").patches)
        self.assertNotIn("codec_licenses.patch", get_target("ios").patches)

    def test_windows_uses_windows_dependency_patch_and_root_library(self) -> None:
        target = get_target("windows-x64")
        self.assertIn("windows_add_deps.patch", target.patches)
        self.assertNotIn("add_deps.patch", target.patches)
        self.assertEqual(target.ninja_targets, (":default",))

    def test_unknown_target_is_rejected(self) -> None:
        with self.assertRaisesRegex(UnknownTargetError, "unsupported target"):
            get_target("linux")


if __name__ == "__main__":
    unittest.main()
