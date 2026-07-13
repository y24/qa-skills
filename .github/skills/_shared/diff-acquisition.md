# PR・コード差分の取得ガイド

対象コードが PR・diff のスキル(qa-code-review、qa-code-overview モードB、
qa-feature-investigation)が、差分の取得で迷わないための手順。
対象がローカルのディレクトリ・機能単位で、コードを直接読める場合は読む必要はない。

## 原則: 差分の本文はローカルの git で取得する

- **差分の本文(コード)はローカルリポジトリ上の git コマンドで取得する。**
  MCP・API(Azure DevOps MCP、GitHub MCP 等)は PR のメタデータ(説明・
  コメント・レビュースレッド・関連チケット)の取得だけに使う。
- 理由: MCP の diff 取得ツールには応答トークン上限(目安 25k)があり、変更量の
  多い PR では応答が切れる・失敗する。ローカル git なら統計 → ファイル単位と
  取得量を制御でき、変更行の呼び出し元・呼び出し先の追跡も同じ作業ツリーで行える。
- 規模を確認する前に差分全文を一括で読み込まない。必ず §3 の段階取得
  (統計 → 計画 → グループ単位の本文)で読む。

## 1. ローカルリポジトリの確保

1. 現在の作業ディレクトリ(ワークスペース)が対象リポジトリなら、それを使う。
   `git remote -v` で PR のリポジトリと一致することを確認する。
2. 一致しない・見つからない場合は、**ファイルシステムを推測で探し回らず**、
   選択式でユーザーに確認する:
   - ローカルクローンのパスを教えてもらう
   - クローン URL を教えてもらい、新たに clone する(大きいリポジトリは
     `git clone --filter=blob:none <url>` で必要な blob だけ取得できる)
   - diff ファイル・パッチを直接提供してもらう(git を使えない環境の逃げ道)
3. shallow clone 等で merge-base が解決できない場合は `git fetch --unshallow`
   (または `--deepen=<n>`)で履歴を補ってから §3 に進む。

## 2. PR の両端ブランチを fetch する

PR のメタデータ(MCP またはユーザーへの確認)から **PR ID・ソースブランチ・
ターゲットブランチ** を把握し、両ブランチを fetch する。

```
git fetch origin <target-branch> <source-branch>
```

ソースブランチを fetch できない場合(削除済み・フォーク由来・名前不明)は
PR ref を使う:

| ホスティング | fetch | 差分の取り方 |
|---|---|---|
| Azure DevOps | `git fetch origin refs/pull/<ID>/merge` | `git diff FETCH_HEAD^1 FETCH_HEAD`(merge ref の第1親 = ターゲット先端) |
| GitHub | `git fetch origin refs/pull/<ID>/head` | `git diff origin/<target>...FETCH_HEAD` |

Azure DevOps の merge ref はコンフリクトがあるPRでは生成されない。その場合は
ソースブランチ名をユーザーに確認して fetch する。

## 3. 段階取得(統計 → 計画 → 本文)

差分は**三点比較(`...` = merge-base 起点)**で取る。二点比較(`..`)は
ターゲット側で進んだ無関係なコミットの差分が混入するため使わない。

### Step 1: 規模と全体像

```
git diff --stat origin/<target>...origin/<source>            # 規模の把握
git diff --name-status -M origin/<target>...origin/<source>  # ファイル一覧(リネーム検出付き)
git log --oneline origin/<target>..origin/<source>           # コミットメッセージから意図を掴む
```

自動生成物・依存ロックファイル(package-lock.json 等)・一括フォーマット変更は
ここで見分け、本文取得から除外する(例: `-- ':(exclude)package-lock.json'`)。
除外したものは成果物の「レビュー範囲」に必ず明記する。

### Step 2: レビュー計画

ファイル一覧を機能単位にグルーピングし、読む順序と除外対象を決める。
規模が大きい場合(目安: 30ファイル超 または 差分3,000行超)は、グルーピング
結果と読む優先順位を選択式でユーザーに確認してから本文に進む。

### Step 3: グループ単位で本文を読む

```
git diff origin/<target>...origin/<source> -- <パス1> <パス2> ...
```

- 1グループ(大きければ1ファイル)ずつ取得する。差分だけで判断できない箇所は
  `git show origin/<source>:<パス>` でファイル全体を読む、またはソースブランチを
  チェックアウトして呼び出し元・呼び出し先を検索する。
- コミット数が多くても、レビューは**最終状態の差分**に対して行うのが基本
  (revert の往復や中間状態を読まずに済む)。経緯が必要なときだけ
  `git log -p -- <パス>` でコミット単位に降りる。

## アンチパターン

- MCP の diff 取得ツールで PR 全体の差分を取ろうとする(大きい PR では失敗する)
- PR の Web ページを開いて差分を読み取ろうとする
- 規模を確認せずにいきなり差分全文を出力する
- 二点比較(`git diff <target> <source>`)で差分を取る
- リポジトリの場所を推測してファイルシステムを探し回る(§1 の選択式確認に従う)
