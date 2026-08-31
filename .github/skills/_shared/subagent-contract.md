# サブエージェント契約(コンテキスト分離実行)

各スキルを**独立したコンテキスト**で実行するときの入出力契約。ツール非依存。

## 1. なぜ分離するか

全スキルを1つの会話で順に実行すると、後段に進むほど文脈が肥大し、初期の資料と後段の判断が混ざる。各スキルを独立コンテキストで動かし、**成果物ファイルと下記のJSONだけを受け渡す**ことで、各スキルは自分に必要な入力だけを読む。

分離実行は必須ではない。単一コンテキストで通しても動作するが、Process モード(スキル9個)では分離を推奨する。

| ツール | 起動方法 |
|---|---|
| GitHub Copilot | `#tool:agent/runSubagent` で `qa-skill-runner` を呼ぶ(要 VS Code v1.107+)。実行するスキルは `skill` フィールドで指示する |
| Claude Code | Agent ツール(サブエージェント) |
| その他・分離なし | オーケストレーター自身が SKILL.md を読んで実行(契約は無視してよい) |

## 2. 入力 JSON

```json
{
  "mode": "subagent",
  "run_mode": "process",
  "session_dir": "qa-output/<セッション名>",
  "skill": "qa-scenario-design",
  "artifact": "11-scenario-design.md",
  "inputs": [
    "qa-output/<セッション名>/10-intent-recovery.md",
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
| `run_mode` | `"quick"` / `"grounded"` / `"process"`(skill-map.md §2)。成果物に明記する限界の判断に使う |
| `session_dir` | 成果物の出力先ディレクトリ |
| `skill` | **実行するスキル名。ランナーはこの値で `.github/skills/<skill>/SKILL.md` を特定する**(必須) |
| `artifact` | 書き出す成果物ファイル名(conventions.md §6 の命名) |
| `inputs` | 読み込むべきインプット資料と前段成果物のパス一覧(バケツリレー)。Markdown変換済みの資料(qa-session.json の `converted_path`)は原本ではなく変換後パスを渡す |
| `answers` | 前回返した `pending_questions` に対するユーザー回答(`{ "q1": "選択肢..." }`) |
| `approved_proposals` | 前回返した `proposals` のうち承認された id の一覧。適用を指示する |
| `user_feedback` | ゲートでユーザーが出した修正指示。null 以外なら成果物を修正する |

## 3. 出力 JSON

サブエージェントは最終応答の末尾に、次の JSON を**そのまま機械可読な形で**返す。

```json
{
  "status": "completed",
  "skill": "qa-scenario-design",
  "artifact": "qa-output/<セッション名>/11-scenario-design.md",
  "summary": "3〜5行の要約(ゲートでユーザーに提示される)",
  "key_decisions": ["重要な判断ポイント(ゲートで提示される)"],
  "unknowns": ["資料から決められず proposed / 不足情報として残した事項"],
  "review_points": [
    { "where": "11-scenario-design.md §3 SC-04", "judgment": "AIの現在の判断(1行)", "why": "確認が要る理由(判断が割れうる点)" }
  ],
  "pending_questions": [
    { "id": "q1", "question": "質問文", "options": ["選択肢A(推奨)", "選択肢B"], "multi": false }
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
  - `"needs_user_input"` — ユーザーの選択が無いと進めない。`pending_questions` 必須。成果物は途中まで書き出してよい
  - `"error"` — 続行不能。`{ "status": "error", "skill": "...", "result": "詳細" }` を返す
- `review_points` は**ゲートのレビュー依頼(conventions.md §4-1)の材料**。親はこれを使って「どのファイルのどこを見てほしいか」をユーザーに示す。§4-1 の優先順(proposed の採否 → やらないと決めた判断 → Blocker → hypothesis → 前提を置いた箇所)で**1〜3点**返す。`where` は人間が開く `.md` の節番号かIDで書く(台帳CSVを指さない)。
- `pending_questions` / `proposals` / `unknowns` / `review_points` は無ければ空配列。
- `proposals` は「参照ナレッジへの追記」などユーザー承認が必要な変更に使う。**承認前に対象ファイルを書き換えてはならない**。親が承認を取り、`approved_proposals` 付きで再呼び出しされたときに初めて適用する。

## 4. サブエージェントモードの制約

1. **ユーザーへ質問できない**。SKILL.md の手順に「ユーザーに確認する」「承認を得る」とある箇所は、その場で止めず `pending_questions` / `proposals` に変換して親へ返す。ただし **実装の挙動・詳細設計を問う項目は `pending_questions` に入れない**(conventions.md §2-1)。バリデーション・既定値・権限・遷移条件のたぐいは資料とコードを読んで確定させ、それでも決まらなければ質問ではなく `unknowns` に残す。判断・承認を求める項目(範囲・除外・優先度・業務の実態)は従来どおり `pending_questions` / `proposals` として返す — 親がユーザーに聞く。
2. **承認ゲートを自分で実施しない**。ゲート(conventions.md §4、skill-map.md §3)は親の責務。ただしゲートで見てほしい箇所は自分にしか分からないので、`review_points` として必ず返す。
3. **qa-session.json を更新しない**。セッション管理は親の責務。
4. 成果物ファイル(`session_dir`/`artifact`)は自分で書き出し、`lint_output.py` の ERROR を解消してから返す。
5. conventions.md の他の規約(日本語、証拠レベルと導出区分、不明点の扱い)はそのまま適用する。
6. 出力 JSON は改変せず正確に返す。**親に伝わるのはこの JSON と成果物ファイルだけ**だと考えること。

## 5. 直接呼び出しとの区別

入力に `"mode": "subagent"` の JSON が**含まれない**場合(ユーザーがチャットから直接スキルを指定した場合)は、この契約は適用しない。SKILL.md の手順どおり、選択式質問・承認を挟みながら対話的に実行する。
