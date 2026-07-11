#!/usr/bin/env python3
"""qa-session.json 管理CLI。

QAセッションファイル(qa-output/<セッション名>/qa-session.json)の作成・更新を
LLMの「読み込み→修正→全体書き戻し」の代わりに行う。定型処理をスクリプトに
寄せることで、JSON破損・タイムスタンプ不正確・トークン浪費を防ぐ。

スキーマ: .github/skills/_shared/session-schema.md
規約:     .github/skills/_shared/conventions.md §3, §6

使用例:
    python qa_session.py init qa-output/invoice-export --name invoice-export \\
        --feature "請求書エクスポート機能" --description "CSV/PDF出力の新規追加"
    python qa_session.py add-input qa-output/invoice-export --type spec \\
        --path docs/spec.md --note "仕様書 v2"
    python qa_session.py add-phase qa-output/invoice-export --order 1 \\
        --skill qa-defect-analysis
    python qa_session.py add-phase qa-output/invoice-export --order 4 \\
        --skill qa-spec-review --mode 1
    python qa_session.py set-status qa-output/invoice-export 1 in_progress
    python qa_session.py set-status qa-output/invoice-export 1 approved \\
        --output 01-defect-analysis.md
    python qa_session.py add-decision qa-output/invoice-export --phase 1 \\
        --decision "軽微な表記ゆれ不具合は分析対象から除外"
    python qa_session.py add-note qa-output/invoice-export "フェーズ2の質問が冗長"
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
    path = _session_path(args.dir)
    if os.path.exists(path):
        _fail("セッションファイルが既に存在します: {}".format(path))
    os.makedirs(args.dir, exist_ok=True)
    now = _now_iso()
    session = {
        "session_name": args.name,
        "created_at": now,
        "updated_at": now,
        "target": {
            "feature": args.feature,
            "description": args.description or "",
        },
        "inputs": [],
        "plan": [],
        "current_order": None,
        "decisions": [],
        "improvement_notes": [],
    }
    _save(args.dir, session, touch_updated=False)
    print("セッションを作成しました: {}".format(path))


def cmd_add_input(args):
    session = _load(args.dir)
    entry = {"type": args.type, "path": args.path, "note": args.note or ""}
    session.setdefault("inputs", []).append(entry)
    _save(args.dir, session)
    print("インプットを追加しました: type={} path={}".format(args.type, args.path))


def cmd_add_phase(args):
    if args.status not in VALID_STATUSES:
        _fail(
            "不正な status です: {} (許可: {})".format(
                args.status, " / ".join(VALID_STATUSES)
            )
        )
    session = _load(args.dir)
    if _find_phase(session, args.order) is not None:
        _fail("order={} のフェーズは既に存在します".format(args.order))
    phase = {"order": args.order, "skill": args.skill}
    if args.mode is not None:
        phase["mode"] = args.mode
    phase["status"] = args.status
    phase["output"] = None
    plan = session.setdefault("plan", [])
    plan.append(phase)
    plan.sort(key=lambda p: p.get("order", 0))
    _save(args.dir, session)
    print("フェーズを追加しました: order={} skill={}".format(args.order, args.skill))


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
        _fail("order={} のフェーズが見つかりません".format(args.order))
    phase["status"] = args.status
    if args.output is not None:
        phase["output"] = args.output
    if args.status == "in_progress":
        session["current_order"] = args.order
    _save(args.dir, session)
    print(
        "フェーズ {} ({}) の status を {} に更新しました".format(
            args.order, phase.get("skill", "?"), args.status
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
    print("フェーズ      : {} 件".format(len(plan)))
    for phase in plan:
        status = phase.get("status", "?")
        label = STATUS_LABELS.get(status, status)
        mode = phase.get("mode")
        output = phase.get("output")
        print(
            "  {:>3}. {}{} [{} / {}]{}".format(
                phase.get("order", "?"),
                phase.get("skill", "?"),
                " (mode {})".format(mode) if mode is not None else "",
                status,
                label,
                " -> {}".format(output) if output else "",
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
        print("  更新日時        : {}".format(session.get("updated_at", "?")))
        if completed:
            done = ", ".join(
                "{}. {}".format(p.get("order", "?"), p.get("skill", "?"))
                for p in completed
            )
        else:
            done = "(なし)"
        print("  完了済みフェーズ: {}".format(done))
        mode = next_phase.get("mode")
        print(
            "  次のフェーズ    : {}. {}{} [{}]".format(
                next_phase.get("order", "?"),
                next_phase.get("skill", "?"),
                " (mode {})".format(mode) if mode is not None else "",
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
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add-input", help="inputs にインプット資料を追記する")
    p.add_argument("dir", help="セッションディレクトリ")
    p.add_argument("--type", required=True,
                   help="資料種別(spec/plan/defects/pr/code/criteria 等)")
    p.add_argument("--path", required=True, help="資料のパスまたはURL")
    p.add_argument("--note", default="", help="補足メモ")
    p.set_defaults(func=cmd_add_input)

    p = sub.add_parser("add-phase", help="plan にフェーズを追記する")
    p.add_argument("dir", help="セッションディレクトリ")
    p.add_argument("--order", required=True, type=int, help="実行順(重複不可)")
    p.add_argument("--skill", required=True, help="スキル名(例: qa-defect-analysis)")
    p.add_argument("--mode", type=int, default=None,
                   help="モード番号(qa-spec-review 等)")
    p.add_argument("--status", default="pending",
                   help="初期 status(既定: pending)")
    p.set_defaults(func=cmd_add_phase)

    p = sub.add_parser("set-status", help="フェーズの status を更新する")
    p.add_argument("dir", help="セッションディレクトリ")
    p.add_argument("order", type=int, help="対象フェーズの order")
    p.add_argument("status",
                   help="新しい status({})".format(" / ".join(VALID_STATUSES)))
    p.add_argument("--output", default=None, help="成果物ファイル名(output に設定)")
    p.set_defaults(func=cmd_set_status)

    p = sub.add_parser("add-decision", help="decisions にユーザー判断を追記する")
    p.add_argument("dir", help="セッションディレクトリ")
    p.add_argument("--phase", required=True, type=int, help="関連フェーズの order")
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
