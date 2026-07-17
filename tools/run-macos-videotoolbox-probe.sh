#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "usage: $0 <webrtc-m150-macos-arm64.tar.gz>" >&2
  exit 2
fi
for command in jq shasum tar xcrun lipo sw_vers sysctl; do
  command -v "$command" >/dev/null || {
    echo "required command is unavailable: $command" >&2
    exit 1
  }
done
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "real-hardware probe requires an Apple Silicon Mac" >&2
  exit 1
fi

model="$(sysctl -n hw.model)"
if [[ "$model" =~ (VirtualMac|VMware|Parallels) ]]; then
  echo "virtual Mac hardware is not admissible VideoToolbox evidence: $model" >&2
  exit 1
fi

macos_package="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
if [[ "$(basename "$macos_package")" != "webrtc-m150-macos-arm64.tar.gz" ]]; then
  echo "unexpected macOS package filename: $(basename "$macos_package")" >&2
  exit 2
fi
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
package_sha256="$(shasum -a 256 "$macos_package" | awk '{print $1}')"
evidence_root="${EVIDENCE_DIR:-$PWD/evidence/macos-videotoolbox/$package_sha256}"
mkdir -p "$evidence_root"
work_dir="$(mktemp -d "$evidence_root/work.XXXXXX")"
cleanup() {
  rm -rf "$work_dir"
}
trap cleanup EXIT

if tar -tzf "$macos_package" |
  awk 'BEGIN {bad=0} /^\// || /(^|\/)\.\.($|\/)/ || /\\/ {bad=1} END {exit bad ? 0 : 1}'; then
  echo "macOS package contains an unsafe member path" >&2
  exit 1
fi
mkdir -p "$work_dir/extracted"
tar -xzf "$macos_package" -C "$work_dir/extracted"

frameworks=()
while IFS= read -r framework; do
  frameworks+=("$framework")
done < <(find "$work_dir/extracted" -type d -name WebRTC.framework -print)
if [[ ${#frameworks[@]} -ne 1 ]]; then
  echo "expected exactly one WebRTC.framework in macOS arm64 package" >&2
  exit 1
fi
framework="${frameworks[0]}"
framework_binary="$framework/WebRTC"
if [[ ! -e "$framework_binary" ]]; then
  framework_binary="$framework/Versions/A/WebRTC"
fi
if [[ ! -f "$framework_binary" ]]; then
  echo "WebRTC framework binary is missing" >&2
  exit 1
fi
architectures="$(lipo -archs "$framework_binary")"
if [[ " $architectures " != *" arm64 "* ]]; then
  echo "WebRTC framework does not contain arm64: $architectures" >&2
  exit 1
fi

framework_binary_sha256="$(shasum -a 256 "$framework_binary" | awk '{print $1}')"
probe_binary="$work_dir/videotoolbox-probe"
framework_parent="$(dirname "$framework")"
xcrun clang++ \
  -std=c++17 \
  -fobjc-arc \
  -mmacosx-version-min=14.0 \
  -F "$framework_parent" \
  -framework WebRTC \
  -framework Foundation \
  -framework CoreVideo \
  -framework CoreMedia \
  -framework VideoToolbox \
  -Wl,-rpath,"$framework_parent" \
  "$repo_root/tools/macos-videotoolbox-probe/main.mm" \
  -o "$probe_binary"

raw_output="$evidence_root/probe.ndjson"
probe_log="$evidence_root/probe.log"
DYLD_FRAMEWORK_PATH="$framework_parent" "$probe_binary" \
  2> >(tee "$probe_log" >&2) | tee "$raw_output"
os_version="$(sw_vers -productVersion)"
evidence_path="$evidence_root/evidence.json"
jq -s \
  --arg generated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg artifact_filename "$(basename "$macos_package")" \
  --arg macos_package_sha256 "$package_sha256" \
  --arg framework_binary_sha256 "$framework_binary_sha256" \
  --arg architectures "$architectures" \
  --arg hardware_model "$model" \
  --arg os_version "$os_version" \
  '{
    schema_version: 1,
    generated_at: $generated_at,
    artifact_filename: $artifact_filename,
    macos_package_sha256: $macos_package_sha256,
    framework_binary_sha256: $framework_binary_sha256,
    architectures: ($architectures | split(" ")),
    hardware_model: $hardware_model,
    os_version: $os_version,
    macos_x64_hardware_runtime_verified: false,
    modes: map(select(.mode == "normal" or .mode == "low_latency")),
    hevc_modes: map(select(.codec == "H265"))
  }' "$raw_output" >"$evidence_path"

jq -e '
  (.modes | length == 2) and
  (all(.modes[]; .session_status == "success")) and
  ((.modes | map(select(.mode == "normal"))) | length == 1) and
  ((.modes | map(select(.mode == "low_latency"))) | length == 1) and
  (all(.modes[];
    .encoder_id != "UNKNOWN" and
    .sps_profile != "UNKNOWN" and
    .reported_actual_profile == .sps_profile and
    .reported_expected_profile == .negotiated_profile and
    .reported_profile_mismatch == .profile_mismatch and
    .profile_mismatch == false)) and
  ((.modes[] | select(.mode == "normal") | .runtime_qp) as $runtime_qp |
    ($runtime_qp | map(.requested_max_qp)) == [32, 24, 32] and
    (all($runtime_qp[]; .apply_state == "applied")) and
    (all($runtime_qp[];
      .effective_max_qp == .requested_max_qp and
      .actual_qp >= 0 and
      .actual_qp <= .requested_max_qp)) and
    ([$runtime_qp[].encoder_session_id] | unique | length) == 3 and
    ($runtime_qp[1].actual_qp <= 24)) and
  ((.modes[] | select(.mode == "low_latency") | .encoder_id) | contains(".rtvc"))
  and
  (.hevc_modes | length == 3) and
  (all(.hevc_modes[]; .session_status == "success" and .codec == "H265")) and
  (all(.hevc_modes[];
    .realtime_os_status == 0 and
    .effective_realtime == true and
    .allow_frame_reordering_os_status == 0 and
    .effective_allow_frame_reordering == false)) and
  ((.hevc_modes | map(.mode) | sort) ==
    ["hevc_low_latency", "hevc_spatial_default", "hevc_spatial_disable"]) and
  (all(.hevc_modes[];
    (.runtime_qp | map(.requested_max_qp)) == [32, 22, 32] and
    (all(.runtime_qp[];
      .apply_state == "applied" and
      .effective_max_qp == .requested_max_qp and
      .actual_qp >= 0 and
      .actual_qp <= .requested_max_qp)) and
    ([.runtime_qp[].encoder_session_id] | unique | length) == 3)) and
  (all(.hevc_modes[] | select(.mode != "hevc_low_latency");
    .spatial_event_type == "encoder_spatial_adaptive_qp_applied" and
    .spatial_os_status == 0)) and
  ((.hevc_modes[] | select(.mode == "hevc_spatial_default") |
    .effective_spatial_adaptive_qp_level) == -1) and
  ((.hevc_modes[] | select(.mode == "hevc_spatial_disable") |
    .effective_spatial_adaptive_qp_level) == 0) and
  ((.hevc_modes[] | select(.mode == "hevc_low_latency") | .encoder_id) |
    contains(".rtvc"))
' "$evidence_path" >/dev/null

if jq -e 'any(.modes[]; .profile_mismatch == true)' "$evidence_path" >/dev/null; then
  grep -F 'CastTuning H264 profile evidence' "$probe_log" >/dev/null
fi

echo "$evidence_path"
