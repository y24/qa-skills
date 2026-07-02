# ドメイン知識ソース(LLM-wiki 連携)

ドメイン知識の正は、このスキルセットの外にある **LLM-wiki**(LLMが編纂・保守する
相互リンクされたMarkdown群。index.md / log.md / schema文書を持つ)とする。
全スキルは、ドメイン用語・業務ルール・機能仕様の背景を調べるとき、このファイルの
プロトコルに従って wiki を参照する。

## 設定

<!-- ユーザー環境に合わせて記入する。未記入の場合 qa-orchestrator が初回ヒアリングで
     確認し、承認を得てここに追記する。 -->

```yaml
wiki:
  path:            # 例: D:/knowledge/wiki(wikiディレクトリの絶対パス)
  index:           # 例: index.md(pathからの相対。カタログファイル)
  schema:          # 例: CLAUDE.md / AGENTS.md(wiki自身の規約文書)
  search_tool:     # 例: qmd / Select-String(PowerShell標準のフォールバック)
fallback:
  glossary: _shared/references/domain-glossary.md   # wiki未設定時・未収載時の簡易用語集
```

## 参照プロトコル(トークン効率の高い順に試す)

1. **index ファースト**: まず wiki の index.md だけを読み、関係しそうなページを特定する。
   wiki 全体や複数ページをまとめて読み込まない。
2. **必要ページのみ読む**: 特定したページを読む。ページ内の `[[リンク]]` は、今の調査に
   必要なものだけを最大2ホップまで辿る(芋づる式の全読みをしない)。
3. **全文検索フォールバック**: index で見つからない用語は、wiki ディレクトリを用語
   (と表記ゆれ候補)で全文検索する。エージェントに検索ツール(Grep等)が組み込まれて
   いればそれを使い、なければ PowerShell で検索する:

   ```powershell
   Get-ChildItem -Path <wikiパス> -Recurse -Filter *.md | Select-String -Pattern "<用語>" -List
   ```

4. **検索ツール**: `search_tool` に qmd 等の専用ツールが設定されている場合は、
   全文検索より優先して使う。
5. **未収載の確定**: 手順3〜4でも見つからなければ「wiki未収載」と判断し、
   成果物に不足情報として明記した上で、用語インボックス(後述)に記録する。

wiki が未設定の環境では、fallback の domain-glossary.md のみを参照する。

## 証拠レベルの扱い(conventions.md §5 の適用)

wiki は LLM が原典から編纂した**二次情報**である。QAの成果物では次のように扱う:

- wiki の記述に基づく事実 → `evidence_level: likely`、`sources: [wiki:<ページパス>]`
- wiki ページが原典(raw source・仕様書)を引用しており、**原典側を直接確認できた**場合
  のみ `confirmed`(sources には原典を書く)
- wiki と仕様書・コードが**矛盾**する場合: どちらかを黙って採用せず、矛盾自体を成果物の
  要確認事項として記録する(wiki 側の lint 対象になる情報なので、qa-improvement が
  ingest候補として回収する)

## 書き込み禁止と還元ルール

- **QAスキルは wiki を直接編集しない。** wiki は自身の schema 文書に従う独立した
  保守フロー(ingest / lint)を持つ。外部から勝手に書くと wiki の一貫性が壊れる。
- セッション中に得たドメイン知識は、次の2経路で wiki に還元する:
  1. **用語インボックス**: 未収載の用語・業務ルールは
     [domain-glossary.md](references/domain-glossary.md) の「wiki ingest 待ち」節に
     出典付きで記録する。
  2. **成果物のingest候補**: セッション成果物のうち wiki に載せる価値があるもの
     (不具合傾向、仕様曖昧箇所の確定結果、機能調査で判明した実装仕様など)は、
     qa-improvement が最後に一覧化する。
- 実際の ingest はユーザーが wiki 側のワークフローで行う(または wiki 保守用の
  エージェントセッションに渡す)。QAスキルの責務は**候補を出典付きで揃える**ところまで。
