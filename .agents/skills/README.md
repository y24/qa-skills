# QA Engineer Skills

QAエンジニア業務(テスト分析〜設計〜レビュー〜ナレッジ蓄積)をAIエージェントで
支援するスキルセット。特定のAIツールに依存しない
[Agent Skills](https://agentskills.io) 形式(`SKILL.md` + `name`/`description`
フロントマターのみ)で記述している。

参考: [qa-orchestrator の記事](https://zenn.dev/aldagram_tech/articles/4aea4b13671ae3)
の構成(オーケストレーター + フェーズ制 + 承認ゲート + セッション復帰)をベースに、
証拠レベルの強制・参照ナレッジの外部化・回帰観点カタログの蓄積を加えたもの。

## 構成

```
.agents/skills/
  qa-orchestrator/          # 入口。ヒアリング→実行計画→フェーズ統括→承認ゲート
  qa-defect-analysis/       # Phase 1: 不具合分析と回帰観点導出
  qa-test-analysis/         # Phase 2: 影響範囲・リスク評価・テスト方針
  qa-spec-review/           # Phase 3/7: 仕様曖昧性検出(モード1=仕様、モード2=期待結果)
  qa-test-planning/         # Phase 4: テスト計画
  qa-feature-investigation/ # Phase 5: コード・デザインからの仕様補完
  qa-test-viewpoint/        # Phase 6: テスト観点抽出
  qa-test-case-design/      # Phase 8: テストケース展開
  qa-test-data-design/      # Phase 9: テストデータ設計
  qa-test-design-review/    # Phase 10: 独立レビュー(S〜D評価)
  qa-improvement/           # Phase 99: スキルセット自己進化
  _shared/
    conventions.md          # 全スキル共通規約(対話・承認ゲート・証拠レベル)
    session-schema.md       # qa-session.json のスキーマ
    references/             # AIが読むナレッジ(育てる資産)
      test-design-techniques.md
      quality-characteristics.md
      spec-ambiguity-checklist.md
      defect-taxonomy.md
      regression-viewpoint-catalog.md   # ★過去不具合→回帰観点の蓄積場所
      review-checklist.md               # ★自分のレビュー観点の蓄積場所
      domain-glossary.md                # ★ドメイン用語の蓄積場所
```

## 設計原則

1. **入口は少なく、知識は多く** — ユーザーが呼ぶのは基本 `qa-orchestrator` だけ。
   技法・チェックリストはスキルではなく `_shared/references/` に置き、AIが読む。
2. **選択式の対話** — 質問は自由記述でなく選択肢(`askQuestions` 等)。属人化を防ぐ。
3. **承認ゲート** — フェーズごとに人間が承認。成果物の責任は人間が持つ。
4. **証拠レベル** — 全ての分析・指摘に confirmed / likely / hypothesis を付け、
   推測と事実を混ぜない。
5. **バケツリレー** — 前フェーズの成果物を次フェーズが読み、情報の純度を上げる。
6. **育てる資産** — ★印のファイルはセッションごとに qa-improvement が追記し、
   スキルセットが自分の現場に適応していく。

## 各ツールでの使い方

このディレクトリを各ツールがスキル/指示として読める場所に置く(またはリンクする)。

| ツール | 方法 |
|---|---|
| GitHub Copilot | スキル探索対象にこのパスを設定するか、各ツールの規定の場所(例: `.github/skills/`)へコピー/シンボリックリンク。質問ツールは `askQuestions` が使われる |
| Claude Code | `.claude/skills/` へリンクするか、プロンプトで `SKILL.md` を直接読ませる。質問ツールは `AskUserQuestion` が使われる |
| Cursor / その他 | ルール・コンテキストとして `qa-orchestrator/SKILL.md` を読み込ませれば、残りは相対パスで辿られる |

どのツールでも、スキル機構がない場合は「`.agents/skills/qa-orchestrator/SKILL.md` を
読んでその指示に従って」と依頼すれば動作する。

## 最初の一歩(PoC)

いきなりフルフローを回すより、価値が出やすい流れから試すのを推奨:

1. 過去不具合50〜100件をCSVで用意(`id,title,description,feature,severity` 程度でよい)
2. `qa-defect-analysis` を単独実行 → 回帰観点カタログに数エントリ蓄積
3. 実際のテスト設計書に対して `qa-test-design-review` を実行 → カタログの観点が
   レビューに効くことを確認
4. 効果を確認できたらフルフロー(`qa-orchestrator`)へ
