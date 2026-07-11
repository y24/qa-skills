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
.github/skills/
  qa-orchestrator/          # 入口。ヒアリング→実行計画→フェーズ統括→承認ゲート
  qa-code-overview/         # Phase 0(フェーズ外・事前把握): コード+設計書・マニュアルからQA向け概要資料を作成
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
    scripts/                # 定型処理の補助スクリプト(Python 3.9+ 標準ライブラリのみ)
      qa_session.py         # qa-session.json の作成・更新・再開判定
      defect_stats.py       # 不具合CSVの正規化雛形とラベル集計
      pairwise.py           # ペアワイズ組み合わせ生成(自己検証付き)
      trace_check.py        # 成果物間のID突合(観点⇄ケース⇄QC⇄AMB)
      lint_output.py        # 成果物の書式・evidence_level・ID書式チェック

.github/agents/             # GitHub Copilot 用アダプター層(下記「GitHub Copilot カスタムエージェント層」参照)
  *.agent.md                # 各スキルへの薄いラッパー(スキルと1対1。フラット配置)
  qa-protocol.md            # サブエージェント呼び出し時の入出力JSON契約
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
   プロジェクト資産(セッション内で直接追記)とマスター資産(振り返りレポート経由で
   メンテナーが反映)の2系統。規範は
   [conventions.md §8](.github/skills/_shared/conventions.md) を参照。
7. **定型はスクリプト、判断はAI** — セッションファイルの更新・ID突合・件数集計・
   組み合わせ生成・書式チェックは [`_shared/scripts/`](.github/skills/_shared/scripts/README.md)
   の決定論的なスクリプトに委譲し、AIはラベル付け・解釈・対応方針の判断に集中する。
   規範は [conventions.md §9](.github/skills/_shared/conventions.md) を参照。

## 外部ナレッジベースとの連携(任意)

ドメイン知識が用語集1ファイルに収まらないプロジェクトでは、OKF × LLM Wiki 形式の
QAナレッジベース(別リポジトリ)を追加のドメイン知識ソースとして参照できる。
設定・参照プロトコル・証拠レベル・還元ルールはすべて
[_shared/knowledge-base.md](.github/skills/_shared/knowledge-base.md) に集約(必須前提ではない)。

## 各ツールでの使い方

このディレクトリを各ツールがスキル/指示として読める場所に置く(またはリンクする)。

| ツール | 方法 |
|---|---|
| GitHub Copilot | **専用のカスタムエージェント層 `.github/agents/` を同梱**(VS Code v1.107+)。`.github/skills/` は Copilot の Agent Skills 公式配置でもあるため、各スキルは Copilot から直接発見される。qa-orchestrator が `#tool:agent/runSubagent` で各フェーズエージェントを呼び出す。詳細は下記「GitHub Copilot カスタムエージェント層」を参照。質問ツールは `vscode/askQuestions` が使われる |
| Claude Code | `.claude/skills/` へリンクするか、プロンプトで `SKILL.md` を直接読ませる。質問ツールは `AskUserQuestion` が使われる |
| Cursor / その他 | ルール・コンテキストとして `qa-orchestrator/SKILL.md` を読み込ませれば、残りは相対パスで辿られる |

どのツールでも、スキル機構がない場合は「`.github/skills/qa-orchestrator/SKILL.md` を
読んでその指示に従って」と依頼すれば動作する。

### GitHub Copilot カスタムエージェント層(.github/agents/)

`.github/skills/` の SKILL.md 群を GitHub Copilot のカスタムエージェント +
`#tool:agent/runSubagent` で動かすためのアダプター層。

- **手順の本体はあくまで `.github/skills/<名前>/SKILL.md`**。`*.agent.md` は
  「フロントマター(description/tools)+ SKILL.md への参照 + サブエージェント時の
  入出力契約」だけを持つ薄いラッパー。スキルの手順を変えるときは SKILL.md 側を直す。
- エージェントはスキルと1対1対応(qa-orchestrator 〜 qa-skillset-maintenance)。
  `.github/agents/` はサブディレクトリ非対応のためフラット配置。
  [qa-protocol.md](.github/agents/qa-protocol.md) はエージェント定義ではなく、
  サブエージェント呼び出し時の入出力 JSON・制約の集約先。

**必要環境**:

- VS Code + GitHub Copilot **v1.107 以降**(カスタムエージェントを runSubagent で
  直接呼び出せるのはこのバージョンから)
- `settings.json` に以下を追加(このリポジトリでは `.vscode/settings.json` に設定済み):

```json
{
  "chat.customAgentInSubagent.enabled": true
}
```

**使い方**:

1. **フルフロー**: Copilot Chat のエージェント選択で `qa-orchestrator` を選び、
   テスト対象とやりたいことを伝える。ヒアリング → 実行計画 → 各フェーズの
   サブエージェント実行 → 承認ゲート、が順に進む。
2. **単独実行**: `qa-defect-analysis` や `qa-code-review` などを直接選んで使う。
   直接呼び出しでは SKILL.md の手順どおり対話的(`vscode/askQuestions` ツール)に動く。

**設計上の注意**:

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
- Premium Requests は指示単位で消費されるため、フルフローは qa-orchestrator への
  一回の指示でまとめて流すのが経済的。その分サブエージェント呼び出しの
  オーバーヘッドで応答時間・総トークンは増える。

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
