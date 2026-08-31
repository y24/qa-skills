# qa-session.json スキーマ

セッションファイルの形式。qa-orchestrator が作成・更新する(サブエージェントは更新しない — [subagent-contract.md](subagent-contract.md) §4)。

実行するスキルの組み合わせは固定ではなく、[skill-map.md](skill-map.md) の依存関係表から実行モードに応じて解決される。**下記の `plan` は Process モードの一例**であり、規定の並びではない。

```json
{
  "session_name": "invoice-approval-flow",
  "created_at": "2026-08-30T10:00:00+09:00",
  "updated_at": "2026-08-30T12:30:00+09:00",
  "run_mode": "process",
  "target": {
    "feature": "請求書の申請・承認フロー",
    "description": "対象機能・変更の1〜2行説明"
  },
  "inputs": [
    { "type": "spec",     "path": "docs/basic-design.xlsx",   "note": "基本設計書 v2",
      "converted_path": "qa-output/invoice-approval-flow/sources/basic-design.xlsx.md" },
    { "type": "rbac",     "path": "docs/roles.md",            "note": "権限定義" },
    { "type": "defects",  "path": "data/defects.csv",         "note": "過去不具合一覧" },
    { "type": "pr",       "path": "https://.../pull/123",     "note": "対象PR" },
    { "type": "code",     "path": "src/invoice/",             "note": "対象コード" },
    { "type": "criteria", "path": "docs/quality-criteria.md", "note": "既存の品質基準" }
  ],
  "plan": [
    { "order": 1, "skill": "qa-source-analysis",    "gate": "G2", "status": "approved",    "output": "00-source-analysis.md" },
    { "order": 2, "skill": "qa-defect-analysis",    "gate": "G2", "status": "approved",    "output": "01-defect-analysis.md" },
    { "order": 3, "skill": "qa-intent-recovery",    "gate": "G3", "status": "in_progress", "output": null },
    { "order": 4, "skill": "qa-spec-review",        "gate": "G2", "status": "pending", "output": null, "target": "requirements" },
    { "order": 5, "skill": "qa-scenario-design",    "gate": "G3", "status": "pending",     "output": null },
    { "order": 6, "skill": "qa-test-strategy",      "gate": "G4", "status": "pending",     "output": null },
    { "order": 7, "skill": "qa-test-viewpoint",     "gate": "G4", "status": "pending",     "output": null },
    { "order": 8, "skill": "qa-test-case-design",   "gate": "G4", "status": "pending",     "output": null },
    { "order": 9, "skill": "qa-test-design-review","gate": "G5", "status": "pending",     "output": null }
  ],
  "gates": [
    { "gate": "G1", "status": "approved", "approved_at": "2026-08-30T10:05:00+09:00" },
    { "gate": "G2", "status": "approved", "approved_at": "2026-08-30T11:20:00+09:00", "note": "AMB-003 は暫定解釈で進める" },
    { "gate": "G3", "status": "pending" },
    { "gate": "G4", "status": "pending" },
    { "gate": "G5", "status": "pending" }
  ],
  "current_order": 3,
  "decisions": [
    { "at": "2026-08-30T10:05:00+09:00", "phase": 2, "decision": "軽微な表記ゆれ不具合は分析対象から除外", "by": "user" }
  ],
  "improvement_notes": [
    "qa-intent-recovery で Value の推定根拠を書く欄が足りなかった"
  ]
}
```

## run_mode の値

[skill-map.md](skill-map.md) §2 を参照。`quick` / `grounded` / `process`。**成果物の限界の宣言**であり、この値は各成果物の冒頭注記に反映される。

## plan の各ステップ

| フィールド | 説明 |
|---|---|
| `order` | 実行順(重複不可)。skill-map.md の依存関係から解決した結果 |
| `skill` | スキル名 |
| `gate` | 所属する承認ゲート(G1〜G5。skill-map.md §3) |
| `status` | 下表 |
| `output` | 成果物ファイル名(conventions.md §6 の番号帯に従う) |
| `target` | 任意。同じスキルを対象違いで複数回実行するときのラベル。成果物名の接尾辞になる(例: `40-spec-review-requirements.md`) |

## status の値

| 値 | 意味 |
|---|---|
| `pending` | 未着手 |
| `in_progress` | 実行中 |
| `awaiting_approval` | 成果物提示済み・ゲート承認待ち |
| `approved` | 承認済み |
| `skipped` | 実行計画で除外 |

## gates の値

| 値 | 意味 |
|---|---|
| `pending` | 未到達 |
| `awaiting_approval` | 束ねる成果物が揃い、**レビュー依頼を出して回答待ち**(gates.md §4-1) |
| `approved` | 承認済み(次のゲートの範囲へ進める) |
| `skipped` | このゲートが束ねる成果物が1つも無いため省略 |

## 運用ルール

- `inputs` の `converted_path`(任意)は、Excel・PDF 等を markitdown で Markdown 化した中間ファイルのパス([source-conversion.md](source-conversion.md))。設定されている資料は、各スキルは原本ではなく `converted_path` を読む(出典表記は原本パス)。
- `decisions` にはユーザーの判断(除外・方針変更・承認時の条件・**ループバックの理由**)を必ず記録する。再開時の文脈になる。
- `improvement_notes` には実行中に気づいたスキル自体の改善点を追記する。qa-improvement が最後に回収する。
- 更新はステップ境界・ゲート境界ごと。更新には [scripts/qa_session.py](scripts/qa_session.py) のサブコマンド(init / add-input / add-phase / set-status / set-gate / add-decision / add-note / show / resume-info)を使う。Python が使えない環境では、ファイルを壊さないよう読み込み→修正→全体書き戻しで手動更新する(conventions.md §9)。
- ゲートのレビュー依頼を出した時点で、そのゲートを `awaiting_approval` にする(`set-gate <ゲート> awaiting_approval --note "<何を見てもらっているか>"`)。**再開時にレビュー依頼を出し直すための状態**であり、`pending`(まだ何も見せていない)と区別する。
- ループバック(skill-map.md §4)で前段に戻る場合は、戻り先ステップの status を `in_progress` に戻し、対応するゲートを `pending` に戻す。
