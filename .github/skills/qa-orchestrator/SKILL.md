---
name: qa-orchestrator
description: QA業務全体の入口。テスト対象のヒアリングから実行モードの選定、スキル連鎖の解決と逐次実行、承認ゲートの管理、セッションの中断・再開までを統括する。分析・設計の中身は各スキルが行う。
---

# QA Orchestrator

QAプロセス全体を統括する。**自分では分析・設計をしない。** ヒアリング → 実行計画の解決 → 各スキルの起動 → 承認ゲート → セッション管理を行う。

## 実行前に必ず読むこと

- [_shared/skill-map.md](../_shared/skill-map.md)(**スキル依存関係・実行モード・ゲートの定義元**)
- [_shared/conventions.md](../_shared/conventions.md)(対話ルール・証拠レベルと導出区分・承認ゲート)
- [_shared/session-schema.md](../_shared/session-schema.md)(qa-session.json の形式)
- (コンテキスト分離実行をする場合)[_shared/subagent-contract.md](../_shared/subagent-contract.md)

**実行するスキルの並びをこの SKILL.md に書き写さない。** 並びは skill-map.md §1 の依存関係から毎回解決する。ここに固定表を持つと、スキルの追加・削除のたびに定義が二重化する。

## Step 0: 再開判定

まず再開可能なセッションを確認する。

```
python .github/skills/_shared/scripts/qa_session.py resume-info qa-output
```

(スクリプトが使えない環境では `qa-output/*/qa-session.json` を直接探す。以降のセッションファイル操作も同様 — conventions.md §9)

- **存在し、未完了ステップがある場合**: セッション概要(対象・実行モード・承認済みゲート・次のステップ)を提示し、「続きから再開 / 新規セッション開始」を選択式で確認する
- **存在しない場合**: Step 1 へ

## Step 1: ヒアリング(すべて選択式)

conventions.md §2 に従う。**必須質問を先に、任意質問は後に。** 「すべて推奨で進める」を常に選べるようにする。

### 1-1. 必須(Need to know)

1. **インプット資料**(複数選択): 要件定義書・基本設計書 / 仕様書 / 要件チケット・ユーザーストーリー / 画面設計 / 権限定義(RBAC) / 状態定義 / PR・コード / 過去不具合一覧 / プロジェクト計画書 / 既存テストケース / 既存の品質基準 / その他
   - 選択後、各資料のパス・URLを確認する

2. **実行モード**(単一選択)。skill-map.md §2 の3モードを提示する。**選択肢には各モードの限界を必ず併記する。**
   - **Quick** — ストーリー・チケットのみ。速いが網羅は保証しない
   - **Grounded**(推奨) — 設計資料に基づく。単一ロール・単一画面の変更向け
   - **Process** — 業務プロセスまで復元。複数ロール・状態遷移・外部連携向け

   インプットの選択内容とモードが噛み合わない場合(例: Process を選んだが要件定義書がない)は、その影響を伝えて選び直させる。

3. **セッション名**: 名前の案を提示して確認する。出力先は `qa-output/<セッション名>/` 固定(Step 0 の再開判定がこのパスを前提とするため)。

### 1-2. 任意(Nice to know)

- 特に重点的に見たい領域・過去に問題が起きた箇所
- 除外してよい範囲(既に決まっているもの)

答えられない場合は飛ばしてよい。**ここで止まらない。**

## Step 2: 実行計画の解決

skill-map.md から計画を組む。**手順を暗記せず、毎回ファイルを読んで解決する。**

1. §2 で選ばれたモードの連鎖を取得する
2. §1 の依存関係表と、Step 1 で確認したインプットを突き合わせ、**必須入力が揃わないスキルを除外**する
3. 任意で挿入できるスキルを判定する(コードがあれば `qa-code-review`、不具合一覧があれば `qa-defect-analysis`)
4. 各ステップに §3 のゲートを割り当てる
5. **計画案を提示**する: 実行するスキル・スキップするスキルとその理由・ゲートの位置・各ゲートで誰の承認が要るか

これが **G1(スコープ)ゲート**。承認を得てからセッションを作成する。

**セッションの作成は4コマンドで済ませる**(1件ずつ呼ばない)。

```
python .github/skills/_shared/scripts/qa_session.py init qa-output/<名前> --name <名前> --feature "<対象>" --run-mode <quick|grounded|process>
python .github/skills/_shared/scripts/qa_session.py add-input qa-output/<名前> --item "<種別>:<パス>:<メモ>" --item "..."
python .github/skills/_shared/scripts/qa_session.py add-phase qa-output/<名前> --steps <スキル名>:<ゲート> --steps <スキル名>:<ゲート>:<対象>
python .github/skills/_shared/scripts/qa_session.py set-gate qa-output/<名前> G1 approved
```

スキップするスキルも `--steps <スキル名>:<ゲート>::skipped` で登録する(何を意図的にやらなかったかの記録になる)。

**Quick モードではセッションファイルを作らなくてよい**(skill-map.md §2)。単発の初稿づくりに簿記は要らない。

Excel・PDF など直接読みにくい形式の資料が含まれる場合は、[_shared/source-conversion.md](../_shared/source-conversion.md) を読み、ここで markitdown により `sources/` へ変換して `add-input --converted` に変換後パスを記録する。以降のステップには変換後パスを渡す。

## Step 3: 逐次実行

各ステップについて:

1. 該当スキルを実行する。前段の成果物を必ずインプットに含める(**バケツリレー**)。読むべき成果物は skill-map.md §1 の入力欄が定める
   - **コンテキスト分離する場合**: [subagent-contract.md](../_shared/subagent-contract.md) の入力JSONで起動し、返ってきた出力JSONの `pending_questions` / `proposals` を親であるこのスキルが処理する
   - **分離しない場合**: 該当スキルの SKILL.md を読み込み、その手順に従って実行する
2. 成果物を書き出し、`lint_output.py` で書式チェックして ERROR を解消する
3. **要約(全文ではない)+ 重要な判断ポイント + 残った不明点**を提示する。ここでは承認を取らず、異議がなければ次へ進む
4. `qa_session.py set-status <dir> <order> approved --output <ファイル名>` で更新する(**完了時のみ。開始時の更新はしない** — 再開位置は未完了の最小 order で決まる)
5. 実行中に気づいたスキル自体の問題は `qa_session.py add-note` で追記する

**ゲートに到達したら**(そのゲートに属する全ステップが終わったら):

1. ゲートが束ねる成果物をまとめて提示する(各要約 + ゲート固有の確認事項)
2. conventions.md §4 の4択で承認を取る
3. `qa_session.py set-gate <dir> <ゲート> approved` で更新する。ユーザーの判断(除外・条件付き承認)は `add-decision` で記録する
4. 承認されるまで次のゲートの範囲へ進まない

### ゲート外でも必ず止まる場合

conventions.md §4 の例外。ゲートを待たずその場で確認する。

- 未解決の Blocker(qa-spec-review)が残っている
- 「テストしない」と決める判断(除外範囲)
- 本番データ由来のデータ利用(マスキング要否)

### ループバック

後段で前段の欠落に気づいたら戻る。**戻ることは失敗ではない。** skill-map.md §4 の対応表に従い、戻り先のステップを `in_progress` に、対応するゲートを `pending` に戻し、**戻った理由を `add-decision` に記録する**(qa-improvement の重要な材料になる)。

## Step 4: 完了と自己改善

全ステップ完了後:

1. 成果物一覧と各ステップの要約を最終レポートとして提示する
2. qa-improvement を起動し、成果物のセルフレビュー・`improvement_notes`・指標測定・ユーザーヒアリングから振り返りレポート(`90-improvement.md`)を作成する
3. これが **G5(完了)ゲート**

スキルファイル・参照ナレッジはこの場では変更しない(マスターへの反映はメンテナーが [maintenance-log.md](../_shared/maintenance-log.md) のトリアージを経て判断する — conventions.md §8)。

## 禁止事項

- **ゲートの承認を得ずに次のゲートの範囲へ進むこと。**
- ヒアリングを自由記述の質問で行うこと。
- オーケストレーター自身が分析・設計の中身を作ること(必ず各スキルの手順に従う)。
- skill-map.md を読まずに、記憶しているスキルの並びで計画を組むこと。
- 実行モードの限界を伝えずに成果物を提示すること(特に Quick モードで「網羅した」と受け取られる要約を書かない)。
