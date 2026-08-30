#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks アダプタ(各AIツールの hook 入出力方言を吸収する薄い層)。

判定そのものは行わない。**stdin の hook ペイロードを正規化し、`gate_check.py`
などを呼び、終了コードとメッセージに変換するだけ**。検証ロジックを増やしては
ならない(増やすなら gate_check.py 側へ)。

なぜアダプタが要るか(2026年8月時点の実測):

- ペイロードのキー名が違う   Claude Code は `tool_name` / `tool_input`、
                             GitHub Copilot CLI は `toolName` / `toolArgs`
- 出力スキーマが3方言ある     Claude Code は `hookSpecificOutput`、Copilot CLI は
                             `permissionDecision`、VS Code は `continue` / `stopReason`
- VS Code は matcher を無視する → **どのツール呼び出しかの判定はこちらで行う**

移植可能な契約は「**終了コード 0 / 2 と stderr のメッセージ**」だけなので、
そこを主、JSON 出力を従として扱う(3方言はキーが衝突しないため、1つのJSONに
まとめて出せば各ホストが自分の知るキーだけを読む)。

使用例(hook 設定から呼ぶ):
    python hook_entry.py session-start
    python hook_entry.py pre-bash
    python hook_entry.py pre-write
    python hook_entry.py post-write
    python hook_entry.py stop
    python hook_entry.py stop --warn-only     # 慣らし運転(exit 2 を出さない)

exit code:
    0 = 問題なし(処理を続行させる)
    2 = ブロック(理由は stderr。PostToolUse など阻止できないイベントでは
        stderr がモデルへのフィードバックになる)
    それ以外は使わない(ホストによっては fail-open / fail-closed が分かれるため)
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

SCRIPTS_DIR = Path(__file__).resolve().parent
GATE_CHECK = SCRIPTS_DIR / "gate_check.py"
QA_SESSION = SCRIPTS_DIR / "qa_session.py"

SESSION_FILE = "qa-session.json"
OUTPUT_ROOT = "qa-output"

# Stop hook が同一セッションで連続ブロックしてよい上限。
# これを超えたら警告に降格する(エージェントを無限ループに閉じ込めないため)。
MAX_STOP_BLOCKS = 2

# conventions.md §8: セッション内で直接追記してよい「プロジェクト資産」。
# これ以外の _shared/ 配下と各 SKILL.md はマスター資産(書き換え禁止)。
PROJECT_ASSETS = (
    "regression-viewpoint-catalog.md",
    "domain-glossary.md",
)

# マスター資産の保護対象(リポジトリルートからの相対パスの一部で判定)
PROTECTED_PREFIX = os.path.join(".github", "skills")

# ツール名の同定(VS Code は matcher を無視するため、ここで判定する)
SHELL_TOOLS = {
    "bash", "powershell", "shell", "sh", "zsh",
    "run_in_terminal", "runcommands", "execute",
}
WRITE_TOOLS = {
    "write", "edit", "multiedit", "notebookedit", "create",
    "str_replace_editor", "apply_patch", "createfile", "insertedit",
    "replace_string_in_file", "createandrunterminal",
}

# 成果物ファイル(conventions.md §6)。構造化成果物の .yaml も対象にする
# — YAMLが正なので、そちらこそスキーマ検証を掛ける意味がある
_ARTIFACT_RE = re.compile(r"^\d{2}-.+\.(?:md|ya?ml)$")


# ---------------------------------------------------------------------------
# 入力の正規化
# ---------------------------------------------------------------------------

def read_payload():
    """stdin の hook ペイロードを読む。空・不正でも落ちない({} を返す)。"""
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        # 落ちない(ワークフローを壊さない)が、黙って検証が無効になるのは
        # 事故のもとなので診断だけ残す
        print("hook_entry.py: ペイロードを解釈できません({})。検証をスキップします。"
              .format(e), file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def pick(payload, *names, default=None):
    """複数の候補キーから最初に見つかった値を返す(方言吸収)。"""
    for n in names:
        if n in payload and payload[n] not in (None, ""):
            return payload[n]
    return default


def tool_name(payload):
    return str(pick(payload, "tool_name", "toolName", "tool", default="")).strip()


def tool_args(payload):
    args = pick(payload, "tool_input", "toolArgs", "toolInput", "arguments", default={})
    return args if isinstance(args, dict) else {}


def base_cwd(payload):
    cwd = pick(payload, "cwd", "workingDirectory", default=None)
    if cwd and os.path.isdir(str(cwd)):
        return Path(str(cwd))
    return Path.cwd()


def is_shell_tool(name):
    return name.strip().lower() in SHELL_TOOLS


def is_write_tool(name):
    return name.strip().lower() in WRITE_TOOLS


def command_of(payload):
    """シェル系ツールの実行コマンド文字列を取り出す。"""
    args = tool_args(payload)
    for key in ("command", "cmd", "script", "commandLine", "input"):
        v = args.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def file_path_of(payload):
    """書き込み系ツールの対象ファイルパスを取り出す。"""
    args = tool_args(payload)
    for key in ("file_path", "filePath", "path", "notebook_path", "target_file", "uri"):
        v = args.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


# ---------------------------------------------------------------------------
# 出力(3方言を1つのJSONにまとめる。キーは衝突しない)
# ---------------------------------------------------------------------------

def emit(decision, event, reason, warn_only=False):
    """判定を各ホストの形式で出し、終了コードを返す。

    decision: "allow" / "deny" / "context"
    reason  : 人間とモデルが読む理由(stderr にも出す)
    """
    out = {}
    if decision == "deny":
        if warn_only:
            # 慣らし運転: 阻止せず、モデルに気づかせるだけ
            out["systemMessage"] = reason
            out["hookSpecificOutput"] = {
                "hookEventName": event, "additionalContext": reason,
            }
            print(json.dumps(out, ensure_ascii=False))
            print(reason, file=sys.stderr)
            return 0
        # Claude Code
        hso = {"hookEventName": event}
        if event in ("PreToolUse", "UserPromptSubmit"):
            hso["permissionDecision"] = "deny"
            hso["permissionDecisionReason"] = reason
        elif event in ("Stop", "SubagentStop"):
            hso["shouldContinue"] = True
            hso["systemMessage"] = reason
        else:
            hso["additionalContext"] = reason
        out["hookSpecificOutput"] = hso
        # GitHub Copilot CLI
        if event in ("PreToolUse", "PermissionRequest"):
            out["permissionDecision"] = "deny"
            out["permissionDecisionReason"] = reason
        elif event in ("Stop", "SubagentStop"):
            out["decision"] = "block"
            out["reason"] = reason
        # VS Code
        out["continue"] = False
        out["stopReason"] = reason
        print(json.dumps(out, ensure_ascii=False))
        print(reason, file=sys.stderr)
        return 2

    if decision == "context" and reason:
        out["hookSpecificOutput"] = {
            "hookEventName": event, "additionalContext": reason,
        }
        out["additionalContext"] = reason  # Copilot
        out["systemMessage"] = reason      # VS Code
        print(json.dumps(out, ensure_ascii=False))
        return 0

    return 0


# ---------------------------------------------------------------------------
# gate_check の呼び出し
# ---------------------------------------------------------------------------

def run_gate_check(cli_args):
    """gate_check.py を実行して (ok, report, stderr) を返す。"""
    if not GATE_CHECK.is_file():
        return True, None, "gate_check.py が見つかりません"
    try:
        proc = subprocess.run(
            [sys.executable, str(GATE_CHECK), *cli_args, "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as e:
        return True, None, "gate_check.py を実行できません: {}".format(e)
    if proc.returncode == 2:
        # 使用法エラー(対象なし等)はブロックしない
        return True, None, (proc.stderr or "").strip()
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return True, None, "gate_check.py の出力を解釈できません"
    return not report.get("failed"), report, ""


def summarize(report, limit=12):
    """レポートをモデルが読む数行に圧縮する。"""
    lines = []
    for f in report.get("lint", {}).get("files", []):
        for i in f.get("issues", []):
            if i.get("severity") != "ERROR":
                continue
            loc = " L{}".format(i["line"]) if i.get("line") else ""
            lines.append("  - {}{}: {}".format(
                os.path.basename(f["path"]), loc, i.get("message", "")))
    for f in report.get("schema", {}).get("files", []):
        for i in f.get("issues", []):
            if i.get("severity") != "ERROR":
                continue
            where = " [{}]".format(i["where"]) if i.get("where") else ""
            lines.append("  - {}{}: {}".format(
                os.path.basename(f["path"]), where, i.get("message", "")))
    for t in report.get("trace", {}).get("findings", []):
        lines.append("  - [{}] {}".format(t.get("check"), t.get("detail")))
    for r in report.get("render", {}).get("findings", []):
        first = str(r.get("detail", "")).splitlines()
        lines.append("  - {}: {}".format(r.get("file"), first[0] if first else ""))
    if len(lines) > limit:
        rest = len(lines) - limit
        lines = lines[:limit] + ["  - ...ほか {} 件".format(rest)]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# セッションの探索
# ---------------------------------------------------------------------------

def active_sessions(root):
    """未完了ステップが残っているセッションディレクトリを列挙する。"""
    out = []
    base = Path(root) / OUTPUT_ROOT
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        f = d / SESSION_FILE
        if not f.is_file():
            continue
        try:
            with open(f, encoding="utf-8") as fp:
                session = json.load(fp)
        except (OSError, json.JSONDecodeError):
            continue
        unfinished = [
            p for p in session.get("plan", []) or []
            if p.get("status") in ("pending", "in_progress", "awaiting_approval")
        ]
        if unfinished:
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# Stop の連続ブロック回数(無限ループ防止)
# ---------------------------------------------------------------------------

def _state_path(payload, root):
    key = "{}|{}".format(pick(payload, "session_id", "sessionId", default=""), root)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    d = Path(tempfile.gettempdir()) / "qa-hook-state"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return d / "{}.json".format(digest)


def block_count(payload, root, delta=0, reset=False):
    """Stop の連続ブロック回数を読み書きする。状態を持てない環境では 0 を返す。"""
    p = _state_path(payload, root)
    if p is None:
        return 0
    n = 0
    try:
        if p.is_file():
            n = int(json.loads(p.read_text(encoding="utf-8")).get("stop_blocks", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        n = 0
    if reset:
        n = 0
    n += delta
    try:
        p.write_text(json.dumps({"stop_blocks": n}), encoding="utf-8")
    except OSError:
        pass
    return n


# ---------------------------------------------------------------------------
# アクション
# ---------------------------------------------------------------------------

def action_session_start(payload, args):
    """SessionStart: 再開可能なセッションの情報を文脈に注入する。"""
    root = base_cwd(payload)
    if not (root / OUTPUT_ROOT).is_dir() or not QA_SESSION.is_file():
        return 0
    try:
        proc = subprocess.run(
            [sys.executable, str(QA_SESSION), "resume-info", OUTPUT_ROOT],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except OSError:
        return 0
    text = (proc.stdout or "").strip()
    if not text or "再開可能なセッションはありません" in text:
        return 0
    msg = (
        "【QAセッション】再開可能なセッションがあります。"
        "qa-orchestrator の Step 0 に従い、続きから再開するか新規セッションかを"
        "ユーザーに選択式で確認してください。\n\n" + text
    )
    return emit("context", "SessionStart", msg)


def action_pre_bash(payload, args):
    """PreToolUse(シェル): ゲート承認・ステップ完了の偽装を防ぐ。"""
    if not is_shell_tool(tool_name(payload)):
        return 0
    cmd = command_of(payload)
    if "qa_session.py" not in cmd:
        return 0
    root = base_cwd(payload)

    # set-gate <dir> <gate> approved
    m = re.search(
        r"set-gate\s+(?P<dir>[^\s\"']+|\"[^\"]+\"|'[^']+')\s+(?P<gate>G[1-5])\s+approved",
        cmd,
    )
    if m:
        session_dir = m.group("dir").strip("\"'")
        gate = m.group("gate")
        target = session_dir if os.path.isabs(session_dir) else str(root / session_dir)
        if not os.path.isdir(target):
            return 0
        ok, report, _ = run_gate_check([target, "--gate", gate])
        if ok:
            return 0
        reason = (
            "ゲート {gate} の承認を保留しました。このゲートが束ねる成果物に"
            "未解消の検出があります(conventions.md §9: ERROR を解消してから提示する)。\n"
            "{detail}\n"
            "解消してから再度 set-gate を実行してください。"
            "検出が誤りだと判断する場合は、その理由をユーザーに説明し判断を仰いでください。"
        ).format(gate=gate, detail=summarize(report))
        return emit("deny", "PreToolUse", reason, args.warn_only)

    # set-status <dir> <order> approved --output <file>
    m = re.search(
        r"set-status\s+(?P<dir>[^\s\"']+|\"[^\"]+\"|'[^']+')\s+\d+\s+approved"
        r"(?:.*?--output[= ]\s*(?P<out>[^\s\"']+|\"[^\"]+\"|'[^']+'))",
        cmd, re.S,
    )
    if m:
        session_dir = m.group("dir").strip("\"'")
        outfile = m.group("out").strip("\"'")
        base = session_dir if os.path.isabs(session_dir) else str(root / session_dir)
        target = os.path.join(base, os.path.basename(outfile))
        if not os.path.isfile(target):
            return 0
        ok, report, _ = run_gate_check(["--files", target])
        if ok:
            return 0
        reason = (
            "{name} に未解消の書式エラーがあります(conventions.md §9)。\n"
            "{detail}\n"
            "解消してから完了扱いにしてください。"
        ).format(name=os.path.basename(target), detail=summarize(report))
        return emit("deny", "PreToolUse", reason, args.warn_only)

    return 0


def action_pre_write(payload, args):
    """PreToolUse(書き込み): セッション中のマスター資産の書き換えを止める。"""
    if not is_write_tool(tool_name(payload)):
        return 0
    if os.environ.get("QA_ALLOW_MASTER_EDIT") == "1":
        return 0
    path = file_path_of(payload)
    if not path:
        return 0
    root = base_cwd(payload)

    # conventions.md §8 はセッション**内**での書き換えを禁じている。
    # 稼働中のセッションが無いときはメンテナンス作業とみなして通す。
    if not active_sessions(root):
        return 0

    norm = os.path.normpath(path).replace("\\", "/")
    if PROTECTED_PREFIX.replace("\\", "/") not in norm:
        return 0
    if os.path.basename(norm) in PROJECT_ASSETS:
        return 0  # プロジェクト資産はセッション内で育ててよい

    reason = (
        "マスター資産への書き込みを止めました: {path}\n"
        "conventions.md §8: マスター資産(SKILL.md・_shared/ 配下・scripts/)は"
        "セッション内で書き換えない。改善は 90-improvement.md に提案として書き出し、"
        "maintenance-log.md のトリアージを経てメンテナーが反映します。\n"
        "セッション内で直接育ててよいのはプロジェクト資産だけです: {assets}"
    ).format(path=path, assets=" / ".join(PROJECT_ASSETS))
    return emit("deny", "PreToolUse", reason, args.warn_only)


def action_post_write(payload, args):
    """PostToolUse(書き込み): 成果物を書いた直後に書式を検証する。"""
    if not is_write_tool(tool_name(payload)):
        return 0
    path = file_path_of(payload)
    if not path:
        return 0
    root = base_cwd(payload)
    target = path if os.path.isabs(path) else str(root / path)
    if not os.path.isfile(target):
        return 0
    norm = os.path.normpath(target).replace("\\", "/")
    if "/{}/".format(OUTPUT_ROOT) not in norm:
        return 0
    if not _ARTIFACT_RE.match(os.path.basename(norm)):
        return 0

    ok, report, _ = run_gate_check(["--files", target])
    if ok:
        return 0
    reason = (
        "{name} に書式エラーがあります(conventions.md §9: 要約を提示する前に解消する)。\n"
        "{detail}"
    ).format(name=os.path.basename(target), detail=summarize(report))
    # PostToolUse は阻止できない。stderr がモデルへのフィードバックになる
    return emit("deny", "PostToolUse", reason, args.warn_only)


def action_stop(payload, args):
    """Stop: 未承認ゲートの成果物に未解消の検出があるうちは終わらせない。"""
    if payload.get("stop_hook_active") or payload.get("stopHookActive"):
        return 0
    root = base_cwd(payload)
    sessions = active_sessions(root)
    if not sessions:
        block_count(payload, str(root), reset=True)
        return 0

    problems = []
    for d in sessions:
        ok, report, _ = run_gate_check([str(d), "--unapproved"])
        if not ok:
            problems.append((d, report))
    if not problems:
        block_count(payload, str(root), reset=True)
        return 0

    n = block_count(payload, str(root), delta=1)
    detail = "\n".join(
        "■ {}\n{}".format(d.name, summarize(rep)) for d, rep in problems
    )
    if n > MAX_STOP_BLOCKS:
        # **カウンタをリセットしない。** 一度降格したら、検出が解消されるまで
        # このセッションでは二度と止めない(ブロックと通過を繰り返して
        # エージェントを振動させないため)。リセットは検出が消えたときだけ。
        msg = (
            "未解消の検出が残っていますが、{n} 回止めたのでこれ以上は止めません。"
            "**解消したことにせず**、残っている検出をそのままユーザーに報告してください。\n"
            "{detail}"
        ).format(n=MAX_STOP_BLOCKS, detail=detail)
        return emit("context", "Stop", msg)

    reason = (
        "未承認ゲートの成果物に未解消の検出があります"
        "(conventions.md §9)。解消してから完了してください。\n"
        "{detail}\n"
        "検出が誤りだと判断する場合は、解消したことにせず理由をユーザーに説明してください。"
    ).format(detail=detail)
    return emit("deny", "Stop", reason, args.warn_only)


def action_subagent_stop(payload, args):
    """SubagentStop: サブエージェントの成果物を検証する(契約JSON検証は Phase 3)。"""
    return action_stop(payload, args)


ACTIONS = {
    "session-start": action_session_start,
    "pre-bash": action_pre_bash,
    "pre-write": action_pre_write,
    "post-write": action_post_write,
    "stop": action_stop,
    "subagent-stop": action_subagent_stop,
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="hook_entry.py",
        description=(
            "hooks アダプタ。stdin の hook ペイロードを正規化して gate_check.py を呼び、"
            "終了コードとメッセージに変換する。判定ロジックは持たない。"
        ),
        epilog="exit code: 0=続行 / 2=ブロック(理由は stderr)。",
    )
    parser.add_argument("action", choices=sorted(ACTIONS),
                        help="hook イベントに対応するアクション")
    parser.add_argument("--warn-only", action="store_true",
                        help="ブロックせず警告だけ返す(段階導入時の慣らし運転用)")
    args = parser.parse_args(argv)

    payload = read_payload()
    try:
        return ACTIONS[args.action](payload, args)
    except Exception as e:  # hook が落ちてワークフローを壊さないこと
        print("hook_entry.py の内部エラー(処理は続行します): {}".format(e),
              file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
