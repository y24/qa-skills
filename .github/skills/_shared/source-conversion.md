# インプット資料のMarkdown変換(markitdown)

Excel・PDF・Word・PowerPoint などの資料はAIが直接読むと非効率・不正確になりやすい。
コマンド実行と [markitdown](https://github.com/microsoft/markitdown) が使える環境では、
分析に使う前に Markdown へ変換し、以降のフェーズでは変換後ファイルを読む。

このファイルは、インプット資料に変換対象の形式が**含まれる場合のみ**読めばよい
(conventions.md §10)。

## 変換対象

- `.xlsx` / `.xls` / `.docx` / `.pptx` / `.pdf` など、テキストとして直接読めない形式。
- Markdown・プレーンテキストはそのまま使う。
- **不具合CSVは変換しない**(`defect_stats.py` が原本CSVを前提とするため)。

## 変換先とコマンド

変換先は `qa-output/<セッション名>/sources/<元ファイル名>.md`。
成果物(conventions.md §6)ではなく、原本から再生成できる中間ファイルとして扱う。

```
markitdown "docs/仕様書.xlsx" -o "qa-output/<セッション名>/sources/仕様書.xlsx.md"
```

導入は `pip install "markitdown[all]"`(Python 3.10+)。
conventions.md §9 のスクリプトと異なり外部パッケージであり、
導入するかはプロジェクト側の任意。

## 変換後の確認

変換直後に内容を一読し、次がないかを確認する:

1. 空出力・文字化け
2. 表の崩れ(Excelの結合セル等)
3. スキャンPDF(OCRされず本文が出ない)

問題がある部分は原本の該当箇所を直接確認するか、別形式での提供をユーザーに依頼する。

## セッションへの記録

qa-orchestrator 経由の場合、`add-input` は**原本パス**で登録し、`--converted` に
変換後パスを記録する(session-schema.md の `converted_path`)。
以降のフェーズには変換後パスを渡す。

## 出典の書き方

成果物の `sources`(conventions.md §5)には**原本のパス**を書く
(真実の源は原本。変換後ファイルは中間物)。
変換品質に不安が残る箇所だけを根拠にした指摘は evidence_level を confirmed にしない。

## フォールバック

markitdown もコマンド実行も使えない環境では、読める範囲で原本を直接読むか、
変換済みテキストの提供をユーザーに依頼する。
変換は補助であり、ワークフロー自体は変わらない(conventions.md §9 と同じ方針)。
