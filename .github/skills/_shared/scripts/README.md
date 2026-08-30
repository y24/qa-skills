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
| [defect_stats.py](defect_stats.py) | `normalize`: 不具合CSV→ラベル雛形YAML生成 / `stats`: ラベル付け後の4軸分布・クロス集計 | qa-defect-analysis 手順1・3 |
| [pairwise.py](pairwise.py) | ペアワイズ(全ペア網羅)組み合わせ生成。決定論的・生成後に自己検証。禁止ペア制約対応 | qa-test-case-design 手順2 |
| [trace_check.py](trace_check.py) | 成果物間のID突合: 意図モデル⇄シナリオ⇄観点⇄ケースの孤児参照、導出元欠落、未確認QC基準、AMB参照切れ、ID重複 | qa-intent-recovery / qa-scenario-design / qa-test-viewpoint / qa-test-case-design / qa-test-design-review |
| [lint_output.py](lint_output.py) | 成果物の必須セクション・evidence_level・derivation の付与漏れ・ID書式・曖昧語のチェック | 全スキル(要約提示前)/ qa-improvement 手順2 |
| [metrics.py](metrics.py) | conventions.md §11 の指標算出: 根拠参照率・根拠なし事実主張率・トレース率・モデル/シナリオ種別カバレッジ・業務オラクル保有率 | qa-improvement 手順2 / qa-scenario-design 手順7 / qa-test-design-review 手順0 |

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
python .github/skills/_shared/scripts/defect_stats.py normalize defects.csv -o labeled.yaml
python .github/skills/_shared/scripts/defect_stats.py stats labeled.yaml

# ペアワイズ生成(qa-test-case-design)
python .github/skills/_shared/scripts/pairwise.py params.json --format md

# トレーサビリティ検証・書式チェック・指標算出
python .github/skills/_shared/scripts/trace_check.py qa-output/my-session
python .github/skills/_shared/scripts/lint_output.py --session-dir qa-output/my-session
python .github/skills/_shared/scripts/metrics.py qa-output/my-session
```

## 責務の境界

スクリプトの出力は機械処理の結果にすぎない。

- **スクリプトが保証する**: 突合・集計の正確さ、生成の網羅性、ファイルの整合
- **AIと人間が判断する**: ラベルの妥当性、検出への対応要否、集計結果の意味づけ、組み合わせ対象パラメータの選定

## 保守

スクリプトはマスター資産(conventions.md §8)。配布先のセッション内では変更せず、不具合・改善は qa-improvement の振り返りレポート経由でメンテナーに提案し、[maintenance-log.md](../maintenance-log.md) のトリアージを経て反映する。

スキルの追加・削除・成果物フォーマットの変更をしたときの追随手順は [skill-map.md §5](../skill-map.md) を参照。`lint_output.py` は必須セクション対応表を、`trace_check.py` / `metrics.py` は ID 体系(conventions.md §6-1)を持つため、**定義元を変えたらこれらも追随させること**(各エントリに出典コメントあり)。

`metrics.py` は表の解析に `trace_check.py` の関数を import する(同一ディレクトリ配置が前提)。
