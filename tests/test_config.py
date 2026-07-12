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
    def test_exact_supported_target_set(self) -> None:
        self.assertEqual(
            set(TARGETS),
            {"android", "ios", "macos-x64", "macos-arm64"},
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

    def test_macos_bundles_software_h264_while_mobile_does_not(self) -> None:
        for name in ("macos-x64", "macos-arm64"):
            args = get_target(name).gn_args_for(get_target(name).architectures[0])
            self.assertIn("rtc_use_h264=true", args)
            self.assertIn("rtc_system_openh264=false", args)
            self.assertIn('ffmpeg_branding="Chrome"', args)
            self.assertIn("rtc_use_h265=true", args)

        for name in ("android", "ios"):
            args = get_target(name).gn_args_for(get_target(name).architectures[0])
            self.assertIn("rtc_use_h264=false", args)
            self.assertIn("rtc_use_h265=true", args)

    def test_macos_applies_codec_license_mapping_patch(self) -> None:
        self.assertIn("codec_licenses.patch", get_target("macos-x64").patches)
        self.assertIn("codec_licenses.patch", get_target("macos-arm64").patches)
        self.assertNotIn("codec_licenses.patch", get_target("android").patches)
        self.assertNotIn("codec_licenses.patch", get_target("ios").patches)

    def test_unknown_target_is_rejected(self) -> None:
        with self.assertRaisesRegex(UnknownTargetError, "unsupported target"):
            get_target("linux")


if __name__ == "__main__":
    unittest.main()
