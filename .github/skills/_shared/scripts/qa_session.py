#!/usr/bin/env python3
"""qa-session.json 管理CLI。

QAセッションファイル(qa-output/<セッション名>/qa-session.json)の作成・更新を
LLMの「読み込み→修正→全体書き戻し」の代わりに行う。定型処理をスクリプトに
寄せることで、JSON破損・タイムスタンプ不正確・トークン浪費を防ぐ。

スキーマ: .github/skills/_shared/session-schema.md
規約:     .github/skills/_shared/conventions.md §3, §6

使用例:
    python qa_session.py init qa-output/invoice-export --name invoice-export \\
        --feature "請求書エクスポート機能" --description "CSV/PDF出力の新規追加" \\
        --run-mode process
    python qa_session.py add-input qa-output/invoice-export \\
        --item "spec:docs/design.md:基本設計書" --item "code:src/invoice/:対象コード"
    python qa_session.py add-phase qa-output/invoice-export \\
        --steps qa-source-analysis:G2 --steps qa-defect-analysis:G2 \\
        --steps qa-spec-review:G2:requirements --steps qa-test-viewpoint:G4
    python qa_session.py set-status qa-output/invoice-export 1 approved \\
        --output 00-source-analysis.md
    python qa_session.py set-gate qa-output/invoice-export G2 approved
    python qa_session.py add-decision qa-output/invoice-export --phase 1 \\
        --decision "軽微な表記ゆれ不具合は分析対象から除外"
    python qa_session.py add-note qa-output/invoice-export "ステップ2の質問が冗長"
    python qa_session.py show qa-output/invoice-export
    python qa_session.py resume-info            # 既定: ./qa-output を走査
    python qa_session.py resume-info path/to/qa-output

exit code: 0=成功, 1=検証エラー(不正status・重複order・ファイル既存等), 2=使用法エラー
"""

import argparse
import glob
import json
import os
import sys
import tempfile
from datetime import datetime

SESSION_FILE = "qa-session.json"

VALID_STATUSES = ("pending", "in_progress", "awaiting_approval", "approved", "skipped")
UNFINISHED_STATUSES = ("pending", "in_progress", "awaiting_approval")

STATUS_LABELS = {
    "pending": "未着手",
    "in_progress": "実行中",
    "awaiting_approval": "承認待ち",
    "approved": "承認済み",
    "skipped": "スキップ",
}

# skill-map.md §2: 実行モード(どこまで根拠に基づくかの宣言)
VALID_RUN_MODES = ("quick", "grounded", "process")

# skill-map.md §3: 承認ゲート(成果物ごとではなく意味が変わる地点で承認を取る)
GATE_LABELS = {
    "G1": "スコープ",
    "G2": "根拠と未知",
    "G3": "意図モデル",
    "G4": "テスト設計",
    "G5": "完了",
}
VALID_GATES = tuple(GATE_LABELS)
VALID_GATE_STATUSES = ("pending", "awaiting_approval", "approved", "skipped")


def _now_iso():
    """ローカルタイムゾーン付き ISO 8601 タイムスタンプ(秒精度)。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _fail(message):
    """検証エラー: 日本語メッセージを stderr へ出して exit 1。"""
    print("エラー: " + message, file=sys.stderr)
    sys.exit(1)


def _session_path(directory):
    return os.path.join(directory, SESSION_FILE)


def _load(directory):
    """qa-session.json を読み込む。未知フィールドもそのまま保持される。"""
    path = _session_path(directory)
    if not os.path.isfile(path):
        _fail("セッションファイルが見つかりません: {}".format(path))
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        _fail("qa-session.json の解析に失敗しました({}): {}".format(path, e))


def _save(directory, session, touch_updated=True):
    """アトミック書き込み(一時ファイル → os.replace)。updated_at を自動更新。"""
    if touch_updated:
        session["updated_at"] = _now_iso()
    path = _session_path(directory)
    fd, tmp_path = tempfile.mkstemp(
        prefix=SESSION_FILE + ".", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _find_phase(session, order):
    for phase in session.get("plan", []):
        if phase.get("order") == order:
            return phase
    return None


# ---------------------------------------------------------------- subcommands


def cmd_init(args):
    if args.run_mode not in VALID_RUN_MODES:
        _fail(
            "不正な run-mode です: {} (許可: {})".format(
                args.run_mode, " / ".join(VALID_RUN_MODES)
            )
        )
    path = _session_path(args.dir)
    if os.path.exists(path):
        _fail("セッションファイルが既に存在します: {}".format(path))
    os.makedirs(args.dir, exist_ok=True)
    now = _now_iso()
    session = {
        "session_name": args.name,
        "created_at": now,
        "updated_at": now,
        "run_mode": args.run_mode,
        "target": {
            "feature": args.feature,
            "description": args.description or "",
        },
        "inputs": [],
        "plan": [],
        "gates": [{"gate": g, "status": "pending"} for g in VALID_GATES],
        "current_order": None,
        "decisions": [],
        "improvement_notes": [],
    }
    _save(args.dir, session, touch_updated=False)
    print("セッションを作成しました: {}".format(path))


def _parse_item(spec, field_count, label):
    """`a:b:c` 形式の一括指定を分解する(不足分は空文字で埋める)。"""
    parts = spec.split(":", field_count - 1)
    if len(parts) < 1 or not parts[0].strip():
        _fail("{}の書式が不正です: {}".format(label, spec))
    parts += [""] * (field_count - len(parts))
    return [x.strip() for x in parts]


def cmd_add_input(args):
    session = _load(args.dir)
    inputs = session.setdefault("inputs", [])
    added = 0
    for spec in args.item or []:
        # 種別:パス[:メモ[:変換後パス]]
        kind, path, note, converted = _parse_item(spec, 4, "--item")
        if not path:
            _fail("--item にパスがありません: {}".format(spec))
        entry = {"type": kind, "path": path, "note": note}
        if converted:
            entry["converted_path"] = converted
        inputs.append(entry)
        added += 1
    if args.type and args.path:
        entry = {"type": args.type, "path": args.path, "note": args.note or ""}
        if args.converted:
            entry["converted_path"] = args.converted
        inputs.append(entry)
        added += 1
    if added == 0:
        _fail("--item または --type/--path のいずれかを指定してください")
    _save(args.dir, session)
    print("インプットを {} 件追加しました".format(added))


def cmd_add_phase(args):
    session = _load(args.dir)
    plan = session.setdefault("plan", [])
    next_order = max((p.get("order", 0) for p in plan), default=0) + 1

    def _append(order, skill, gate, target, status):
        if _find_phase(session, order) is not None:
            _fail("order={} のステップは既に存在します".format(order))
        if status not in VALID_STATUSES:
            _fail("不正な status です: {} (許可: {})".format(
                status, " / ".join(VALID_STATUSES)))
        if gate and gate not in VALID_GATES:
            _fail("不正な gate です: {} (許可: {})".format(
                gate, " / ".join(VALID_GATES)))
        entry = {"order": order, "skill": skill}
        if target:
            entry["target"] = target
        if gate:
            entry["gate"] = gate
        entry["status"] = status
        entry["output"] = None
        plan.append(entry)

    added = 0
    for spec in args.steps or []:
        # スキル名[:ゲート[:対象ラベル[:status]]]。order は指定順に自動採番
        skill, gate, target, status = _parse_item(spec, 4, "--steps")
        _append(next_order, skill, gate, target, status or "pending")
        next_order += 1
        added += 1
    if args.skill:
        order = args.order if args.order is not None else next_order
        _append(order, args.skill, args.gate or "", args.target, args.status)
        added += 1
    if added == 0:
        _fail("--steps または --skill のいずれかを指定してください")

    plan.sort(key=lambda p: p.get("order", 0))
    _save(args.dir, session)
    print("ステップを {} 件追加しました".format(added))


def cmd_set_status(args):
    if args.status not in VALID_STATUSES:
        _fail(
            "不正な status です: {} (許可: {})".format(
                args.status, " / ".join(VALID_STATUSES)
            )
        )
    session = _load(args.dir)
    phase = _find_phase(session, args.order)
    if phase is None:
        _fail("order={} のステップが見つかりません".format(args.order))
    phase["status"] = args.status
    if args.output is not None:
        phase["output"] = args.output
    if args.status == "in_progress":
        session["current_order"] = args.order
    _save(args.dir, session)
    print(
        "ステップ {} ({}) の status を {} に更新しました".format(
            args.order, phase.get("skill", "?"), args.status
        )
    )


def cmd_set_gate(args):
    if args.gate not in VALID_GATES:
        _fail(
            "不正な gate です: {} (許可: {})".format(args.gate, " / ".join(VALID_GATES))
        )
    if args.status not in VALID_GATE_STATUSES:
        _fail(
            "不正な status です: {} (許可: {})".format(
                args.status, " / ".join(VALID_GATE_STATUSES)
            )
        )
    session = _load(args.dir)
    gates = session.setdefault(
        "gates", [{"gate": g, "status": "pending"} for g in VALID_GATES]
    )
    entry = next((g for g in gates if g.get("gate") == args.gate), None)
    if entry is None:
        entry = {"gate": args.gate}
        gates.append(entry)
    entry["status"] = args.status
    if args.status == "approved":
        entry["approved_at"] = _now_iso()
    if args.note:
        entry["note"] = args.note
    _save(args.dir, session)
    print(
        "ゲート {} ({}) の status を {} に更新しました".format(
            args.gate, GATE_LABELS.get(args.gate, "?"), args.status
        )
    )


def cmd_add_decision(args):
    session = _load(args.dir)
    entry = {
        "at": _now_iso(),
        "phase": args.phase,
        "decision": args.decision,
        "by": args.by,
    }
    session.setdefault("decisions", []).append(entry)
    _save(args.dir, session)
    print("判断を記録しました: phase={} decision={}".format(args.phase, args.decision))


def cmd_add_note(args):
    session = _load(args.dir)
    session.setdefault("improvement_notes", []).append(args.text)
    _save(args.dir, session)
    print("改善メモを追記しました: {}".format(args.text))


def cmd_show(args):
    session = _load(args.dir)
    target = session.get("target", {}) or {}
    print("セッション名  : {}".format(session.get("session_name", "?")))
    print("対象機能      : {}".format(target.get("feature", "?")))
    description = target.get("description") or ""
    if description:
        print("説明          : {}".format(description))
    print("実行モード    : {}".format(session.get("run_mode", "(未設定)")))
    print("作成日時      : {}".format(session.get("created_at", "?")))
    print("更新日時      : {}".format(session.get("updated_at", "?")))
    print("current_order : {}".format(session.get("current_order")))
    inputs = session.get("inputs", [])
    print("インプット    : {} 件".format(len(inputs)))
    for item in inputs:
        note = item.get("note") or ""
        print(
            "  - [{}] {}{}".format(
                item.get("type", "?"),
                item.get("path", "?"),
                " ({})".format(note) if note else "",
            )
        )
    plan = session.get("plan", [])
    print("ステップ      : {} 件".format(len(plan)))
    for phase in plan:
        status = phase.get("status", "?")
        label = STATUS_LABELS.get(status, status)
        target = phase.get("target")
        gate = phase.get("gate")
        output = phase.get("output")
        print(
            "  {:>3}. {}{}{} [{} / {}]{}".format(
                phase.get("order", "?"),
                phase.get("skill", "?"),
                " <{}>".format(target) if target else "",
                " ({})".format(gate) if gate else "",
                status,
                label,
                " -> {}".format(output) if output else "",
            )
        )
    gates = session.get("gates", [])
    if gates:
        print("承認ゲート    : {} 件".format(len(gates)))
        for g in gates:
            name = g.get("gate", "?")
            print(
                "  - {} {} [{}]{}".format(
                    name,
                    GATE_LABELS.get(name, ""),
                    g.get("status", "?"),
                    " {}".format(g.get("approved_at")) if g.get("approved_at") else "",
                )
            )
    decisions = session.get("decisions", [])
    print("判断記録      : {} 件".format(len(decisions)))
    for decision in decisions:
        print(
            "  - [phase {}] {} ({}, {})".format(
                decision.get("phase", "?"),
                decision.get("decision", ""),
                decision.get("by", "?"),
                decision.get("at", "?"),
            )
        )
    notes = session.get("improvement_notes", [])
    print("改善メモ      : {} 件".format(len(notes)))
    for note in notes:
        print("  - {}".format(note))


def cmd_resume_info(args):
    root = args.root
    if not os.path.isdir(root):
        print("qa-output ディレクトリが見つかりません: {}".format(root))
        return
    pattern = os.path.join(root, "*", SESSION_FILE)
    found = 0
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as f:
                session = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print("警告: {} を読めませんでした: {}".format(path, e), file=sys.stderr)
            continue
        plan = session.get("plan", [])
        unfinished = [p for p in plan if p.get("status") in UNFINISHED_STATUSES]
        if not unfinished:
            continue
        found += 1
        target = session.get("target", {}) or {}
        completed = [p for p in plan if p.get("status") == "approved"]
        next_phase = min(unfinished, key=lambda p: p.get("order", 0))
        print("■ セッション: {}".format(session.get("session_name", "?")))
        print("  パス            : {}".format(path))
        print("  対象            : {}".format(target.get("feature", "?")))
        print("  実行モード      : {}".format(session.get("run_mode", "(未設定)")))
        print("  更新日時        : {}".format(session.get("updated_at", "?")))
        if completed:
            done = ", ".join(
                "{}. {}".format(p.get("order", "?"), p.get("skill", "?"))
                for p in completed
            )
        else:
            done = "(なし)"
        print("  完了済みステップ: {}".format(done))
        approved_gates = [
            g.get("gate") for g in session.get("gates", [])
            if g.get("status") == "approved"
        ]
        print(
            "  承認済みゲート  : {}".format(
                ", ".join(approved_gates) if approved_gates else "(なし)"
            )
        )
        print(
            "  次のステップ    : {}. {}{} [{}]".format(
                next_phase.get("order", "?"),
                next_phase.get("skill", "?"),
                " <{}>".format(next_phase["target"]) if next_phase.get("target") else "",
                next_phase.get("status", "?"),
            )
        )
        print()
    if found == 0:
        print("再開可能なセッションはありません: {}".format(root))
    else:
        print("再開可能なセッション: {} 件".format(found))


# --------------------------------------------------------------------- parser


def build_parser():
    parser = argparse.ArgumentParser(
        prog="qa_session.py",
        description="qa-session.json 管理CLI(スキーマ: _shared/session-schema.md)",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p = sub.add_parser("init", help="qa-session.json を新規作成する")
    p.add_argument("dir", help="セッションディレクトリ(qa-output/<セッション名>)")
    p.add_argument("--name", required=True, help="セッション名")
    p.add_argument("--feature", required=True, help="対象機能")
    p.add_argument("--description", default="", help="対象機能・変更の1〜2行説明")
    p.add_argument("--run-mode", dest="run_mode", default="grounded",
                   help="実行モード({})".format(" / ".join(VALID_RUN_MODES)))
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add-input", help="inputs にインプット資料を追記する")
    p.add_argument("dir", help="セッションディレクトリ")
    p.add_argument("--item", action="append", metavar="種別:パス[:メモ[:変換後パス]]",
                   help="一括指定(複数回指定可。推奨)")
    p.add_argument("--type", default="",
                   help="資料種別(spec/plan/defects/pr/code/criteria 等)")
    p.add_argument("--path", default="", help="資料のパスまたはURL")
    p.add_argument("--note", default="", help="補足メモ")
    p.add_argument("--converted", default="",
                   help="Markdown変換済みファイルのパス(_shared/source-conversion.md)")
    p.set_defaults(func=cmd_add_input)

    p = sub.add_parser("add-phase", help="plan に実行ステップを追記する")
    p.add_argument("dir", help="セッションディレクトリ")
    p.add_argument("--steps", action="append",
                   metavar="スキル名[:ゲート[:対象[:status]]]",
                   help="一括指定(複数回指定可。order は指定順に自動採番。推奨)")
    p.add_argument("--order", type=int, default=None,
                   help="実行順(単体指定時。省略時は末尾)")
    p.add_argument("--skill", default="", help="スキル名(例: qa-defect-analysis)")
    p.add_argument("--target", default="",
                   help="対象ラベル(成果物名の接尾辞。例: requirements)")
    p.add_argument("--gate", default=None,
                   help="所属ゲート({})".format(" / ".join(VALID_GATES)))
    p.add_argument("--status", default="pending",
                   help="初期 status(既定: pending)")
    p.set_defaults(func=cmd_add_phase)

    p = sub.add_parser("set-status", help="ステップの status を更新する")
    p.add_argument("dir", help="セッションディレクトリ")
    p.add_argument("order", type=int, help="対象ステップの order")
    p.add_argument("status",
                   help="新しい status({})".format(" / ".join(VALID_STATUSES)))
    p.add_argument("--output", default=None, help="成果物ファイル名(output に設定)")
    p.set_defaults(func=cmd_set_status)

    p = sub.add_parser("set-gate", help="承認ゲートの status を更新する")
    p.add_argument("dir", help="セッションディレクトリ")
    p.add_argument("gate", help="ゲート({})".format(" / ".join(VALID_GATES)))
    p.add_argument("status",
                   help="新しい status({})".format(" / ".join(VALID_GATE_STATUSES)))
    p.add_argument("--note", default="", help="承認時の条件・補足")
    p.set_defaults(func=cmd_set_gate)

    p = sub.add_parser("add-decision", help="decisions にユーザー判断を追記する")
    p.add_argument("dir", help="セッションディレクトリ")
    p.add_argument("--phase", required=True, type=int, help="関連ステップの order")
    p.add_argument("--decision", required=True, help="判断の本文")
    p.add_argument("--by", default="user", help="判断者(既定: user)")
    p.set_defaults(func=cmd_add_decision)

    p = sub.add_parser("add-note", help="improvement_notes に改善メモを追記する")
    p.add_argument("dir", help="セッションディレクトリ")
    p.add_argument("text", help="改善メモの本文")
    p.set_defaults(func=cmd_add_note)

    p = sub.add_parser("show", help="セッション概要を人間可読で表示する")
    p.add_argument("dir", help="セッションディレクトリ")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser(
        "resume-info",
        help="qa-output 配下の未完了セッションを要約表示する(qa-orchestrator Step 0 用)",
    )
    p.add_argument("root", nargs="?", default="./qa-output",
                   help="走査するルート(既定: ./qa-output)")
    p.set_defaults(func=cmd_resume_info)

    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
