# 購買申請システム(PRQ)テーブル定義書(抜粋)

| 項目 | 内容 |
|---|---|
| 文書番号 | PRQ-DB-001 |
| 版数 | v1.5 |
| 最終更新 | 2026-07-10 |

主要テーブルのみを抜粋する。マスタ系(社員・部門・予算科目・サプライヤ・営業日カレンダー)は割愛する。

## requisitions(申請)

| 列名 | 型 | NULL | 説明 |
|---|---|---|---|
| `id` | bigint | × | 主キー |
| `requisition_no` | varchar(16) | × | 申請番号 `PRQ-YYYY-NNNNN`。一意 |
| `title` | varchar(60) | × | 件名 |
| `requester_id` | bigint | × | 申請者(社員ID) |
| `department_id` | bigint | × | 申請時点の申請者の所属部門 |
| `budget_account_id` | bigint | × | 予算科目 |
| `desired_delivery_date` | date | × | 希望納期 |
| `reason` | varchar(500) | × | 購買理由 |
| `total_amount` | decimal(10,0) | × | 税抜合計金額(明細の数量×単価の合計) |
| `status` | varchar(16) | × | 状態(基本設計書 §2) |
| `submitted_at` | datetime | ○ | 直近の提出日時 |
| `approved_at` | datetime | ○ | 最終承認日時 |
| `canceled_reason` | varchar(200) | ○ | 取消理由 |
| `created_at` / `updated_at` | datetime | × | 楽観排他に使用 |

## requisition_items(申請明細)

| 列名 | 型 | NULL | 説明 |
|---|---|---|---|
| `id` | bigint | × | 主キー |
| `requisition_id` | bigint | × | 申請 |
| `line_no` | int | × | 明細行番号(1〜20) |
| `item_name` | varchar(100) | × | 品目名 |
| `quantity` | int | × | 数量 |
| `unit_price` | decimal(9,0) | × | 申請単価(税抜) |
| `ordered_unit_price` | decimal(9,0) | ○ | 発注単価(税抜) |
| `received_quantity` | int | ○ | 検収数量 |

## approvals(承認ステップ)

| 列名 | 型 | NULL | 説明 |
|---|---|---|---|
| `id` | bigint | × | 主キー |
| `requisition_id` | bigint | × | 申請 |
| `step` | int | × | 承認段階(1 または 2) |
| `assignee_id` | bigint | × | 本来の承認者 |
| `status` | varchar(16) | × | `pending` / `approved` / `returned` |
| `approved_by` | bigint | ○ | 実際に操作した者(代理承認時は代理承認者) |
| `is_delegated` | boolean | × | 代理承認フラグ(既定 false) |
| `comment` | varchar(500) | ○ | 承認・差戻しコメント |
| `acted_at` | datetime | ○ | 操作日時 |

`requisition_id + step` に一意制約を持つ。

## delegations(代理承認設定)

| 列名 | 型 | NULL | 説明 |
|---|---|---|---|
| `id` | bigint | × | 主キー |
| `approver_id` | bigint | × | 本来の承認者 |
| `delegate_id` | bigint | × | 代理承認者 |
| `valid_from` | date | × | 不在期間の開始日 |
| `valid_to` | date | × | 不在期間の終了日 |

## orders(発注)

| 列名 | 型 | NULL | 説明 |
|---|---|---|---|
| `id` | bigint | × | 主キー |
| `requisition_id` | bigint | × | 申請。1申請1発注 |
| `supplier_id` | bigint | × | サプライヤ |
| `ordered_at` | datetime | × | 発注確定日時 |
| `ordered_by` | bigint | × | 発注確定者(購買担当) |
| `edi_sent_at` | datetime | ○ | EDI送信日時。NULL は未送信 |

## receipts(検収)

| 列名 | 型 | NULL | 説明 |
|---|---|---|---|
| `id` | bigint | × | 主キー |
| `requisition_id` | bigint | × | 申請 |
| `received_date` | date | × | 検収日 |
| `received_by` | bigint | × | 検収者 |
| `comment` | varchar(200) | ○ | 検収コメント |

## monthly_closings(月次締め)

| 列名 | 型 | NULL | 説明 |
|---|---|---|---|
| `period` | char(6) | × | 月度(YYYYMM)。主キー |
| `closed_at` | datetime | × | 締め実行日時 |
| `closed_by` | bigint | × | 実行者(経理担当) |

## audit_logs(監査ログ)

| 列名 | 型 | NULL | 説明 |
|---|---|---|---|
| `id` | bigint | × | 主キー |
| `event_type` | varchar(32) | × | `status_change` / `approval` / `permission_denied` / `master_change` |
| `requisition_id` | bigint | ○ | 対象申請 |
| `from_status` / `to_status` | varchar(16) | ○ | 状態変化時のみ |
| `actor_id` | bigint | × | 操作者 |
| `payload` | text | ○ | 補足情報(JSON) |
| `occurred_at` | datetime | × | 発生日時 |
