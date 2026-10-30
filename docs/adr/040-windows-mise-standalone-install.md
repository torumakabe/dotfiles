# ADR-040: Windows の mise は公式 standalone installer で直接導入する

## Status

Accepted

## Context

[ADR-028](028-mise-bootstrap-preserves-existing-installations.md) は Windows の WinGet 導入を維持し、[ADR-032](032-protect-self-updated-winget-packages-with-blocking-pins.md) は自己更新と blocking pin を採用した。WinGet catalog の反映待ちを避け、WinGet の管理情報と実体を自己更新で不整合にしないため、Windows の mise を直接導入へ変更する。

[公式導入資料](https://mise.jdx.dev/installing-mise.html) は Windows 向け PowerShell installer を提供し、[self-update](https://mise.jdx.dev/cli/self-update.html) は mise 本体を更新できる。本 ADR は ADR-028 の Windows の WinGet 維持方針と、ADR-032 の Windows の mise 更新および pin 方針だけを置換する。

## Decision

- Windows bootstrap は、release tag と SHA-256 を固定した[公式 standalone installer の install.ps1](https://raw.githubusercontent.com/jdx/mise/v2026.10.23/packaging/standalone/install.ps1) を検証して使用し、`~/.local/bin/mise.exe` と `mise-shim.exe` を配置する。
- 有効な既存の直接導入版は版を問わず保持する。既存の直接導入実体が破損している場合は失敗とし、自動置換しない。
- 日常更新は全 OS で `mise-self-update` から `mise self-update --yes --no-plugins` を実行し、成功後に `mise reshim` を行う。WinGet 管理下の自己更新保護は解除しない。
- Windows DSC は mise の導入と pin を管理しない。旧 WinGet 版からの移行は完了し、pin 解除、旧版警告、WinGet 実体の探索 fallback は残さない。
- mise は直接導入に一本化する。config、lockfile、installs は維持し、bootstrap で自動 force uninstall や自動削除は行わない。
- CopilotApp、Copilot、Rustup など他のパッケージの pin 方針と、macOS、Linux、WSL の bootstrap 方針は変更しない。

## Consequences

- Windows の mise 本体を WinGet catalog の反映待ちなく更新でき、日常更新の操作と方式を全 OS で統一できる。
- mise の設定と導入済みツールを保持し、WinGet の管理情報と実体を自己更新で不整合にしない。
