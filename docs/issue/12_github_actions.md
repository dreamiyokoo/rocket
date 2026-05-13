# [CI/CD] GitHub Actions の追加

## 概要

プロジェクトの品質を継続的に担保するための GitHub Actions ワークフローを整備する。
バックエンド・フロントエンドのリント＋テスト、および E2E テストを CI として自動実行する。

## ワークフロー構成

| ファイル | ジョブ内容 |
| --- | --- |
| `.github/workflows/backend.yml` | ruff によるリント + pytest（カバレッジ 85%）|
| `.github/workflows/frontend.yml` | ESLint + TypeScript 型チェック + ビルド検証 |
| `.github/workflows/e2e.yml` | Playwright による E2E テスト（Chromium） |

## バックエンド CI

- **リンター**: `ruff check .`
- **テスト**: `pytest --cov=. --cov-fail-under=85`
- **対象ファイル変更時のみ実行**: `api/**`

## フロントエンド CI

- **リンター**: `eslint app/`（ESLint 9 + `eslint-config-next`）
- **型チェック**: `tsc --noEmit`
- **ビルド**: `next build`
- **対象ファイル変更時のみ実行**: `frontend/**`

## E2E テスト

- **ツール**: Playwright（Chromium）
- **テスト実行**: `playwright test`
- **Web サーバー**: `npm run dev` を自動起動（`webServer` 設定）
- **テストファイル**: `frontend/e2e/`
- **CI アーティファクト**: Playwright HTML レポートを 7 日間保持

## 受け入れ条件

- [x] バックエンドの lint + test ワークフローが存在し、`api/**` 変更時に起動する
- [x] フロントエンドの lint + typecheck + build ワークフローが存在し、`frontend/**` 変更時に起動する
- [x] E2E ワークフロー（Playwright）が存在し、`frontend/**` 変更時に起動する
- [x] バックエンドのテストカバレッジが 85% 以上
- [x] Playwright レポートが CI アーティファクトとして保存される

## 技術メモ

- カバレッジ計測から除外するファイル: `core/database.py`, `core/redis.py`, `core/config.py`（インフラ接続コードのため）
- 現在のバックエンドカバレッジ: 96%
- Playwright は `webServer` 設定で Next.js dev サーバーを自動起動する
- `api/requirements-dev.txt` に `pytest-cov` と `ruff` を追加済み
- `frontend/package.json` に `lint`, `typecheck`, `test:e2e` スクリプトを追加済み
