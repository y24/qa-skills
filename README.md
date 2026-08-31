# QA Engineer Skills

QAエンジニア業務(業務シナリオの復元〜テスト分析〜設計〜レビュー〜ナレッジ蓄積)を
AIエージェントで支援するスキルセット。特定のAIツールに依存しない
[Agent Skills](https://agentskills.io) 形式(`SKILL.md` + `name`/`description`
フロントマターのみ)で記述している。

**このスキルセットが狙う空白**は、設計資料から**利用者の目的を復元し、複数ロール・
状態遷移・例外・後続影響を含む業務シナリオを作る**ところにある。仕様書を機能単位で
テストケースに展開することは既にコモディティ化しているが、業務プロセスの意味を
復元する部分は依然として手つかずの領域である。

## 構成

```
.github/skills/
  qa-orchestrator/          # 入口。ヒアリング→モード選定→連鎖の解決→ゲート管理
  qa-source-analysis/       # 00: コード・設計書・画面・RBAC・状態定義から事実(根拠モデル)を抽出
  qa-defect-analysis/       # 01: 不具合分析と回帰観点導出
  qa-intent-recovery/       # 10: Actor・業務ゴール・状態遷移・引き継ぎの復元 → ユーザーストーリー
  qa-scenario-design/       # 11: 業務シナリオ(正常/代替/例外/回復/取消/同時実行/権限違反)
  qa-test-strategy/         # 20-21: 影響範囲・リスク・品質基準・テスト方針・計画
  qa-test-viewpoint/        # 30: テスト観点抽出
  qa-test-case-design/      # 31-32: テストケース展開とテストデータ設計
  qa-spec-review/           # 40: 曖昧性検出(対象を指定して実行。仕様書・意図モデル等)
  qa-test-design-review/    # 42: 独立レビュー(S〜D評価。期待結果の全数監査 → 修正 → 再レビューまで)
  qa-improvement/           # 90: 振り返りレポートと指標測定
  _shared/
    skill-map.md            # ★スキル依存関係・実行モード・ゲートの唯一の定義元
    conventions.md          # 全スキル共通規約(対話・証拠レベルと導出区分・成果物・指標)
    gates.md                # ゲートの実施手順(ゲートを運ぶスキルだけが読む)
    subagent-contract.md    # コンテキスト分離実行の入出力契約(ツール非依存)
    session-schema.md       # qa-session.json のスキーマ
    maintenance-log.md      # マスター資産の改善トリアージ手順と採否履歴
    source-conversion.md    # Excel/PDF等→Markdown変換(markitdown)の手順
    diff-acquisition.md     # PR・コード差分の取得手順
    references/             # AIが読むナレッジ(育てる資産)
      business-scenario-patterns.md     # 業務シナリオの型(申請・承認・差戻し・引き継ぎ失敗等)
      test-design-techniques.md
      quality-characteristics.md
      spec-ambiguity-checklist.md
      test-oracles.md                   # テストオラクル(FEW HICCUPPS)
      defect-taxonomy.md
      regression-viewpoint-catalog.md   # ★過去不具合→回帰観点の蓄積場所
      review-checklist.md               # ★自分のレビュー観点の蓄積場所
      domain-glossary.md                # ★ドメイン用語の蓄積場所
    hooks.md                # ★hooksが何を保証するかの唯一の定義元
    schemas/                # ★台帳系成果物のスキーマ(列・必須・許容値・MD構成)
      intent-recovery.yaml  #   意図モデル(ACT / TRN / BG の3台帳)
      scenario-design.yaml  #   業務シナリオ(一覧・詳細・提案を1台帳から描き分ける)
      test-viewpoint.yaml
      test-case.yaml
    scripts/                # 定型処理の補助スクリプト(Python 3.9+ 標準ライブラリのみ)
      qa_session.py         # qa-session.json の作成・更新・再開判定
      defect_stats.py       # 不具合CSVの下見・台帳CSVへの正規化・ラベル集計
      pairwise.py           # ペアワイズ組み合わせ生成(自己検証付き)
      trace_check.py        # 成果物間のID突合(意図モデル⇄シナリオ⇄観点⇄ケース)
      lint_output.py        # 成果物の書式・evidence_level・derivation・ID書式チェック
      metrics.py            # 指標算出(根拠参照率・トレース率・カバレッジ)
      gate_check.py         # ★検証の単一入口(lint+突合+スキーマをゲート単位で束ねる)
      hook_entry.py         # hooksアダプタ(各ツールの入出力方言を吸収する薄い層)
      miniyaml.py           # スキーマ(YAML)を読む限定パーサー(PyYAML不要)
      normalize_ledger.py   # 台帳CSVの正規化(セル内改行を実改行に揃える)
      validate_artifact.py  # 台帳CSVのスキーマ検証
      render_md.py          # 台帳CSV + notes.md → 人間向けMarkdown
                            #   (proposed を機械的に別表へ)

.github/agents/             # GitHub Copilot 用アダプター層(2ファイルのみ)
  qa-orchestrator.agent.md  # 統括役
  qa-skill-runner.agent.md  # 全スキル共通の汎用ランナー

.github/hooks/              # 品質ゲートの配線(Copilot CLI / cloud agent / VS Code)
  qa-quality-gates.json
.claude/settings.json       # 同じ配線(Claude Code。形式が違うだけで呼ぶものは同じ)
.github/workflows/
  qa-artifacts.yml          # CI。成果物の検証と、検証層自身の自己検査
tests/fixtures/             # CIが使う構造化成果物のサンプル
```

## 設計原則

1. **入口は少なく、知識は多く** — ユーザーが呼ぶのは基本 `qa-orchestrator` だけ。
   技法・チェックリストはスキルではなく `_shared/references/` に置き、AIが読む。
2. **定義元は1箇所** — スキルの連鎖・モード・ゲートは
   [skill-map.md](.github/skills/_shared/skill-map.md) だけが定義する。
   オーケストレーターは順序をハードコードせず、依存関係から毎回解決する。
3. **選択式の対話** — 質問は自由記述でなく選択肢。属人化を防ぐ。
   必須質問を先に、「すべて推奨で進める」のファストパスを常設。
   **実装の中身は質問にしない** — バリデーション・既定値・権限・遷移条件のような
   詳細設計は、答えを持たない QA 担当者に聞かず、前段の成果物 → 資料 → コードの
   順で調べて出典付きで確定させる。**判断を仰ぐ質問(範囲・除外・優先度・承認・
   業務の実態)は従来どおり聞く** — 質問を減らすことが目的ではない
   ([conventions.md §2-1](.github/skills/_shared/conventions.md))。
4. **ゲートは意味が変わる地点に** — 成果物ごとの逐一承認ではなく、G1〜G5 の5ゲート。
   承認の形骸化を防ぐ。成果物の責任は人間が持つ。
   ゲートでは「承認しますか」ではなく**レビュー依頼**を出す — どのファイルの
   どこを見て何を判断すればよいかを示し、その質問への回答で承認・差し戻しを完結させる。
5. **証拠レベル × 導出区分** — confirmed/likely/hypothesis(確信度)と
   explicit/inferred/proposed(出所)の**直交する2軸**。導出区分は explicit が既定で、
   **推定(inferred)と提案(proposed)にだけ印を付ける**。
   **AIが資料外から補った項目を資料由来の事実と混ぜない。**
6. **ストーリーは正本ではない** — 正本は業務プロセスモデル(Actor・状態・遷移・
   引き継ぎ)。ストーリーはそのビュー。ストーリーは情報を圧縮するため、
   複数ロールの業務を保持できない。
7. **バケツリレー** — 前段の成果物を後続が読み、情報の純度を上げる。
   後段で欠落に気づいたら前段に戻ってよい(ループバックは失敗ではない)。
8. **育てる資産** — ★印のファイルにセッションの知見を還元して育てる。還元経路は
   プロジェクト資産(セッション内で直接追記)とマスター資産(振り返りレポート経由で
   [maintenance-log.md](.github/skills/_shared/maintenance-log.md) のトリアージを経る)
   の2系統。規範は [conventions.md §8](.github/skills/_shared/conventions.md)。
9. **定型はスクリプト、判断はAI** — セッション更新・ID突合・件数集計・組み合わせ生成・
   書式チェック・指標算出は決定論的なスクリプトに委譲し、AIはラベル付け・解釈・
   対応方針の判断に集中する。
10. **測るのは件数ではなく規律** — 根拠参照率・**根拠なし事実主張率(目標0%)**・
   トレース率・カバレッジを `metrics.py` で測る。指標を目標にしてはならない。
11. **指示ではなく保証** — 「AIに指示してある」と「機械が保証している」は違う。
   機械判定できる規約(ゲート承認の前提・マスター資産の保護・成果物の書式)は
   hooks で強制し、AIが回避できない位置に置く。ただし**ブロックしてよいのは
   誤検出しない検査だけ**。指摘の妥当性・網羅性は人間の責務のまま置く。
   定義元は [hooks.md](.github/skills/_shared/hooks.md)。
12. **台帳はCSV、叙述はMarkdown、人が読むものは生成物** — ID・traces_to・
   derivation を持つ台帳は `<成果物>/<台帳名>.csv` が正で、`.md` は
   `render_md.py` の生成物。**CSVにしているのは表計算でそのまま開いて
   読み書きするため** — QAの成果物は最後は人がレビューする。分析の解釈・
   判断理由といった叙述を構造化しても何も保証されないので、そこは
   Markdown(`notes.md`)のまま置く。**この分割が「誤検出しない検査」を
   可能にし、hooks がブロックできる根拠になる**(原則11と対になる)。
   規約は [conventions.md §6-2](.github/skills/_shared/conventions.md)。

## 3つの実行モード

モードは「**どこまで根拠に基づくか**」の宣言であり、出力の**限界**を決める。
詳細は [skill-map.md §2](.github/skills/_shared/skill-map.md)。

| モード | 入力 | 出力 | 限界 |
|---|---|---|---|
| **Quick** | ユーザーストーリー・チケットのみ | 観点・ケース | **網羅ではない。** 入力に書かれていない業務知識・状態・ロールは出ない |
| **Grounded**(推奨) | ストーリー + 設計資料 + UI | 根拠付きの戦略・観点・ケース | 業務プロセス・引き継ぎは復元しない |
| **Process** | 要件定義・基本設計一式 | 意図モデル・業務シナリオ・E2Eケース | 資料に無い暗黙知は復元できない(proposed として提案するに留まる) |

## 承認ゲート

| ゲート | 束ねる成果物 | 承認内容 | 想定承認者 |
|---|---|---|---|
| G1 スコープ | (実行計画) | モード・インプット・実行するスキル | 依頼者 |
| G2 根拠と未知 | 00 / 01 / 40 | 何が事実で何が不明か。未解決 Blocker の扱い | BA・仕様担当 |
| G3 意図モデル | 10 / 11 | Actor・業務ゴール・状態遷移・引き継ぎ・完了条件 | PO・業務担当 |
| G4 テスト設計 | 20 / 21 / 30 / 31 | リスク評価・除外範囲・観点・ケース | QA |
| G5 完了 | 42 / 90 | レビュー結果と残リスク・振り返り | 依頼者・QA |

未解決 Blocker・除外範囲の決定・本番データ利用は、ゲートを待たずその場で確認する。

ゲートでの提示は**レビュー依頼**の形にする([gates.md](.github/skills/_shared/gates.md) §4-1)。開くファイルのパス・
見てほしい箇所を3〜7点(各点に「AIの現在の判断」と「なぜ確認が要るか」)・確認不要な範囲
(書式とID突合は `gate_check.py` で検証済み)を書き、同じ質問の選択肢で承認・差し戻しまで
完結させる。ゲートごとに必ず指す箇所は
[skill-map.md §3-1](.github/skills/_shared/skill-map.md)。
**「G3 が未承認なので進めません」で止めない** — 未承認はレビュー依頼を出す合図であって、
停止の理由ではない(gates.md §4-3)。

## インプット資料のMarkdown変換(任意)

仕様書・設計書が Excel / PDF / Word / PowerPoint の場合、AIが直接読むと非効率で
読み落としも起きやすい。[markitdown](https://github.com/microsoft/markitdown) が
使える環境では、各スキルは資料を `qa-output/<セッション名>/sources/` へ Markdown
変換してから読む(手順は
[_shared/source-conversion.md](.github/skills/_shared/source-conversion.md))。

- 導入: `pip install "markitdown[all]"`(Python 3.10+。導入は任意)
- 出典表記は常に原本パス。変換に不安が残る箇所は evidence_level を confirmed にしない
- markitdown が無い環境では原本を直接読む(ワークフローは変わらない)

## 各ツールでの使い方

このディレクトリを各ツールがスキル/指示として読める場所に置く(またはリンクする)。

| ツール | 方法 | 品質ゲート(hooks) |
|---|---|---|
| GitHub Copilot | **専用のカスタムエージェント層 `.github/agents/` を同梱**(VS Code v1.107+)。`.github/skills/` は Copilot の Agent Skills 公式配置でもあるため、各スキルは Copilot から直接発見される。qa-orchestrator が `#tool:agent/runSubagent` で各エージェントを呼び出す。質問ツールは `vscode/askQuestions` | `.github/hooks/qa-quality-gates.json`(CLI / cloud agent / VS Code。VS Code は preview) |
| Claude Code | `.claude/skills/` へリンクするか、プロンプトで `SKILL.md` を直接読ませる。コンテキスト分離は Agent ツール + [subagent-contract.md](.github/skills/_shared/subagent-contract.md)。質問ツールは `AskUserQuestion` | `.claude/settings.json` |
| Cursor / その他 | ルール・コンテキストとして `qa-orchestrator/SKILL.md` を読み込ませれば、残りは相対パスで辿られる | hooks は使えない。`gate_check.py` を手順から呼ぶ + CI |

どのツールでも、スキル機構がない場合は「`.github/skills/qa-orchestrator/SKILL.md` を
読んでその指示に従って」と依頼すれば動作する。

### GitHub Copilot カスタムエージェント層(.github/agents/)

`.github/skills/` の SKILL.md 群を GitHub Copilot のカスタムエージェント +
`#tool:agent/runSubagent` で動かすためのアダプター層。**ファイルは2枚だけ**で、
スキルが増減しても変更されない。

- `qa-orchestrator.agent.md` — 統括役。ユーザーとの対話・ゲート・セッション管理を担う
- `qa-skill-runner.agent.md` — 全スキル共通の汎用ランナー。入力JSONの `skill` が指す
  SKILL.md を読んで実行する。**スキルごとの agent 定義は持たない**(description の
  二重管理が発生しないため)
- **手順の本体はあくまで `.github/skills/<名前>/SKILL.md`**。手順を変えるときは
  SKILL.md 側だけを直す。
- サブエージェントの入出力契約は
  [_shared/subagent-contract.md](.github/skills/_shared/subagent-contract.md)
  にある(ツール非依存。Claude Code の Agent ツールでも同じ契約を使う)。
- 個別スキルを直接使いたいときは、`.github/skills/` が Copilot の Agent Skills 公式
  配置なので、スキル名で直接呼べる(agent 定義は不要)。

**必要環境**: VS Code + GitHub Copilot **v1.107 以降**、および
`settings.json` に `"chat.customAgentInSubagent.enabled": true`
(このリポジトリでは `.vscode/settings.json` に設定済み)。

**設計上の注意**:

- **ユーザーとの対話は qa-orchestrator に集約**している。runSubagent で起動された
  サブエージェントはユーザーに質問できないため、承認・選択が必要な事項は出力 JSON の
  `pending_questions` / `proposals` として親に返し、親が askQuestions で確認してから
  再呼び出しする。
- Premium Requests は指示単位で消費されるため、フルフローは qa-orchestrator への
  一回の指示でまとめて流すのが経済的。その分サブエージェント呼び出しの
  オーバーヘッドで応答時間・総トークンは増える。

## 品質ゲート(hooks)

規約のうち機械判定できるものは hooks で強制している。「AIに指示してある」を
「機械が保証している」に変えるのが目的で、**どの hook が何を保証するかの定義元は
[hooks.md](.github/skills/_shared/hooks.md)**。

| イベント | 保証すること |
|---|---|
| `SessionStart` | 再開可能なセッションを文脈に注入する(再開判定がAI任せにならない) |
| `PreToolUse`(シェル) | ゲート承認の直前に、そのゲートが束ねる成果物を検証する |
| `PreToolUse`(書き込み) | セッション稼働中のマスター資産の書き換えを止める |
| `PostToolUse`(書き込み) | 成果物を書いた直後に書式を検証し、その場でフィードバックする |
| `Stop` / `SubagentStop` | 未承認ゲートに未解消の検出があるうちは終わらせない |

判定の実装は [gate_check.py](.github/skills/_shared/scripts/gate_check.py) の**1本だけ**で、
SKILL.md の手順も hooks も CI も同じものを呼ぶ。hook 設定は各ツールの形式が違うため
2ファイルあるが、配線を持つだけで判定ロジックは持たない。

**止めてよいのは誤検出しない検査だけ。** 誤検出が出たら hook 設定ではなく検査側を
直す(hook で緩めると環境ごとに強制力が変わる)。無限ループを防ぐため、Stop の
連続ブロックには上限がある — 詳細は [hooks.md](.github/skills/_shared/hooks.md)。

hooks が使えない環境でも、[gate_check.py](.github/skills/_shared/scripts/gate_check.py)
を手順から呼ぶ層と CI 層は動く。4層の防御の全体像は
[scripts/README.md](.github/skills/_shared/scripts/README.md) を参照。

## 最初の一歩(PoC)

いきなりフルフローを回すより、価値が出やすい流れから試すのを推奨。

### 業務シナリオ設計を試す(このスキルセットの主目的)

対象には**単純なログインやCRUDを選ばない**。次を満たす業務フロー1本が適している。

- 2〜3ロールが関与する
- 主要オブジェクトに4状態以上ある
- 申請・承認・差戻し・取消がある
- 外部システムまたはバッチ連携が1つある
- DBまたはAPIで業務結果を確認できる

1. `qa-source-analysis`(深さC)で対象機能の事実を集める
2. `qa-intent-recovery` で Actor・状態遷移・引き継ぎを復元する → **G3 で業務担当に承認を取る**
3. `qa-scenario-design` でシナリオを作り、`metrics.py` でカバレッジを見る
4. 同じ資料に対して Quick モードも回し、**何が落ちるか**を比較する

### 回帰観点の蓄積から試す

1. 過去不具合50〜100件をCSVで用意(`id,title,description,feature,severity` 程度でよい)
2. `qa-defect-analysis` を単独実行 → 回帰観点カタログに数エントリ蓄積
   (修正PRも入力に含めると、観点エントリに「発生メカニズム」節 —
   コードがどう壊れると再現するか — が付く。KITE:
   [arXiv:2607.11573](https://arxiv.org/abs/2607.11573) の記録形式の翻案)
3. 実際のテスト設計書に対して `qa-test-design-review` を実行 → カタログの観点と
   発生メカニズムの机上シミュレーションがレビューに効くことを確認

### 品質基準づくりから試す

フェーズ移行判定・リリース判定が迫っている場合は、手元の計画書・要件定義書・仕様書を
入力に `qa-test-strategy` を単独実行すると、品質特性別の品質基準項目・判定基準・
確認方法(確認工程: 設計/UT/IT/ST ラベル付き)が判定材料として得られる。

## スキルセット自体の改修

スキルファイルの編集は各AIツールのスキル編集機能(Claude なら `skill-creator`)に
委譲してよい。ただし**採否の判断基準と履歴は
[maintenance-log.md](.github/skills/_shared/maintenance-log.md) がツール非依存の正**で
あり、ここを飛ばして反映してはならない(1セッションの特殊事情を一般ルール化して
しまう歯止めが、この履歴だけのため)。

構成が変わる変更(スキルの追加・削除・成果物フォーマットの変更)の追随手順は
[skill-map.md §5](.github/skills/_shared/skill-map.md) を参照。
