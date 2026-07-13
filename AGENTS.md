# 项目协作说明

本项目的 Windows x64 package verifier 曾因错误假设 Chromium Windows clang package 提供 `llvm-lib.exe` 而失败。涉及 Windows archive inspection、`dumpbin`、`vswhere`、COFF architecture 或 static-library symbol validation 时，必须先阅读：

- [Windows package verifier tool probe](docs/windows-verifier-tool-probe-2026-07-13.md)

该记录保存了真实 `windows-latest` runner 的探测结果、失败 probe、可复现命令和当前工具选择约束；不要仅凭本机 macOS 环境推断 Windows toolchain 内容。
