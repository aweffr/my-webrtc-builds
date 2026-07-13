# Windows package verifier tool probe

日期：2026-07-13

## 背景

Windows x64 build run [29219659614](https://github.com/aweffr/my-webrtc-builds/actions/runs/29219659614) 已完成 source preparation、GN、Ninja、static archive 和 native CastTuning tests，但在 package 阶段失败：

```text
third_party/llvm-build/Release+Asserts/bin/llvm-lib.exe /list stage/windows-x64/webrtc/lib/webrtc.lib
FileNotFoundError: [WinError 2]
```

失败原因不是 `webrtc.lib` 缺失。诊断产物显示 archive 已存在；缺失的是 verifier 假定存在的 `llvm-lib.exe`。

## Disposable probe

为避免再次消耗完整 WebRTC 编译时间，临时 workflow `Probe Windows verifier tools` 只在 `windows-latest` runner 上执行工具发现和最小 COFF archive 实验。临时 workflow 已在 probe 完成后从 `main` 和远端 probe branch 删除。

- 首次 probe [29223027187](https://github.com/aweffr/my-webrtc-builds/actions/runs/29223027187)：probe 源码漏加 `/std:c++17`，失败属于 probe 自身错误。
- 修正后的 probe [29223117244](https://github.com/aweffr/my-webrtc-builds/actions/runs/29223117244)：成功。

## 实测事实

1. `vswhere.exe` 在 PATH 中，但 `dumpbin.exe`、`lib.exe`、`cl.exe` 不在 PATH；`lld-link.exe` 在 `C:\Program Files\LLVM\bin\lld-link.exe`。
2. `vswhere -find **/dumpbin.exe` 会扫描约 40 秒，并返回多个 SDK/toolset 版本；不能无条件取这个宽 glob 的第一个结果。
3. `vswhere -find **/Hostx64/x64/dumpbin.exe` 约 1 秒返回可用于 x64 archive 检查的工具路径。
4. 用 `cl.exe` 和 `lib.exe` 生成最小 x64 `probe.lib` 后，`dumpbin /headers probe.lib` 输出：

   ```text
   File Type: LIBRARY
   FILE HEADER VALUES
               8664 machine (x64)
   ```

5. `dumpbin /linkermember:2 probe.lib` 输出 public symbols；实验中包含：

   ```text
   H264DecoderImpl
   H264EncoderImpl
   ?run@CastTuningController@cast_tuning@webrtc@@SAXXZ
   ```

   MSVC names 是 decorated symbols，因此 namespace 不会以 `webrtc::cast_tuning::` 的 demangled 形式出现，但会保留 `CastTuningController` 和 namespace fragments。

## 代码决策

Windows verifier 使用 Visual Studio 的 `dumpbin.exe`：

- 由 `vswhere` 精确解析 `**/Hostx64/x64/dumpbin.exe`；
- `/headers` 验证输出非空且为 AMD64 COFF（`8664 machine (x64)`）；
- `/linkermember:2` 验证 H264 和 CastTuning public symbol fragments；
- 不再调用 Chromium Windows clang package 中不存在的 `llvm-lib.exe`、`llvm-readobj.exe` 或 `llvm-nm.exe`。

`dumpbin` 对 COFF object、standard library 和其他 COFF binary 的支持见 [Microsoft DUMPBIN reference](https://learn.microsoft.com/en-us/cpp/build/reference/dumpbin-reference?view=msvc-170)；`/LINKERMEMBER:2` 的语义见 [Microsoft /LINKERMEMBER reference](https://learn.microsoft.com/en-us/cpp/build/reference/linkermember?view=msvc-170)。

## 后续排障规则

- 看到 Windows package verifier 的 `WinError 2` 时，先区分“archive 缺失”和“inspection tool 缺失”。
- 不要假设 Chromium `third_party/llvm-build/Release+Asserts/bin` 在 Windows 包含 Linux/macOS 分支中的 `llvm-ar`、`llvm-readobj`、`llvm-nm` 等工具。
- 若需要重新验证 runner 工具，优先复用最小 COFF probe，不要先重新执行完整 WebRTC build。
