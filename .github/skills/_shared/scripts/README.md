# 補助スクリプト(定型はスクリプト、判断はAI)

QAスキル群のワークフローのうち、**入出力が決まっていて繰り返し発生する定型処理**を LLMの手作業から切り出したスクリプト群。LLMにやらせると壊れやすい・間違えやすい処理 (ファイル更新・ID突合・件数集計・組み合わせ生成・書式チェック)を決定論的に行い、AIはラベル付け・解釈・対応方針の判断に集中する。運用規約は [conventions.md §9](../conventions.md) を参照。

## 動作要件

- Python 3.9+(**標準ライブラリのみ**。追加インストール不要)
- Windows / macOS / Linux 対応(コンソール・ファイルI/OはUTF-8を明示。不具合CSVは cp932 / UTF-8 を自動判別)
- Python が使えない環境では各 SKILL.md の手順を手動で行う(スクリプトは補助であり、ワークフロー自体は変わらない)

## 一覧

| スクリプト | 用途 | 利用箇所 |
|---|---|---|
| [qa_session.py](qa_session.py) | qa-session.json の作成・更新・再開判定。タイムスタンプ付与・status検証・アトミック書き込みを保証 | qa-orchestrator(全フェーズ境界) |
| [defect_stats.py](defect_stats.py) | `normalize`: 不具合CSV→ラベル雛形YAML生成 / `stats`: ラベル付け後の4軸分布・クロス集計 | qa-defect-analysis 手順1・3 |
| [pairwise.py](pairwise.py) | ペアワイズ(全ペア網羅)組み合わせ生成。決定論的・生成後に自己検証。禁止ペア制約対応 | qa-test-case-design 手順2 |
| [trace_check.py](trace_check.py) | 成果物間のID突合: 観点⇄ケースの孤児参照、導出元欠落、未確認QC基準、AMB参照切れ、ID重複 | qa-test-viewpoint 手順6 / qa-test-case-design 手順5 / qa-test-design-review 手順0 |
| [lint_output.py](lint_output.py) | 成果物の必須セクション・evidence_level付与漏れ・ID書式・曖昧語のチェック | 全スキル(承認ゲート前)/ qa-improvement 手順2 |

各スクリプトの詳細な使い方は `python <スクリプト> --help` と冒頭の docstring を参照。

## 使用例

```bash
# セッション管理(qa-orchestrator)
python .github/skills/_shared/scripts/qa_session.py resume-info qa-output
python .github/skills/_shared/scripts/qa_session.py init qa-output/my-session --name my-session --feature "請求書エクスポート"
python .github/skills/_shared/scripts/qa_session.py set-status qa-output/my-session 1 approved --output 01-defect-analysis.md

# 不具合分析(qa-defect-analysis)
python .github/skills/_shared/scripts/defect_stats.py normalize defects.csv -o labeled.yaml
python .github/skills/_shared/scripts/defect_stats.py stats labeled.yaml

# ペアワイズ生成(qa-test-case-design)
python .github/skills/_shared/scripts/pairwise.py params.json --format md

# トレーサビリティ検証・書式チェック
python .github/skills/_shared/scripts/trace_check.py qa-output/my-session
python .github/skills/_shared/scripts/lint_output.py --session-dir qa-output/my-session
```

## 責務の境界

スクリプトの出力は機械処理の結果にすぎない。

- **スクリプトが保証する**: 突合・集計の正確さ、生成の網羅性、ファイルの整合
- **AIと人間が判断する**: ラベルの妥当性、検出への対応要否、集計結果の意味づけ、組み合わせ対象パラメータの選定

## 保守

スクリプトはマスター資産(conventions.md §8)。配布先のセッション内では変更せず、不具合・改善は qa-improvement の振り返りレポート経由でメンテナーに提案し、qa-skillset-maintenance で採否を検討・反映する。

`lint_output.py` は各成果物の必須セクション対応表をスクリプト内の対応表として持つため、**各 SKILL.md の出力フォーマットを変更したら lint_output.py の対応表も追随させること** (各エントリに出典コメントあり)。
