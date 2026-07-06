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
  qa-criteria-analysis/     # Phase 3: 非機能の品質基準項目・判定基準・確認方法の策定
  qa-spec-review/           # Phase 4/9: 仕様曖昧性検出(モード1=仕様、モード2=期待結果)
  qa-test-planning/         # Phase 5: テスト計画
  qa-feature-investigation/ # Phase 6: コード・デザインからの仕様補完
  qa-code-review/           # Phase 7: 品質特性ベースのQAコードレビュー(シフトレフト)
  qa-test-viewpoint/        # Phase 8: テスト観点抽出
  qa-test-case-design/      # Phase 10: テストケース展開
  qa-test-data-design/      # Phase 11: テストデータ設計
  qa-test-design-review/    # Phase 12: 独立レビュー(S〜D評価)
  qa-improvement/           # Phase 99: 振り返りレポート(99-improvement.md)の作成
  qa-skillset-maintenance/  # マスター側: レポートの採否検討と反映(メンテナー向け。フェーズ外)
  _shared/
    conventions.md          # 全スキル共通規約(対話・承認ゲート・証拠レベル)
    session-schema.md       # qa-session.json のスキーマ
    knowledge-base.md       # 外部ナレッジベース(OKF×LLM Wiki)連携の設定と参照プロトコル(任意)
    maintenance-log.md      # 振り返りレポートの採否履歴(qa-skillset-maintenance が更新)
    references/             # AIが読むナレッジ(育てる資産)
      test-design-techniques.md
      quality-characteristics.md
      spec-ambiguity-checklist.md
      test-oracles.md                   # テストオラクル(FEW HICCUPPS)
      product-coverage-model.md         # プロダクトカバレッジモデル(SFDIPOT)
      defect-taxonomy.md
      regression-viewpoint-catalog.md   # ★過去不具合→回帰観点の蓄積場所
      review-checklist.md               # ★自分のレビュー観点の蓄積場所
      code-review-viewpoints.md         # ★品質特性→コードの見どころ(QAコードレビュー用)
      domain-glossary.md                # ★ドメイン用語の蓄積場所(KB連携時はインボックス兼用)
```

## 設計原則

1. **入口は少なく、知識は多く** — ユーザーが呼ぶのは基本 `qa-orchestrator` だけ。
   技法・チェックリストはスキルではなく `_shared/references/` に置き、AIが読む。
2. **選択式の対話** — 質問は自由記述でなく選択肢(`askQuestions` 等)。属人化を防ぐ。
3. **承認ゲート** — フェーズごとに人間が承認。成果物の責任は人間が持つ。
4. **証拠レベル** — 全ての分析・指摘に confirmed / likely / hypothesis を付け、
   推測と事実を混ぜない。
5. **バケツリレー** — 前フェーズの成果物を次フェーズが読み、情報の純度を上げる。
6. **育てる資産** — ★印のファイルにセッションの知見を還元して育てる。還元経路は
   ファイルの性格で2系統に分かれる:
   - **プロジェクト資産**(`regression-viewpoint-catalog.md` / `domain-glossary.md`):
     BUG-ID・用語などプロジェクト固有の知識。配布先リポジトリのセッション内で
     承認を経て直接追記して育てる。マスターへは反映しない。
   - **マスター資産**(`review-checklist.md` / `code-review-viewpoints.md` /
     `defect-taxonomy.md` / 各 `SKILL.md` / `conventions.md`): プロジェクトを跨いで
     使える知見。セッション内では書き換えず、qa-improvement が振り返りレポート
     (99-improvement.md)に提案として一覧化し、メンテナーがマスターのリポジトリ上で
     `qa-skillset-maintenance` を使って採否を検討・反映する(採否履歴は
     `_shared/maintenance-log.md` に蓄積)。

## 外部ナレッジベースとの連携(任意)

ドメイン知識が用語集1ファイルに収まらないプロジェクトでは、OKF × LLM Wiki 形式の
QAナレッジベース(別リポジトリ)を追加のドメイン知識ソースとして参照できる。
設定・参照プロトコル・証拠レベル・還元ルールはすべて
[_shared/knowledge-base.md](_shared/knowledge-base.md) に集約(必須前提ではない)。

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

シフトレフトを先に試したい場合は、実際のPR 1件に対して `qa-code-review` を
単独実行するのも入口として有効(品質特性ラベル付きの指摘と「コードで保証済み=
テスト軽減候補」が得られる)。

フェーズ移行判定・リリース判定が迫っている場合は、手元の計画書・要件定義書・仕様書を
入力に `qa-criteria-analysis` を単独実行すると、品質特性別の品質基準項目・判定基準・
確認方法(確認フェーズ: 設計/UT/IT/ST ラベル付き)が判定材料として得られる。
