# GitHub Copilot カスタムエージェント層

`.github/skills/`(ツール非依存の SKILL.md 群)を GitHub Copilot の
カスタムエージェント + `#tool:agent/runSubagent` で動かすためのアダプター層。

スキル層は `.github/skills/` に配置している。これは GitHub Copilot の
Agent Skills の公式配置ディレクトリでもあるため、各スキルは本層(カスタム
エージェント)経由だけでなく、Copilot の Agent Skills としても直接発見される。

- **手順の本体は `.github/skills/<名前>/SKILL.md`**。この層の `*.agent.md` は
  「フロントマター(description/tools)+ SKILL.md への参照 + サブエージェント時の
  入出力契約」だけを持つ薄いラッパー。スキルの手順を変えるときは SKILL.md 側を直す。
- サブエージェント呼び出し時の入出力 JSON・制約は [qa-protocol.md](qa-protocol.md) に集約。

## 必要環境

- VS Code + GitHub Copilot **v1.107 以降**(カスタムエージェントを runSubagent で
  直接呼び出せるのはこのバージョンから)
- `settings.json` に以下を追加(このリポジトリでは `.vscode/settings.json` に設定済み):

```json
{
  "chat.customAgentInSubagent.enabled": true
}
```

## 使い方

1. **フルフロー**: Copilot Chat のエージェント選択で `qa-orchestrator` を選び、
   テスト対象とやりたいことを伝える。ヒアリング → 実行計画 → 各フェーズの
   サブエージェント実行 → 承認ゲート、が順に進む。
2. **単独実行**: `qa-defect-analysis` や `qa-code-review` などを直接選んで使う。
   直接呼び出しでは SKILL.md の手順どおり対話的(`vscode/askQuestions` ツール)に動く。

## 設計上の注意

- **ユーザーとの対話は qa-orchestrator(メインエージェント)に集約**している。
  runSubagent で起動されたサブエージェントはユーザーに質問できないため、
  承認・選択が必要な事項は出力 JSON の `pending_questions` / `proposals` として
  親に返し、親が askQuestions で確認してから再呼び出しする(qa-protocol.md 参照)。
- 各エージェントの `tools` は必要最小限に絞っている(コンテキスト肥大化の防止)。
  Copilot のバージョンによってツール ID が異なる場合は、チャットのツール一覧に
  合わせて `tools` を調整すること。
- 補助スクリプト(`.github/skills/_shared/scripts/`、conventions.md §9)を使う
  エージェント(qa-orchestrator / qa-defect-analysis / qa-test-viewpoint /
  qa-test-case-design / qa-test-design-review / qa-improvement)には `execute` を
  付与している。Python が使えない環境ではスクリプトなしの手動手順にフォールバックする。
- `.github/agents/` はサブディレクトリ非対応のためフラット配置。
  `qa-protocol.md` と本 README はエージェント定義ではない(`.agent.md` ではない)。
- Premium Requests は指示単位で消費されるため、フルフローは qa-orchestrator への
  一回の指示でまとめて流すのが経済的。その分サブエージェント呼び出しの
  オーバーヘッドで応答時間・総トークンは増える。

## ファイル対応表

| エージェント | 役割 | 元スキル |
|---|---|---|
| qa-orchestrator | 入口。runSubagent で各フェーズを統括 | `.github/skills/qa-orchestrator/` |
| qa-code-overview | フェーズ外: QA向けコード概要資料 | `.github/skills/qa-code-overview/` |
| qa-defect-analysis | Phase 1: 不具合分析と回帰観点導出 | `.github/skills/qa-defect-analysis/` |
| qa-test-analysis | Phase 2: 影響範囲・リスク・テスト方針 | `.github/skills/qa-test-analysis/` |
| qa-criteria-analysis | Phase 3: 品質基準の策定 | `.github/skills/qa-criteria-analysis/` |
| qa-spec-review | Phase 4/9: 仕様曖昧性検出 | `.github/skills/qa-spec-review/` |
| qa-test-planning | Phase 5: テスト計画 | `.github/skills/qa-test-planning/` |
| qa-feature-investigation | Phase 6: 実装からの仕様補完 | `.github/skills/qa-feature-investigation/` |
| qa-code-review | Phase 7: QAコードレビュー | `.github/skills/qa-code-review/` |
| qa-test-viewpoint | Phase 8: テスト観点抽出 | `.github/skills/qa-test-viewpoint/` |
| qa-test-case-design | Phase 10: テストケース展開 | `.github/skills/qa-test-case-design/` |
| qa-test-data-design | Phase 11: テストデータ設計 | `.github/skills/qa-test-data-design/` |
| qa-test-design-review | Phase 12: 独立レビュー | `.github/skills/qa-test-design-review/` |
| qa-improvement | Phase 99: 振り返りレポート | `.github/skills/qa-improvement/` |
| qa-skillset-maintenance | メンテナー向け(直接呼び出し専用) | `.github/skills/qa-skillset-maintenance/` |
