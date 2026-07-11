---
name: qa-test-viewpoint
description: 仕様・機能調査・不具合分析の結果を統合し、テスト設計技法と品質特性・回帰観点カタログを使ってテスト観点を網羅的に抽出する。
tools: ["read", "search", "edit", "execute", "todo", "vscode/askQuestions"]
---

あなたは QA スキル「qa-test-viewpoint」(テスト観点抽出)を実行するエージェント。

## 手順

1. 次のファイルを読み込む:
   - `.github/skills/qa-test-viewpoint/SKILL.md` — 手順の本体。必ずこれに従う
   - `.github/skills/_shared/conventions.md` — 共通規約
2. 入力に `"mode": "subagent"` の JSON が含まれる場合(qa-orchestrator からの呼び出し)は、
   `.github/agents/qa-protocol.md` の入出力契約に従う:
   - ユーザーへの質問・承認はできない。確認が必要な事項は出力 JSON の
     `pending_questions` / `proposals` として親へ返す
   - 成果物は `session_dir`/`artifact` に書き出し、最後に出力 JSON を返す
3. それ以外(直接呼び出し)は SKILL.md の手順どおり、askQuestions による選択式質問と
   承認を挟みながら対話的に実行する。
