# 外部ナレッジベース連携(任意)

ドメイン知識が多いプロダクトでは、用語集1ファイル
([references/domain-glossary.md](references/domain-glossary.md))に収まらない。
そうしたプロジェクト向けに、**OKF × LLM Wiki 形式で構築したQAナレッジベース(以下 KB)**
を追加のドメイン知識ソースとして参照できる。

**KB は必須ではない。** 未設定のプロジェクトではこのファイルを無視し、
domain-glossary.md だけを使えばよい。KB がある場合も、用語の追記先・インボックスは
引き続き domain-glossary.md とする(KB へ直接書かない。理由は後述)。

## 設定

<!-- KB があるプロジェクトでのみ記入する。qa-orchestrator の初期ヒアリングで
     「ドメインナレッジベース」がインプットに選ばれたら、承認を得てここに追記する。 -->

```yaml
kb:
  path:        # 例: D:/knowledge/my-product(KBリポジトリの絶対パス)
```

`path` が未記入なら KB 連携は無効。以降の記述はすべて設定済みの場合のみ適用する。

## KB の構造(前提)

KB は独立したリポジトリで、次の構造を持つ:

```
<path>/
  AGENTS.md         KB 自身の運用ルール
  index.md          ルートナビゲーション(まずここを読む)
  log.md            変更ログ(追記のみ)
  sources/          一次情報(仕様書・議事録など。不変)
  knowledge/        コンセプト群(1コンセプト = 1 Markdown、frontmatter 付き)
    features/       機能仕様(何をするか、入出力、正常系/異常系)
    glossary/       用語・概念の定義
    rules/          業務ルール(制約・上限値・バリデーション)
    decisions/      仕様決定の背景(なぜその仕様か)
```

各コンセプトの frontmatter には `type` / `confidence`(verified | inferred | unverified)/
`sources`(出所)が付いている。各ディレクトリに目次 `index.md` がある。

## 参照プロトコル(トークン効率の高い順に試す)

1. **index ファースト**: `<path>/index.md` → 関係するカテゴリの
   `knowledge/<dir>/index.md` だけを読み、必要なコンセプトを特定する。
   KB 全体や複数ページをまとめて読み込まない。
2. **必要コンセプトのみ読む**: 特定したファイルを読む。ページ内のリンクは、今の調査に
   必要なものだけを最大2ホップまで辿る(芋づる式の全読みをしない)。
3. **全文検索フォールバック**: index で見つからない用語は、`knowledge/` 配下を用語
   (と表記ゆれ候補)で全文検索する。
4. **未収載の確定**: 手順3でも見つからなければ「KB未収載」と判断し、成果物に不足情報
   として明記した上で、domain-glossary.md の「KB ingest 待ち」節に記録する。

## 使いどころ(何を調べるとき、どこを見るか)

| 知りたいこと | 参照先 |
|---|---|
| 用語の定義・表記ゆれ | domain-glossary.md → KB `glossary/` |
| 機能の入出力・正常系/異常系 | KB `features/` |
| 制約・上限値・バリデーション等の業務ルール | KB `rules/` |
| 「なぜこの仕様か」の背景・経緯 | KB `decisions/` |

## 証拠レベルの扱い(conventions.md §5 の適用)

KB は一次情報(sources/)から LLM が編纂した**二次情報**である。QA成果物では:

- `confidence: verified` のコンセプトに基づく事実 → `evidence_level: likely`、
  `sources: [kb:knowledge/rules/xxx.md]` の形式で出所を書く
- コンセプトの `sources:` が指す一次情報(KB の sources/ 内の仕様書等)を
  **直接確認できた**場合のみ `confirmed`(sources には一次情報の方を書く)
- `confidence: inferred / unverified` に基づく事実 → `hypothesis`
- KB とインプット資料(仕様書・コード)が**矛盾**する場合: どちらかを黙って採用せず、
  矛盾自体を要確認事項(qa-spec-review の AMB 形式)として記録し、人間に判定を返す。

## 書き込み禁止と還元ルール

- **QAスキルは KB を直接編集しない。** KB は自身の AGENTS.md と
  kb-ingest / kb-lint ワークフローで保守される独立リポジトリであり、
  外部から勝手に書くと一貫性(引用・相互参照・ログ)が壊れる。
- セッションで得た新しいドメイン知識は、次の2経路で還元する:
  1. **用語・小さな事実** → domain-glossary.md の「KB ingest 待ち」節に出典付きで記録
  2. **成果物単位の知見**(確定した仕様解釈、機能調査で判明した実装仕様、不具合傾向など)
     → qa-improvement がセッション末に「KB ingest 候補」として出典付きで一覧化
- 実際の取り込みはユーザーが KB 側の `kb-ingest` ワークフローで行う。
  QAスキルの責務は**候補を出典付きで揃える**ところまで。
