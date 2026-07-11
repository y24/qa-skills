# QA サブエージェント共通プロトコル(GitHub Copilot 用)

`.github/agents/` 配下の QA エージェント群が `#tool:agent/runSubagent` で
呼び出されるときの共通契約。各エージェントの**手順の本体**は
`.github/skills/<エージェント名>/SKILL.md` にあり、このファイルは
「サブエージェントとして呼ばれたときの入出力と制約」だけを定める。

## 1. 呼び出し形式

親(qa-orchestrator)は `#tool:agent/runSubagent` を次のパラメータで呼ぶ:

- **agentName**: 呼び出すエージェント名(例: `qa-defect-analysis`)
- **description**: チャットに表示する短い説明(例: `フェーズ1: 不具合分析と回帰観点導出`)
- **prompt**: 下記の入力 JSON(文字列化したもの)

## 2. 入力 JSON

```json
{
  "mode": "subagent",
  "session_dir": "qa-output/<セッション名>",
  "phase": "01",
  "artifact": "01-defect-analysis.md",
  "skill_mode": null,
  "inputs": [
    "docs/spec.md",
    "qa-output/<セッション名>/01-defect-analysis.md"
  ],
  "answers": {},
  "approved_proposals": [],
  "user_feedback": null
}
```

| フィールド | 説明 |
|---|---|
| `mode` | 常に `"subagent"`。これが含まれる入力を受けたらサブエージェントモードで動く |
| `session_dir` | 成果物の出力先ディレクトリ |
| `phase` | フェーズ番号(成果物ファイル名の接頭辞) |
| `artifact` | 書き出す成果物ファイル名(conventions.md §6 の命名) |
| `skill_mode` | スキル内モードの指定(qa-spec-review のみ `"mode1"` / `"mode2"`) |
| `inputs` | 読み込むべきインプット資料と前フェーズ成果物のパス一覧(バケツリレー)。Markdown変換済みの資料(qa-session.json の `converted_path`、_shared/source-conversion.md)は原本ではなく変換後パスを渡す |
| `answers` | 前回返した `pending_questions` に対するユーザー回答(`{ "q1": "選択肢..." }`) |
| `approved_proposals` | 前回返した `proposals` のうち承認された id の一覧。適用を指示する |
| `user_feedback` | 承認ゲートでユーザーが出した修正指示。null 以外なら成果物を修正する |

## 3. 出力 JSON

サブエージェントは最終応答の末尾に、次の JSON を**そのまま機械可読な形で**返す:

```json
{
  "status": "completed",
  "agentName": "qa-defect-analysis",
  "artifact": "qa-output/<セッション名>/01-defect-analysis.md",
  "summary": "3〜5行の要約(承認ゲートでユーザーに提示される)",
  "key_decisions": ["重要な判断ポイント(承認ゲートで提示される)"],
  "pending_questions": [
    {
      "id": "q1",
      "question": "質問文",
      "options": ["選択肢A(推奨)", "選択肢B"],
      "multi": false
    }
  ],
  "proposals": [
    {
      "id": "p1",
      "target": ".github/skills/_shared/references/regression-viewpoint-catalog.md",
      "summary": "追記内容の1行要約",
      "content": "追記するエントリ全文"
    }
  ],
  "notes": "スキル自体への改善メモ(qa-session.json の improvement_notes 行き。無ければ空)"
}
```

- `status`:
  - `"completed"` — 成果物を書き出し済み
  - `"needs_user_input"` — ユーザーの選択が無いと進めない。`pending_questions` 必須。
    成果物は途中まで書き出してよい
  - `"error"` — 続行不能。`{ "status": "error", "agentName": "...", "result": "詳細" }` を返す
- `pending_questions` / `proposals` は無ければ空配列。
- `proposals` は「参照ナレッジへの追記」などユーザー承認が必要な変更に使う。
  **承認前に対象ファイルを書き換えてはならない**。親が承認を取り、
  `approved_proposals` 付きで再呼び出しされたときに初めて適用する。

## 4. サブエージェントモードの制約

1. **ユーザーへ質問できない**(askQuestions 等は親しか使えない)。
   SKILL.md の手順に「ユーザーに確認する」「承認を得る」とある箇所は、
   その場で止めず `pending_questions` / `proposals` に変換して親へ返す。
2. **承認ゲートを自分で実施しない**。承認ゲート(conventions.md §4)は親の責務。
3. **qa-session.json を更新しない**。セッション管理は親の責務。
4. 成果物ファイル(`session_dir`/`artifact`)は自分で書き出す。
5. conventions.md の他の規約(日本語、証拠レベル、不明点の扱い)はそのまま適用する。
6. 出力 JSON は改変せず正確に返す。親に伝わるのはこの JSON だけだと考えること。

## 5. 直接呼び出しとの区別

入力に `"mode": "subagent"` の JSON が**含まれない**場合(ユーザーがチャットから
直接エージェントを選んだ場合)は、このプロトコルは適用しない。
SKILL.md の手順どおり、選択式質問・承認を挟みながら対話的に実行する。
