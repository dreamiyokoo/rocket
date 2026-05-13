# [DB] PostgreSQL スキーマ設計・マイグレーション

## 概要

分析に必要なテーブルを PostgreSQL に作成する。
マイグレーション管理には Alembic を使用する。

## テーブル定義

```sql
-- 入力者アカウント（固定1名）
CREATE TABLE users (
  id            SERIAL PRIMARY KEY,
  username      VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ラウンド倍率履歴
CREATE TABLE rounds (
  id            SERIAL PRIMARY KEY,
  multiplier    NUMERIC(12, 4) NOT NULL,
  recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 分析スナップショット
CREATE TABLE analysis_snapshots (
  id            SERIAL PRIMARY KEY,
  prob_2x       NUMERIC(6, 4),
  prob_5x       NUMERIC(6, 4),
  prob_10x      NUMERIC(6, 4),
  moving_avg    NUMERIC(12, 4),
  window_size   INTEGER,
  snapshot_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 受け入れ条件

- [ ] 上記3テーブルがマイグレーションで作成される
- [ ] `users` テーブルに入力者1名の初期データが seed として投入される
- [ ] `rounds.multiplier` に 0 以下の値が入らないよう CHECK 制約を設ける
- [ ] `recorded_at` にインデックスを設ける（時系列クエリ用）
- [ ] マイグレーションは `alembic upgrade head` で適用できる

## 技術メモ

- パスワードは bcrypt でハッシュ化して保存する
- seed スクリプトは `scripts/seed.py` として管理する
