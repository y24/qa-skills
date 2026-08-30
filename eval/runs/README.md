# ラン台帳

評価ランの記録。`eval_score.py score --append eval/runs/runs.csv --out eval/runs/<run-id>.json` が書き込む。**追記のみで、過去の行を書き換えない。**

- `runs.csv` — 1ラン=1行の要約。ラン間の比較(`eval_score.py compare`)はここを読む
- `<run-id>.json` — そのランの明細(キーごとの検出可否・照合された抜粋・未照合エントリ)。診断はこちらを読む

## runs.csv の列

| 列 | 内容 |
|---|---|
| `run_id` | ラン識別子。ラウンド番号など |
| `date` | 採点日時 |
| `fixture` | 使ったフィクスチャ(答えキーのディレクトリ名) |
| `session_dir` | 成果物の置き場所 |
| `run_mode` | `quick` / `grounded` / `process` |
| `model` | 使用モデル。**これが違うランは比較しない** |
| `skillset_rev` | スキルセットのコミット(`git rev-parse --short HEAD`) |
| `recall_overall` | 全体検出率(%) |
| `recall_ambiguity` / `recall_transition` / `recall_handoff` / `recall_scenario` / `recall_regression` | カテゴリ別検出率(%) |
| `recall_a` / `recall_b` / `recall_c` | 難易度別検出率(%)。**C の推移が本命** |
| `unmatched` | 未照合エントリ数。検出率と対で見る(README §5) |
| `groundless_rate` | 根拠なし事実主張率(%)。目標 0% |
| `trace_rate` | トレース率(%) |
| `gates_approved` | 承認済みゲート数 |
| `loopbacks` | ループバック回数(`decisions` から推定) |
| `hits` | カテゴリ別の 検出/期待(人が読む用) |
| `note` | 条件の変更。**答えキーを増減したら必ずここに記録する**(母数が変わると比較が成立しない) |

比較の前提が変わる変更(答えキーの増減・フィクスチャの改訂・モデル変更)は、`note` に残したうえで**ベースラインを引き直す**。
