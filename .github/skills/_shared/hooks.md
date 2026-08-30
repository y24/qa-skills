# hooks(何を機械で保証するか)

**このファイルが hooks の定義元。** どの hook が規約のどれを保証するかをここで決め、各ツールの設定ファイルは配線だけを持つ。

判定の実装は [scripts/gate_check.py](scripts/gate_check.py) の1本だけで、hook はそれを [scripts/hook_entry.py](scripts/hook_entry.py) 経由で呼ぶ。**hook 設定に判定ロジックを書かない。**

## 1. なぜ hooks が要るか

各 SKILL.md の「機械確認」ステップや conventions.md §9 の「ERROR を解消してから提示する」は、**AIが従うかどうかに依存する指示**であって保証ではない。実行しても検出を無視して先へ進める。hook はハーネス側が実行するため、AIが回避できない。

ただし hooks に一本化しない。層の全体像は [scripts/README.md](scripts/README.md#4層の防御検証はどこで効くか) を参照。

## 2. 配線している hook

| イベント | アクション | 保証する規約 | ブロックするか |
|---|---|---|---|
| `SessionStart` | `session-start` | qa-orchestrator Step 0(再開判定)。再開可能なセッションを文脈に注入する | しない(情報提供) |
| `PreToolUse`(シェル) | `pre-bash` | conventions.md §4 / 設計原則4。`set-gate <G> approved` の直前にそのゲートの成果物を検証し、未解消ならゲート承認を保留する。`set-status <n> approved --output <f>` も同様に当該成果物を検証する | **する** |
| `PreToolUse`(書き込み) | `pre-write` | conventions.md §8。セッション稼働中のマスター資産(SKILL.md・`_shared/` 配下・`scripts/`)への書き込みを止める | **する** |
| `PostToolUse`(書き込み) | `post-write` | conventions.md §9。`qa-output/**` の成果物を書いた直後に書式を検証し、その場でフィードバックする | できない(仕様上。stderr がモデルへの通知になる) |
| `Stop` | `stop` | conventions.md §9。未承認ゲートの成果物に未解消の検出があるうちは応答を終わらせない | **する**(上限あり。§4) |
| `SubagentStop` | `subagent-stop` | subagent-contract.md。サブエージェントが未解消の成果物を親に返さないようにする | **する**(上限あり) |

## 3. 設定ファイルの置き場所

**同じ hook を二重に登録しない。** VS Code は `.github/hooks/*.json` と `.claude/settings.json` の**両方**を既定で読むため、`.vscode/settings.json` の `chat.hookFilesLocations` で `.claude/settings.json` を無効にしている(無効にしないと Stop の連続ブロック回数が二重に加算される)。

| ファイル | 読むツール | 形式 |
|---|---|---|
| [.github/hooks/qa-quality-gates.json](../../hooks/qa-quality-gates.json) | GitHub Copilot CLI / Copilot cloud agent / VS Code Copilot | イベント → ハンドラの**平坦な配列**(`matcher` はハンドラ自身が持つ) |
| [.claude/settings.json](../../../.claude/settings.json) | Claude Code | イベント → `{matcher, hooks: [...]}` の配列(**入れ子**。Copilot と互換性がない) |
| [.vscode/settings.json](../../../.vscode/settings.json) | VS Code | どの hook ファイルを読むかの指定 |

形式が違うため設定ファイルは2つ要る。**呼ぶスクリプトは同じ1本**なので、判定が分裂することはない。

### ツールごとの差(2026年8月時点の実測)

- **VS Code は `matcher` を無視する。** そのため**どのツール呼び出しかの判定は `hook_entry.py` の中で行っている**。設定ファイルの `matcher` は Copilot CLI / cloud agent 向けの絞り込みでしかなく、無視されても挙動は変わらない。
- **ペイロードのキー名が違う。** Claude Code は `tool_name` / `tool_input`、Copilot は `toolName` / `toolArgs`。`hook_entry.py` が両方を受ける。
- **出力スキーマが3方言ある。** `hook_entry.py` は3つを1つのJSONにまとめて出す(キーが衝突しないため各ホストが自分の知るキーだけを読む)。**移植可能な契約は終了コード 0 / 2 と stderr のメッセージだけ**なので、そちらを主として扱う。
- **Copilot cloud agent** は `.github/hooks/*.json` しか読まない(ユーザー設定・プラグインは読まない)。`notification` / `permissionRequest` は発火しない。
- **VS Code の hooks は preview。** 使えない時期があっても層2(`gate_check.py`)と層4(CI)は動く。

### エージェント単位の hook を使っていない理由

Claude Code は `SKILL.md` / subagent の frontmatter に、VS Code Copilot は `.agent.md` の frontmatter に hook を書ける。**採らなかった。** 理由は2つ。

1. `hook_entry.py` は**内容で自己スコープしている** — 稼働中のQAセッションが無ければ `pre-write` は素通しし、`pre-bash` は `qa_session.py` のコマンド以外に反応せず、`post-write` は `qa-output/**` しか見ない。QA作業以外には既に何も起きないので、エージェント単位に絞る必要がない。
2. frontmatter hook が使えるのは4環境中2つだけ。**スコープをスクリプト側に置けば4環境すべてで同じ挙動になる**(`matcher` を使わないのと同じ理由)。

ノイズが問題になった場合の逃げ道としては有効なので、その時は `.agent.md` / `SKILL.md` の frontmatter へ移す。

## 4. 暴走させないための歯止め

hook は入れすぎても止めすぎても壊れる。以下は意図的な設計。

- **Stop の連続ブロックは2回まで。** 3回目からは止めず、「解消したことにせず残っている検出をそのまま報告せよ」というメッセージだけ返す(`hook_entry.py` の `MAX_STOP_BLOCKS`)。**降格後はカウンタをリセットしない** — リセットするとブロックと通過を繰り返してエージェントが振動する。リセットは検出が消えたときだけ。
- **`stop_hook_active` を尊重する。** ホストがループを検知しているときは何もしない。
- **fail-open。** ペイロードが壊れている・スクリプトが落ちる・`gate_check.py` が使用法エラーを返す、のいずれでもワークフローを止めない(診断は stderr に出す)。検証層の不具合で作業が止まる方が害が大きい。
- **承認済みゲートは蒸し返さない。** `Stop` は `--unapproved` で未承認ゲートの成果物だけを見る。人間が承認したものを後から機械が止めない。
- **Quick モードには網羅の手続きを課さない。** `gate_check.py` が `run_mode` を読んで trace を省く(skill-map.md §2)。セッションファイルが無い場合も同じ。
- **`QA_ALLOW_MASTER_EDIT=1`** でマスター資産ガードを一時的に外せる(メンテナンス作業用)。

## 5. 段階導入(慣らし運転)

**いきなり止めない。** 現在すべての hook に `--warn-only` が付いている。この状態では検出をモデルに伝えるだけで、ブロックはしない。

1〜2セッション回して**誤検出が出ないことを確認してから**、2つの設定ファイルから `--warn-only` を外す。誤検出が出た場合は、hook 設定ではなく `gate_check.py` / `lint_output.py` / `trace_check.py` 側を直す(判定基準を hook で緩めない)。

無効化するには:

- Claude Code: `.claude/settings.json` に `"disableAllHooks": true`
- Copilot: 設定ファイルの先頭に `"disableAllHooks": true`
- VS Code: `.vscode/settings.json` の `chat.hookFilesLocations` を全部 `false`

## 6. 変更するとき

hook を追加・削除するときは次の順で行う。

1. 本ファイル §2 の表を更新する(**ここが定義元**)
2. `scripts/hook_entry.py` にアクションを足す。**判定ロジックは `gate_check.py` 側に置く**
3. `.github/hooks/qa-quality-gates.json` と `.claude/settings.json` の両方に配線する(形式が違うことに注意)
4. `.github/workflows/qa-artifacts.yml` の自己検査に「検出できること」のケースを足す
5. `scripts/README.md` の4層の表を追随させる

判定基準(どの検出を失敗と数えるか)を変えるときは `gate_check.py` を直す。hook 側で緩めてはならない — 環境ごとに強制力が変わってしまう。

**このファイルと `scripts/` はマスター資産**(conventions.md §8)。セッション内で書き換えず、[maintenance-log.md](maintenance-log.md) のトリアージを経て反映する。
