# 答えキー: 購買申請システム(PRQ)

[fixtures/prq/](../../fixtures/prq/) に仕込んだ項目の正解。**評価ランに読ませてはならない**(読ませた時点で検出率は意味を失う)。照合は [eval/scripts/eval_score.py](../../scripts/eval_score.py) が行う。

## 台帳

| ファイル | カテゴリ | 件数 | 照合先の成果物 |
|---|---|---|---|
| [ambiguities.csv](ambiguities.csv) | `ambiguity` | 12 | `40-spec-review*.md` / `42-test-design-review.md` |
| [transitions.csv](transitions.csv) | `transition` | 13 | `10-intent-recovery.md` |
| [handoffs.csv](handoffs.csv) | `handoff` | 6 | `10-intent-recovery.md` / `11-scenario-design.md` |
| [scenarios.csv](scenarios.csv) | `scenario` | 10 | `11-scenario-design.md` |
| [regressions.csv](regressions.csv) | `regression` | 6 | `01-defect-analysis.md` / `30-test-viewpoint.md` |

## 列

| 列 | 内容 |
|---|---|
| `id` | キーのID(`AMB-K01` 等)。成果物側のIDとは無関係 |
| `category` | 上表のカテゴリ。照合先と「エントリの目印」を決める |
| `title` | 仕込んだ項目の内容 |
| `target` | 照合先の上書き(セッションディレクトリからの glob を `;` 区切り)。空欄ならカテゴリ既定 |
| `match` | 照合条件。`;` 区切りのグループ**すべて**が1レコード内に必要で、グループ内の `\|` は別表記 |
| `difficulty` | A=文書間の明示的な矛盾 / B=記述の欠落 / C=資料に手掛かりが薄い暗黙知 |
| `rationale` | 仕込みの意図と、資料上の根拠 |

照合の前に、全角/半角・大文字小文字・空白・カンマは正規化で吸収される(`10万` = `１０万`、`100,000` = `100000`)。

## 難易度の考え方

| 難易度 | 何を測っているか |
|---|---|
| **A** | 資料を突き合わせれば分かる。**ここが落ちるのは読み落とし**で、手順の問題として直せる |
| **B** | 業務の流れを最後まで追うと「決まっていない」ことに気づく。読解ではなく**業務モデルを組み立てたか**を測る |
| **C** | 設計文書に手掛かりがなく、運用手順書や過去不具合からしか導けない。**このスキルセットが狙う空白そのもの**。C の検出率が上がることが本命の指標 |

A が落ちているうちに C を追わない。A → B → C の順に潰す。

## 既知の「境界例」

答えキーに入れていないが、資料上は指摘されうる項目。未照合エントリに出てきても誤指摘とは限らない。

- `screen-spec.md` SCR-04 の「一次承認の完了後に表示名を『一次承認済』に切り替える」は、`basic-design.md` §2 の状態一覧に無い表示名である。画面固有の表示と読めば矛盾ではなく、状態の定義元が2つあると読めば矛盾になる。
- `operation-manual.md` の運用(代理は取消を行わない・年度末は起票を控える)を PRQ の仕様として扱った指摘は**誤指摘**。あれは現行の紙運用の記述である。
- `defects.csv` の個別不具合をそのまま観点にしたもの(「BUG-1020 のページングを確認する」等)は、回帰観点としては粒度が細かい。キーは型(クラスタ)で持っている。

## 更新するとき

- 追加は「資料に根拠がある」ものだけ。`rationale` に根拠のファイル名と節を必ず書く。
- 増減したら `eval/runs/runs.csv` の当該ランの `note` に記録する。**母数が変わると前後のランの検出率は比較できない**([eval/README.md](../../README.md) §7)。
- `match` を緩めるときは、緩めた語が別のキーに当たらないかを確認する。確認は `eval/scripts/eval_score.py selftest` ではなく、過去ランの再採点(`--no-metrics` を付ければ速い)で行う。
