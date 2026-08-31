# 補助スクリプト(定型はスクリプト、判断はAI)

QAスキル群のワークフローのうち、**入出力が決まっていて繰り返し発生する定型処理**を LLMの手作業から切り出したスクリプト群。LLMにやらせると壊れやすい・間違えやすい処理 (ファイル更新・ID突合・件数集計・組み合わせ生成・書式チェック)を決定論的に行い、AIはラベル付け・解釈・対応方針の判断に集中する。運用規約は [conventions.md §9](../conventions.md) を参照。

## 動作要件

- Python 3.9+(**標準ライブラリのみ**。追加インストール不要)
- Windows / macOS / Linux 対応(コンソール・ファイルI/OはUTF-8を明示。不具合CSVは cp932 / UTF-8 を自動判別)
- Python が使えない環境では各 SKILL.md の手順を手動で行う(スクリプトは補助であり、ワークフロー自体は変わらない)

## 一覧

| スクリプト | 用途 | 利用箇所 |
|---|---|---|
| [qa_session.py](qa_session.py) | qa-session.json の作成・更新・再開判定。インプット・ステップは一括投入(`--item` / `--steps`) | qa-orchestrator(計画作成時・完了時・ゲート通過時) |
| [defect_stats.py](defect_stats.py) | `inspect`: 不具合CSVの列の下見 / `normalize`: ラベル列付き台帳CSVへ変換(**持ち越す列はAIが選ぶ**) / `stats`: 4軸分布・任意列の分布・クロス集計 / `table`: 台帳CSV→Markdown表 | qa-defect-analysis 手順1・3 |
| [pairwise.py](pairwise.py) | ペアワイズ(全ペア網羅)組み合わせ生成。決定論的・生成後に自己検証。禁止ペア制約対応 | qa-test-case-design 手順2 |
| [trace_check.py](trace_check.py) | 成果物間のID突合: 意図モデル⇄シナリオ⇄観点⇄ケースの孤児参照、導出元欠落、未確認QC基準、AMB参照切れ、ID重複 | qa-intent-recovery / qa-scenario-design / qa-test-viewpoint / qa-test-case-design / qa-test-design-review |
| [lint_output.py](lint_output.py) | 成果物の必須セクション・evidence_level・derivation の付与漏れ・ID書式・曖昧語のチェック | 全スキル(要約提示前)/ qa-improvement 手順2 |
| [metrics.py](metrics.py) | conventions.md §11 の指標算出: 根拠参照率・根拠なし事実主張率・トレース率・モデル/シナリオ種別カバレッジ・業務オラクル保有率 | qa-improvement 手順2 / qa-scenario-design 手順7 / qa-test-design-review 手順0 |
| [gate_check.py](gate_check.py) | **検証の単一入口。** lint・ID突合・スキーマ検証・レンダリング一致を承認ゲート単位で束ねる。判定基準を1箇所に閉じるためのもの | SKILL.md の手順 / hooks / CI(すべてここを呼ぶ) |
| [hook_entry.py](hook_entry.py) | hooks アダプタ。各AIツールの hook 入出力方言を吸収して `gate_check.py` を呼び、終了コードに変換する。**判定ロジックは持たない** | hook 設定(`.github/hooks/*.json` / `.claude/settings.json`) |
| [miniyaml.py](miniyaml.py) | スキーマ(YAML)を読む限定パーサー(PyYAML不要)。**真のYAMLの厳密なサブセット**であることをCIで検査している | validate_artifact / render_md |
| [normalize_ledger.py](normalize_ledger.py) | 台帳CSVの正規化。`&#10;` のまま書き出されたセル内改行を実改行に戻し、表計算で開ける形(BOM付きUTF-8 + CRLF)に揃える。`--check` で検出のみ | 台帳系スキル(CSVを書いた直後・検証の前) |
| [validate_artifact.py](validate_artifact.py) | 台帳CSVを `_shared/schemas/` のスキーマで検証。ID書式・必須・許容値・**出典のない explicit 項目**(conventions.md §5-3) | 台帳系スキル(成果物を書いた直後) |
| [render_md.py](render_md.py) | 台帳CSV + notes.md から人間向け Markdown を生成。**`derivation: proposed` を機械的に別表へ分ける**。`--check` でずれを検出 | 同上 / gate_check / CI |

各スクリプトの詳細な使い方は `python <スクリプト> --help` と冒頭の docstring を参照。

## 使用例

```bash
# セッション管理(qa-orchestrator)
python .github/skills/_shared/scripts/qa_session.py resume-info qa-output
python .github/skills/_shared/scripts/qa_session.py init qa-output/my-session --name my-session --feature "請求書の申請・承認" --run-mode process
# インプットとステップは一括投入する(1件ずつ呼ばない)
python .github/skills/_shared/scripts/qa_session.py add-input qa-output/my-session --item "spec:docs/design.md:基本設計書" --item "code:src/:対象コード"
python .github/skills/_shared/scripts/qa_session.py add-phase qa-output/my-session --steps qa-source-analysis:G2 --steps qa-intent-recovery:G3 --steps qa-test-viewpoint:G4
python .github/skills/_shared/scripts/qa_session.py set-status qa-output/my-session 1 approved --output 00-source-analysis.md
python .github/skills/_shared/scripts/qa_session.py set-gate qa-output/my-session G2 approved

# 不具合分析(qa-defect-analysis)
# 列を下見し、分析に使う列を選んで台帳CSVにする(--keep 省略時は全列を持ち越す)
python .github/skills/_shared/scripts/defect_stats.py inspect bugs.csv
python .github/skills/_shared/scripts/defect_stats.py normalize bugs.csv --keep 画面名 -o defects.csv
# ラベルを埋めたあと。持ち越した列も集計軸にできる
python .github/skills/_shared/scripts/defect_stats.py stats defects.csv --by 画面名 --cross 画面名:test_gap
python .github/skills/_shared/scripts/defect_stats.py table defects.csv --columns id,title,type,test_gap

# ペアワイズ生成(qa-test-case-design)
python .github/skills/_shared/scripts/pairwise.py params.json --format md

# トレーサビリティ検証・書式チェック・指標算出
python .github/skills/_shared/scripts/trace_check.py qa-output/my-session
python .github/skills/_shared/scripts/lint_output.py --session-dir qa-output/my-session
python .github/skills/_shared/scripts/metrics.py qa-output/my-session

# ゲート単位の検証(lint + trace + スキーマ + レンダリング一致をまとめて)
python .github/skills/_shared/scripts/gate_check.py qa-output/my-session --gate G4
python .github/skills/_shared/scripts/gate_check.py qa-output/my-session --unapproved
python .github/skills/_shared/scripts/gate_check.py --files qa-output/my-session/30-test-viewpoint.md

# 構造化成果物(台帳CSVが正・Markdownは生成物 — conventions.md §6-2)
python .github/skills/_shared/scripts/normalize_ledger.py qa-output/my-session/30-test-viewpoint
python .github/skills/_shared/scripts/validate_artifact.py qa-output/my-session/30-test-viewpoint
python .github/skills/_shared/scripts/render_md.py qa-output/my-session/30-test-viewpoint
python .github/skills/_shared/scripts/render_md.py --session-dir qa-output/my-session --check
```

## 構造化成果物(台帳はCSV、Markdownは生成物)

観点一覧・テストケースのような**台帳系の成果物**は、成果物ごとのディレクトリに台帳CSVと `notes.md` を置き、そこから `.md` を生成する(規約は conventions.md §6-2)。

```
qa-output/<セッション名>/
  30-test-viewpoint/
    viewpoints.csv     ← 台帳。表計算でそのまま開ける
    notes.md           ← 叙述
  30-test-viewpoint.md ← 生成物。人間が読むのはこれ
```

**台帳にするのは、他の成果物がIDを参照するか、機械チェックが列に依存するものだけ**(conventions.md §6-2)。それ以外の表は `notes.md` の中に書く。この基準で、セッション全体の台帳は6枚に収まる — 意図モデル3(Actor / 遷移 / 業務ゴール)、シナリオ1、観点1、ケース1。仕様レビュー・設計レビューは構造化せず Markdown を直接書く(AMB参照の実在確認は `trace_check.py` が正規表現で行っている)。

なぜこの形か。

- **表計算で読み書きできる。** QAの成果物は最後は人がレビューし、しばしば手で直す。1台帳=1CSVなら Excel / スプレッドシートでそのまま開ける(BOM付きUTF-8で書き、Excel が保存する cp932 も読める)。
- **誤検出しない検査ができる。** Markdown を字面で読む `lint_output.py` は列名の一致やキーワード推定に頼るため、誤検出を避けようとすると WARN 止まりになる。列を直接見るスキーマ検証は誤検出しないので、**hook でブロックできる**(hooks.md §1)。
- **規約が構造的な保証になる。** conventions.md §5-3 の「proposed を混ぜない」は散文の指示だったが、`render_md.py` が `derivation` 列を見て機械的に別表へ出すので、混ぜること自体ができなくなる。「explicit なのに出典がない」も、指標で事後に測るのではなくスキーマ検証でエラーになる。
- **LLMが書くファイルからYAMLが消える。** 自前パーサー(`miniyaml.py`)が読むのはメンテナーが書くスキーマだけになり、インデント崩れのような壊れ方の面が減る。

スキーマは [_shared/schemas/](../schemas/) にあり、台帳・列・必須・許容値・Markdown の構成を定義する。**スキーマの無い成果物は従来どおり `.md` を直接書く**(両方が共存する)。不具合分析の `01-defect-analysis/defects.csv` はこちら側 — 集計と転記防止のための**作業台帳**であり、スキーマ検証・レンダリングの対象ではない(`.md` は直接書く)。

厳密に列へ割り切らない箇所もある。シナリオの手順のように「1件が複数行を持つ」データは、子テーブルへ正規化せず**セル内改行(Excel なら Alt+Enter)で1行=1ステップ**として持つ。多少のファジーさと引き換えに、表計算で書けることを優先している。

AIツールがCSVを書き出すと、このセル内改行が `&#10;`(数値文字参照)のまま残ることがある。そのままでは表計算で1行に潰れて読めないので、**書いた直後に `normalize_ledger.py` をかけて実改行に戻す**。かけ忘れは `validate_artifact.py` が `escaped_newline` で落とすので、hook・CI からも同じ判定が効く。

## 4層の防御(検証はどこで効くか)

同じ判定を4つの層で重ねる。**判定の実装は `gate_check.py` の1本だけ**で、どの層もそれを呼ぶ。1箇所で判定基準が決まるので、層が増えても定義は二重化しない(skill-map.md §5 と同じ考え方)。

| 層 | 実体 | 効く環境 | 強制力 |
|---|---|---|---|
| 1. 手順 | 各 SKILL.md の「機械確認」ステップ | すべて | なし(AIが従うかどうかに依存する) |
| 2. 単一入口 | `gate_check.py` | Python が使えるすべて | 呼べば確実 |
| 3. hooks | `hook_entry.py`(hook 設定から起動) | Claude Code / Copilot CLI / Copilot cloud agent / VS Code(preview) | AIが回避できない |
| 4. CI | [.github/workflows/qa-artifacts.yml](../../../workflows/qa-artifacts.yml) | PRを出すなら常に | 最終防衛 |

**どの hook が何を保証するかの定義元は [hooks.md](../hooks.md)。** 判定の実装は `gate_check.py` の1本だけで、どの層もそれを呼ぶ。

**CI は成果物だけでなく検証層自身も検査する。** `gate_check.py` が誤って PASS を返すようになると全ゲートが黙って無効になるため、欠陥を仕込んだフィクスチャで「検出できること」と「規約どおりの成果物を誤検出しないこと」の両方を毎回確かめている。

### 誤検出が出たとき

**hook 設定ではなく検査側を直す。** `gate_check.py` / `lint_output.py` / `trace_check.py` / `validate_artifact.py` のいずれかの欠陥として `maintenance-log.md` のトリアージに乗せる。hook 側で緩めると環境ごとに強制力が変わり、「どこで動かしたか」で結果が変わるようになる。

## 責務の境界

スクリプトの出力は機械処理の結果にすぎない。

- **スクリプトが保証する**: 突合・集計の正確さ、生成の網羅性、ファイルの整合
- **AIと人間が判断する**: ラベルの妥当性、検出への対応要否、集計結果の意味づけ、組み合わせ対象パラメータの選定

## 保守

スクリプトはマスター資産(conventions.md §8)。配布先のセッション内では変更せず、不具合・改善は qa-improvement の振り返りレポート経由でメンテナーに提案し、[maintenance-log.md](../maintenance-log.md) のトリアージを経て反映する。

スキルの追加・削除・成果物フォーマットの変更をしたときの追随手順は [skill-map.md §5](../skill-map.md) を参照。`lint_output.py` は必須セクション対応表を、`trace_check.py` / `metrics.py` は ID 体系(conventions.md §6-1)を、`gate_check.py` は**ゲートが束ねる成果物の対応表**(skill-map.md §3)を持つため、**定義元を変えたらこれらも追随させること**(各エントリに出典コメントあり)。

`gate_check.py` のゲート対応表はセッションファイルが無いときのフォールバックにすぎない。通常は `qa-session.json` の `plan`(各ステップの `gate` と `output`)が正として使われる。

`metrics.py` は表の解析に `trace_check.py` の関数を import する(同一ディレクトリ配置が前提)。
