# ADR-033: azd と Copilot CLI を OS 別の公式経路で管理する

## Status

Accepted

## Context

ADR-004 は両 CLI を mise 外へ出したが、macOS の Copilot CLI を Homebrew と `copilot update` の双方が更新し得た。初期導入元と日常更新の責務を分離するため、本 ADR で ADR-004 を置き換える。

## Decision

- `azd` と Copilot CLI は mise の管理対象にしない。
- macOS の Copilot CLI は固定した公式リリースアーカイブを SHA-256 検証し、`~/.local/bin/copilot` に配置する。日常更新は `copilot update` に一本化する。
- 既存の Homebrew formula は、公式バイナリの配置と実行確認後に削除する。
- Windows の Copilot CLI は WinGet で導入し、更新競合は ADR-032 に従う。Linux は固定した公式リリースアーカイブを SHA-256 検証して導入する。
- `azd` は macOS では Homebrew、Windows では WinGet、Linux では固定した公式 `.deb` を SHA-256 検証して導入する。`azd update` は macOS で Homebrew に委譲する。
- macOS の mise は ADR-028 に従い、新規環境だけ公式アーカイブから導入し、既存導入を置換しない。rustup は ADR-016 に従い公式 installer で導入する。

## Consequences

- macOS の Copilot CLI は Homebrew と自己更新が同じ実体を競合して更新しない。
- 初期導入は再現可能な固定成果物、日常更新は公式 CLI の updater という責務分離になる。
- macOS の azd、既存 mise、rustup の管理方針は変更しない。
