# 根拠抽出(プロダクト概要): 請求管理システム

## 1. これは何のシステムか(3行要約)

社内の請求書を申請・承認し、月次で会計システムへ連携する業務システム。利用者は申請者・承認者・経理の3ロール(出典: basic-design.md#1)。

## 3. 代表的な業務フロー(入口 → 処理 → 出力)

1. 申請者が請求書入力画面で起票し申請する(出典: basic-design.md#3.1)。
2. 承認者が承認一覧画面で承認または差戻しする(出典: basic-design.md#3.2)。
3. 月次締めバッチが承認済みの請求書を会計システムへ連携する(出典: batch/monthly_close.py:1)。

## 4. データの全体像(主要エンティティと関係)

invoices(請求書)- invoice_lines(明細)の1対多。承認履歴は approvals に別テーブルで持つ(出典: db-schema.md#2)。

## 5. 外部連携・依存

会計システムへの月次CSV連携(非同期・ファイル連携)。連携失敗時の再送手順は資料に記述がない(evidence_level: hypothesis / derivation: inferred)。

## 6. 設定・権限・環境による挙動差

承認権限は role テーブルで制御する(出典: rbac.md#2)。金額上限による多段承認の有無は設定値 `APPROVAL_LIMIT` に依存する(出典: config/default.yml:8)。

## 7. 資料との対応と食い違い(要確認事項)

- 基本設計書は差戻しを「申請中のみ可」と書くが、実装は承認済みでも差戻しできる(出典: basic-design.md#3.2 / src/invoice/approve.py:55。evidence_level: confirmed)。どちらが正か要確認。

## 8. 根拠モデル(Actor候補 / オブジェクト候補 / 状態候補 / 外部連携)

- Actor候補: 申請者 / 承認者 / 経理 / 月次締めバッチ(出典: rbac.md#2)
- ドメインオブジェクト候補: 請求書 / 明細 / 承認履歴(出典: db-schema.md#2)
- 状態候補: draft / applied / approved(出典: src/invoice/models.py:12)
- 外部連携: 会計システム(月次CSV。出典: batch/monthly_close.py:1)

## 9. QAが押さえるべき勘所

- 締め処理と承認が同時に走る時間帯(evidence_level: likely / derivation: inferred。出典: batch/monthly_close.py:23 が締め時刻に承認可否を見ていない)。

## 11. 未調査領域と読み方ガイド

- 通知メールの送信条件(src/notify/ 未読)。承認フローの入口は src/invoice/approve.py から読むとよい。
