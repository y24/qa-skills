---
name: qa-defect-analysis
description: 過去の不具合一覧を分類・クラスタリングし、根本原因とテストギャップを分析して回帰テスト観点を導出する。
---

# 不具合分析と回帰観点導出

過去の失敗をテスト設計能力に変換するスキル。不具合の分類 → パターン抽出 →
テストギャップ分析 → 回帰観点カタログへの還元、までを1本の流れで行う。

## 実行前に読むこと

- [_shared/conventions.md](../_shared/conventions.md)
- [_shared/references/defect-taxonomy.md](../_shared/references/defect-taxonomy.md)(分類軸)
- [_shared/references/regression-viewpoint-catalog.md](../_shared/references/regression-viewpoint-catalog.md)(既存カタログ)

## 入力

- 不具合一覧(CSV / Markdown / チケットのエクスポート)。最低限 ID・タイトル・説明があればよい。
- (あれば)修正PR、対象機能一覧、既存テストケース。

入力に無い項目(根本原因・混入工程など)は推測で埋めてよいが、
必ず `evidence_level: hypothesis` を付ける。

## 手順

1. **正規化**: CSV入力の場合、まず
   `python .github/skills/_shared/scripts/defect_stats.py normalize <csv>` で
   ID・タイトル入りのYAML雛形を生成する(転記ミス・件数の取りこぼしを防ぐ。
   cp932/UTF-8 自動判別)。その雛形に対し、defect-taxonomy.md の4軸
   (種類/混入工程/検出工程/テストギャップ)のラベルを埋める — ここが判断であり
   AIの仕事。判断根拠が薄いものは hypothesis とする。
2. **クラスタリング**: 類似不具合をグループ化する。軸は「同じ発生条件」「同じ機能」
   「同じ根本原因パターン」。1件だけのクラスタも許容する。
3. **傾向分析**: ラベル付け済みYAMLを
   `python .github/skills/_shared/scripts/defect_stats.py stats <yaml>` で機械集計し、
   件数・4軸の分布・種類×テストギャップのクロス集計はその数値を正とする
   (LLMが数え直さない。埋め漏れもここで検出される)。その上で頻出パターン上位を
   特定し、次を整理する。
   - 発生しやすい条件(境界・状態・データ量・環境)
   - 流出原因(テストギャップ軸の分布)
   - 影響機能の偏り
4. **回帰観点の導出**: 主要クラスタごとに regression-viewpoint-catalog.md の書式で
   観点エントリを作成する。**横展開対象**(同じパターンが潜んでいそうな他機能)を必ず考える。
5. **カタログ更新の提案**: 新規・更新エントリをユーザーに提示し、承認されたものを
   regression-viewpoint-catalog.md に追記する。

## 出力フォーマット(NN-defect-analysis.md)

```markdown
# 不具合分析レポート: <対象>

## 1. サマリー(3〜5行)

## 2. 分類結果
(YAMLブロック: 全件のラベル付き一覧)

## 3. クラスタと頻出パターン
| クラスタ | 件数 | 代表チケット | 発生条件 | テストギャップ |

## 4. 根本原因の仮説
(各仮説に evidence_level と sources を必ず付ける)

## 5. 導出した回帰テスト観点
(カタログ書式のエントリ。根拠チケットID必須)

## 6. 不足情報・次のアクション
```

## 品質基準

- 根拠チケットIDのない回帰観点を作らない。
- 「テストを増やすべき」で終わらせず、必ず「どの条件を・どの機能で」まで具体化する。
- confirmed と hypothesis を同じ表に混ぜて並べない。
