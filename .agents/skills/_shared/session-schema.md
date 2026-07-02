# qa-session.json スキーマ

セッションファイルの形式。qa-orchestrator が作成し、各フェーズのスキルが更新する。

```json
{
  "session_name": "invoice-export-feature",
  "created_at": "2026-07-03T10:00:00+09:00",
  "updated_at": "2026-07-03T12:30:00+09:00",
  "target": {
    "feature": "請求書エクスポート機能",
    "description": "対象機能・変更の1〜2行説明"
  },
  "knowledge_sources": {
    "wiki_path": "D:/knowledge/wiki",
    "wiki_available": true,
    "search_tool": "Select-String",
    "note": "knowledge-source.md の設定を解決した結果。未設定なら wiki_available: false"
  },
  "inputs": [
    { "type": "spec",    "path": "docs/spec.md",        "note": "仕様書 v2" },
    { "type": "defects", "path": "data/defects.csv",    "note": "過去不具合一覧" },
    { "type": "pr",      "path": "https://.../pull/123", "note": "対象PR" },
    { "type": "code",    "path": "src/export/",          "note": "対象コード" }
  ],
  "plan": [
    { "order": 1, "skill": "qa-defect-analysis",     "status": "approved",    "output": "01-defect-analysis.md" },
    { "order": 2, "skill": "qa-test-analysis",       "status": "in_progress", "output": "02-test-analysis.md" },
    { "order": 3, "skill": "qa-spec-review",         "mode": 1, "status": "pending", "output": null },
    { "order": 4, "skill": "qa-test-planning",       "status": "skipped",     "output": null },
    { "order": 5, "skill": "qa-feature-investigation","status": "pending",    "output": null },
    { "order": 6, "skill": "qa-test-viewpoint",      "status": "pending",     "output": null },
    { "order": 7, "skill": "qa-spec-review",         "mode": 2, "status": "pending", "output": null },
    { "order": 8, "skill": "qa-test-case-design",    "status": "pending",     "output": null },
    { "order": 9, "skill": "qa-test-data-design",    "status": "pending",     "output": null },
    { "order": 10, "skill": "qa-test-design-review", "status": "pending",     "output": null }
  ],
  "current_order": 2,
  "decisions": [
    { "at": "2026-07-03T10:05:00+09:00", "phase": 1, "decision": "軽微な表記ゆれ不具合は分析対象から除外", "by": "user" }
  ],
  "improvement_notes": [
    "フェーズ2で影響範囲の質問が冗長だった(選択肢を絞るべき)"
  ]
}
```

## status の値

| 値 | 意味 |
|---|---|
| `pending` | 未着手 |
| `in_progress` | 実行中 |
| `awaiting_approval` | 成果物提示済み・承認待ち |
| `approved` | 承認済み(次フェーズへ進める) |
| `skipped` | 実行計画で除外 |

## 運用ルール

- `decisions` にはユーザーの判断(除外・方針変更・承認時の条件)を必ず記録する。再開時の文脈になる。
- `improvement_notes` には実行中に気づいたスキル自体の改善点を追記する。qa-improvement が最後に回収する。
- 更新はフェーズ境界ごと。ファイルを壊さないよう、必ず読み込み→修正→全体書き戻しで行う。
