# 项目协作说明

本项目的 Windows x64 package verifier 曾因错误假设 Chromium Windows clang package 提供 `llvm-lib.exe` 而失败。涉及 Windows archive inspection、`dumpbin`、`vswhere`、COFF architecture 或 static-library symbol validation 时，必须先阅读：

- [Windows package verifier tool probe](docs/windows-verifier-tool-probe-2026-07-13.md)

该记录保存了真实 `windows-latest` runner 的探测结果、失败 probe、可复现命令和当前工具选择约束；不要仅凭本机 macOS 环境推断 Windows toolchain 内容。

## 经验教训

### 跨平台 patch 边界与验证

修改多个平台共用的 patch 时，必须保证 patch 中修改的每个文件都存在于所有使用它的平台源码中。只属于 macOS、Android、iOS 或 Windows 的修改，应放在独立的平台 patch 中，并且只应用于对应平台。修改完成后，必须在每个受影响平台的 source snapshot 上检查完整 patch chain 能否成功应用；只验证部分文件或只验证一个平台不算完成。
