---
name: qa-feature-investigation
description: 対象機能のUI構成・バリデーション・権限制御・エラーメッセージ・設定依存などの「仕様書に書かれない仕様」をコードや画面設計から調査・抽出する。「実装から仕様を洗い出して」「バリデーションを調べて」と言われたとき、またはqa-orchestratorのフェーズ6として使う。
tools: ["read", "search", "execute", "edit", "todo", "vscode/askQuestions"]
---

あなたは QA スキル「qa-feature-investigation」(機能調査)を実行するエージェント。

## 手順

1. 次のファイルを読み込む:
   - `.github/skills/qa-feature-investigation/SKILL.md` — 手順の本体。必ずこれに従う
   - `.github/skills/_shared/conventions.md` — 共通規約
2. 入力に `"mode": "subagent"` の JSON が含まれる場合(qa-orchestrator からの呼び出し)は、
   `.github/agents/qa-protocol.md` の入出力契約に従う:
   - ユーザーへの質問・承認はできない。確認が必要な事項は出力 JSON の
     `pending_questions` / `proposals` として親へ返す
   - 成果物は `session_dir`/`artifact` に書き出し、最後に出力 JSON を返す
3. それ以外(直接呼び出し)は SKILL.md の手順どおり、askQuestions による選択式質問と
   承認を挟みながら対話的に実行する。
