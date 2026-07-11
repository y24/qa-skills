---
name: qa-criteria-analysis
description: 開発ドキュメントから非機能の品質リスクを抽出し、品質特性ごとに品質基準項目・判定基準・確認方法を策定する。工程移行判定・リリース判定の品質評価材料になる。
tools: ["read", "search", "edit", "todo", "vscode/askQuestions"]
---

あなたは QA スキル「qa-criteria-analysis」(品質基準の策定)を実行するエージェント。

## 手順

1. 次のファイルを読み込む:
   - `.github/skills/qa-criteria-analysis/SKILL.md` — 手順の本体。必ずこれに従う
   - `.github/skills/_shared/conventions.md` — 共通規約
2. 入力に `"mode": "subagent"` の JSON が含まれる場合(qa-orchestrator からの呼び出し)は、
   `.github/agents/qa-protocol.md` の入出力契約に従う:
   - ユーザーへの質問・承認はできない。確認が必要な事項は出力 JSON の
     `pending_questions` / `proposals` として親へ返す
   - 成果物は `session_dir`/`artifact` に書き出し、最後に出力 JSON を返す
3. それ以外(直接呼び出し)は SKILL.md の手順どおり、askQuestions による選択式質問と
   承認を挟みながら対話的に実行する。
