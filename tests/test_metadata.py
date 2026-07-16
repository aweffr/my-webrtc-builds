import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from builder.config import get_target
from builder.metadata import (
    BuildMetadata,
    MetadataError,
    configuration_fingerprint,
    load_metadata,
    release_tag,
    save_metadata,
    validate_compatible,
)


def metadata_for(target: str = "macos-x64") -> BuildMetadata:
    return BuildMetadata.create(
        target=target,
        builder_commit="a" * 40,
        header_manifest="headers-sha256",
        patch_hashes={"h265.patch": "patch-sha256"},
        gn_args={"x64": get_target("macos-x64").gn_args_for("x64")},
        toolchain={"xcode": "26.0.1"},
        overlay_hashes={"api/cast_tuning/config.h": "overlay-sha256"},
        tuning_schema_version=2,
    )


class FingerprintTests(unittest.TestCase):
    def test_configuration_fingerprint_is_deterministic(self) -> None:
        first = configuration_fingerprint(get_target("macos-x64"))
        second = configuration_fingerprint(get_target("macos-x64"))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_target_configuration_changes_fingerprint(self) -> None:
        target = get_target("macos-x64")
        changed = replace(target, deployment_target="15.0")
        self.assertNotEqual(
            configuration_fingerprint(target),
            configuration_fingerprint(changed),
        )


class MetadataTests(unittest.TestCase):
    def test_metadata_round_trip_uses_canonical_json(self) -> None:
        metadata = metadata_for()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "metadata.json")
            save_metadata(path, metadata)
            loaded = load_metadata(path)
            self.assertEqual(loaded, metadata)
            self.assertTrue(path.read_text().endswith("\n"))
            payload = json.loads(path.read_text())
            self.assertEqual(payload["schema_version"], 3)
            self.assertEqual(payload["tuning_schema_version"], 2)
            self.assertEqual(
                payload["snapshot"]["archive_sha256"],
                get_target("macos-x64").snapshot.archive_sha256,
            )
            self.assertEqual(
                payload["overlay_hashes"],
                {"api/cast_tuning/config.h": "overlay-sha256"},
            )

    def test_unknown_schema_is_rejected(self) -> None:
        payload = metadata_for().to_dict()
        payload["schema_version"] = 2
        with self.assertRaisesRegex(MetadataError, "schema version"):
            BuildMetadata.from_dict(payload)

    def test_snapshot_provenance_is_required_and_must_match_target(self) -> None:
        payload = metadata_for("android").to_dict()
        payload.pop("snapshot")
        with self.assertRaisesRegex(MetadataError, "snapshot"):
            BuildMetadata.from_dict(payload)

        payload = metadata_for("android").to_dict()
        payload["snapshot"]["archive_sha256"] = "0" * 64
        with self.assertRaisesRegex(MetadataError, "snapshot"):
            BuildMetadata.from_dict(payload)

    def test_legacy_tuning_schema_is_rejected_for_new_artifacts(self) -> None:
        payload = metadata_for().to_dict()
        payload["tuning_schema_version"] = 1
        with self.assertRaisesRegex(MetadataError, "tuning_schema_version"):
            BuildMetadata.from_dict(payload)

    def test_mixed_source_or_builder_commit_is_rejected(self) -> None:
        first = metadata_for("macos-x64")
        second = metadata_for("macos-arm64")
        validate_compatible((first, second))

        with self.assertRaisesRegex(MetadataError, "builder commit"):
            validate_compatible((first, replace(second, builder_commit="b" * 40)))

        changed_source = dict(second.source)
        changed_source["commit"] = "b" * 40
        with self.assertRaisesRegex(MetadataError, "source"):
            validate_compatible((first, replace(second, source=changed_source)))

    def test_mixed_headers_are_rejected_for_macos_merge(self) -> None:
        first = metadata_for("macos-x64")
        second = replace(metadata_for("macos-arm64"), header_manifest="different")
        with self.assertRaisesRegex(MetadataError, "header manifest"):
            validate_compatible((first, second), require_same_headers=True)

    def test_mixed_overlays_are_rejected_for_macos_merge(self) -> None:
        first = metadata_for("macos-x64")
        second = replace(
            metadata_for("macos-arm64"),
            overlay_hashes={"api/cast_tuning/config.h": "different"},
        )
        with self.assertRaisesRegex(MetadataError, "overlay manifest"):
            validate_compatible((first, second), require_same_headers=True)

    def test_platform_specific_patch_sets_are_allowed_for_release(self) -> None:
        first = metadata_for("android")
        second = replace(
            metadata_for("ios"),
            patch_hashes={"h265_ios.patch": "apple-patch"},
        )
        validate_compatible((first, second))

        with self.assertRaisesRegex(MetadataError, "patch set"):
            validate_compatible((first, second), require_same_patches=True)

    def test_metadata_target_must_be_known(self) -> None:
        payload = metadata_for().to_dict()
        payload["target"] = "linux"
        with self.assertRaisesRegex(MetadataError, "target"):
            BuildMetadata.from_dict(payload)


class ReleaseTagTests(unittest.TestCase):
    def test_release_tag_includes_version_short_commit_date_and_platform(self) -> None:
        self.assertEqual(
            release_tag("0565ce035a0ace92163200355d6ed75c7eec14a2", "20260712", "all"),
            "webrtc-m150.7871.3-0565ce0-20260712-all",
        )

    def test_invalid_release_tag_fields_are_rejected(self) -> None:
        for builder_commit, date, platform in (
            ("short", "20260712", "all"),
            ("a" * 40, "20261312", "all"),
            ("a" * 40, "20260712", "macos arm64"),
        ):
            with self.subTest(builder_commit=builder_commit, date=date, platform=platform):
                with self.assertRaises(ValueError):
                    release_tag(builder_commit, date, platform)


if __name__ == "__main__":
    unittest.main()
