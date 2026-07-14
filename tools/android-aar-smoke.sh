#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^[0-9]+$ ]]; then
  echo "usage: $0 <successful-build-android-run-id>" >&2
  exit 2
fi

run_id="$1"
artifact_name="webrtc-m150-android-arm64-v8a"
avd_name="${ANDROID_AVD_NAME:-Pixel_6_API_31}"
android_home="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_HOME="$android_home"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

for command in gh jq adb emulator shasum unzip; do
  command -v "$command" >/dev/null || {
    echo "required command is unavailable: $command" >&2
    exit 1
  }
done

repository="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
evidence_root="${EVIDENCE_DIR:-$PWD/evidence/android-aar/$run_id}"
download_dir="$evidence_root/download"
logcat_path="$evidence_root/logcat.txt"
evidence_path="$evidence_root/evidence.json"
mkdir -p "$evidence_root"
rm -rf "$download_dir"
mkdir -p "$download_dir"

run_json="$(gh api "repos/$repository/actions/runs/$run_id")"
if [[ "$(jq -r .conclusion <<<"$run_json")" != "success" ]]; then
  echo "workflow run $run_id is not successful" >&2
  exit 1
fi
builder_commit="$(jq -r .head_sha <<<"$run_json")"

artifact_json="$(
  gh api --paginate "repos/$repository/actions/runs/$run_id/artifacts" |
    jq -s --arg name "$artifact_name" \
      '[.[].artifacts[] | select(.name == $name)] | if length == 1 then .[0] else error("artifact count must be one") end'
)"
artifact_digest="$(jq -r '.digest // "unavailable"' <<<"$artifact_json")"
if [[ ! "$artifact_digest" =~ ^sha256:[0-9a-fA-F]{64}$ ]]; then
  echo "workflow artifact has no usable SHA-256 digest" >&2
  exit 1
fi

gh run download "$run_id" \
  --repo "$repository" \
  --name "$artifact_name" \
  --dir "$download_dir"

find_one() {
  local filename="$1"
  local -a matches=()
  while IFS= read -r match; do
    matches+=("$match")
  done < <(find "$download_dir" -type f -name "$filename" -print)
  if [[ ${#matches[@]} -ne 1 ]]; then
    echo "expected exactly one $filename in downloaded artifact" >&2
    exit 1
  fi
  printf '%s\n' "${matches[0]}"
}

aar="$(find_one webrtc-m150-android-arm64-v8a.aar)"
apk="$(find_one app-debug.apk)"
hosted_checksums="$(find_one android-artifact-sha256.txt)"
aar_sha256="$(shasum -a 256 "$aar" | awk '{print $1}')"
apk_sha256="$(shasum -a 256 "$apk" | awk '{print $1}')"
expected_aar_sha256="$(awk '/webrtc-m150-android-arm64-v8a[.]aar$/ {print $1}' "$hosted_checksums")"
expected_apk_sha256="$(awk '/app-debug[.]apk$/ {print $1}' "$hosted_checksums")"
if [[ "$aar_sha256" != "$expected_aar_sha256" || "$apk_sha256" != "$expected_apk_sha256" ]]; then
  echo "downloaded AAR/APK differs from hosted checksum evidence" >&2
  exit 1
fi
unzip -Z1 "$aar" | grep -Fx "jni/arm64-v8a/libjingle_peerconnection_so.so" >/dev/null
unzip -Z1 "$apk" | grep -Fx "lib/arm64-v8a/libjingle_peerconnection_so.so" >/dev/null

started_emulator=false
emulator_pid=""
cleanup() {
  if [[ "$started_emulator" == true ]]; then
    adb -s "${serial:-emulator-5554}" emu kill >/dev/null 2>&1 || true
    if [[ -n "$emulator_pid" ]]; then
      wait "$emulator_pid" 2>/dev/null || true
    fi
  fi
}
trap cleanup EXIT

serial="$(adb devices | awk '$1 ~ /^emulator-/ && $2 == "device" {print $1; exit}')"
if [[ -z "$serial" ]]; then
  emulator "@$avd_name" \
    -no-window \
    -no-audio \
    -no-boot-anim \
    -gpu swiftshader_indirect \
    >"$evidence_root/emulator.log" 2>&1 &
  emulator_pid="$!"
  started_emulator=true
  serial="emulator-5554"
fi

adb -s "$serial" wait-for-device
boot_completed=""
for _ in $(seq 1 180); do
  boot_completed="$(adb -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
  [[ "$boot_completed" == "1" ]] && break
  sleep 1
done
if [[ "$boot_completed" != "1" ]]; then
  echo "Android emulator did not finish booting" >&2
  exit 1
fi

api_level="$(adb -s "$serial" shell getprop ro.build.version.sdk | tr -d '\r')"
abi="$(adb -s "$serial" shell getprop ro.product.cpu.abi | tr -d '\r')"
if [[ "$api_level" != "31" || "$abi" != "arm64-v8a" ]]; then
  echo "unexpected emulator identity: API $api_level, ABI $abi" >&2
  exit 1
fi

adb -s "$serial" install -r "$apk" >/dev/null
adb -s "$serial" shell am force-stop dev.aweffr.webrtcsmoke
adb -s "$serial" logcat -c
adb -s "$serial" shell am start -W \
  -n dev.aweffr.webrtcsmoke/.MainActivity >/dev/null

smoke_ok=false
for _ in $(seq 1 60); do
  adb -s "$serial" logcat -d -v threadtime \
    WebRTCAarSmoke:I AndroidRuntime:E '*:S' >"$logcat_path"
  if grep -F "AAR_SMOKE_OK" "$logcat_path" >/dev/null; then
    smoke_ok=true
    break
  fi
  if grep -F "AAR_SMOKE_FAILED" "$logcat_path" >/dev/null; then
    break
  fi
  sleep 1
done
if [[ "$smoke_ok" != true ]]; then
  echo "AAR runtime smoke did not produce AAR_SMOKE_OK" >&2
  cat "$logcat_path" >&2
  exit 1
fi

logcat_sha256="$(shasum -a 256 "$logcat_path" | awk '{print $1}')"
generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
jq -n \
  --arg schema_version "1" \
  --arg generated_at "$generated_at" \
  --arg repository "$repository" \
  --arg run_id "$run_id" \
  --arg builder_commit "$builder_commit" \
  --arg artifact_name "$artifact_name" \
  --arg artifact_digest "$artifact_digest" \
  --arg aar_sha256 "$aar_sha256" \
  --arg apk_sha256 "$apk_sha256" \
  --arg avd_name "$avd_name" \
  --arg serial "$serial" \
  --arg api_level "$api_level" \
  --arg abi "$abi" \
  --arg logcat_sha256 "$logcat_sha256" \
  '{
    schema_version: ($schema_version | tonumber),
    generated_at: $generated_at,
    repository: $repository,
    workflow_run_id: ($run_id | tonumber),
    builder_commit: $builder_commit,
    artifact_name: $artifact_name,
    artifact_digest: $artifact_digest,
    aar_sha256: $aar_sha256,
    apk_sha256: $apk_sha256,
    avd_name: $avd_name,
    emulator_serial: $serial,
    android_api_level: ($api_level | tonumber),
    abi: $abi,
    marker: "AAR_SMOKE_OK",
    logcat_sha256: $logcat_sha256
  }' >"$evidence_path"

echo "$evidence_path"
