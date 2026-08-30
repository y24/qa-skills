#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""承認ゲート単位の成果物検証(単一の検証入口)。

`lint_output.py`(書式)と `trace_check.py`(ID突合)を**ゲート単位で束ねる**。
SKILL.md の手順・hooks(`hook_entry.py`)・CI のいずれからも**このスクリプトを
呼ぶ**ことで、判定基準が3箇所に分裂するのを防ぐ(conventions.md §9)。

**このスクリプトは書式と突合しか見ない。** 指摘の妥当性・分析の正しさ・観点の
網羅性は判定しない(scripts/README.md「責務の境界」)。

使用例:
    python gate_check.py qa-output/my-session                  # 全成果物
    python gate_check.py qa-output/my-session --gate G3        # G3が束ねる成果物だけ
    python gate_check.py qa-output/my-session --unapproved     # 未承認ゲートの分だけ
    python gate_check.py --files qa-output/my-session/30-test-viewpoint.md
    python gate_check.py qa-output/my-session --json
    python gate_check.py qa-output/my-session --warn-only      # 常に exit 0(段階導入用)
    python gate_check.py qa-output/my-session --lint-only      # 書式だけ見る

ゲートと成果物の対応:
    qa-session.json の `plan`(各ステップの `gate` と `output`)を**正**とする。
    セッションファイルが無い場合のみ、下の静的表にフォールバックする。

Quick モードの扱い(skill-map.md §2「網羅を主張しないモードに網羅の手続きを
課さない」):
    run_mode が `quick` の場合、および**セッションファイルが存在しない場合**
    (Quick はセッションファイルを作らなくてよい)は、trace_check を実行せず
    lint のみを行う。

exit code:
    0 = 未解消なし(WARN と trace の info は含みうる)
    1 = lint ERROR または trace の検出あり(--warn-only 指定時は 0 に落とす)
    2 = 使用法エラー(ディレクトリ不存在等)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lint_output  # noqa: E402
import render_md  # noqa: E402
import validate_artifact  # noqa: E402

SESSION_FILE = "qa-session.json"

# 構造化成果物(YAMLが正・Markdownは生成物)。conventions.md §6 の命名に従う
YAML_ARTIFACT_RE = validate_artifact.ARTIFACT_RE

# ---------------------------------------------------------------------------
# skill-map.md §3: 承認ゲートが束ねる成果物
# セッションファイルが無いときのフォールバック。定義元は skill-map.md であり、
# ゲートの割り当てを変えたらここも追随させること(skill-map.md §5)。
# 値は lint_output.FIXED_NAMES の成果物種別。
# ---------------------------------------------------------------------------
GATE_ARTIFACTS = {
    "G1": (),  # 実行計画のみ。成果物を持たない
    "G2": ("source-analysis", "defect-analysis", "spec-review"),
    "G3": ("intent-recovery", "scenario-design"),
    "G4": ("test-strategy", "test-plan", "test-viewpoint", "test-case",
           "test-data", "code-review"),
    "G5": ("test-design-review", "improvement"),
}

# skill-map.md §3 のゲート名
VALID_GATES = tuple(GATE_ARTIFACTS)

# qa_session.py と同じ定義(承認済み扱いにする gate status)
SETTLED_GATE_STATUSES = ("approved", "skipped")

_ARTIFACT_TYPE_OF = {}  # 成果物種別 -> 所属ゲート(静的表の逆引き)
for _gate, _types in GATE_ARTIFACTS.items():
    for _t in _types:
        _ARTIFACT_TYPE_OF[_t] = _gate


def artifact_type_of(filename):
    """ファイル名から成果物種別を返す(conventions.md §6 の `NN-<固定名>[-<対象>].md`)。"""
    base = os.path.basename(filename)
    m = re.match(r"^(\d{2})-(.+?)(?:-.+)?\.md$", base)
    if not m:
        return None
    name = m.group(2)
    if name in lint_output.FIXED_NAMES:
        return lint_output.FIXED_NAMES[name][1]
    # `40-spec-review-requirements.md` のように接尾辞が付く場合、
    # 最長一致の固定名で判定する
    stem = base[3:-3] if len(base) > 6 else ""
    for fixed in sorted(lint_output.FIXED_NAMES, key=len, reverse=True):
        if stem == fixed or stem.startswith(fixed + "-"):
            return lint_output.FIXED_NAMES[fixed][1]
    return None


# ---------------------------------------------------------------------------
# セッションファイル
# ---------------------------------------------------------------------------

def load_session(session_dir):
    """qa-session.json を読む。存在しない・壊れている場合は None。"""
    path = Path(session_dir) / SESSION_FILE
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def gate_of_artifact(filename, session):
    """成果物ファイル名から所属ゲートを解決する。session の plan を優先する。"""
    base = os.path.basename(filename)
    if session:
        for step in session.get("plan", []) or []:
            if step.get("output") and os.path.basename(step["output"]) == base:
                gate = step.get("gate")
                if gate in GATE_ARTIFACTS:
                    return gate
    atype = artifact_type_of(base)
    return _ARTIFACT_TYPE_OF.get(atype)


def unsettled_gates(session):
    """まだ承認・スキップされていないゲートの集合。session が無ければ全ゲート。"""
    if not session:
        return set(VALID_GATES)
    settled = {
        g.get("gate")
        for g in session.get("gates", []) or []
        if g.get("status") in SETTLED_GATE_STATUSES
    }
    return set(VALID_GATES) - settled


# ---------------------------------------------------------------------------
# 対象の解決
# ---------------------------------------------------------------------------

def find_artifacts(session_dir):
    """セッションディレクトリ配下の成果物 `NN-*.md` を列挙する。"""
    d = Path(session_dir)
    return sorted(
        str(p) for p in d.iterdir()
        if p.is_file() and lint_output.SESSION_FILE_RE.match(p.name)
    )


def find_structured(session_dir):
    """構造化成果物 `NN-*.yaml` を列挙する(まだ無いセッションもある)。"""
    d = Path(session_dir)
    return sorted(
        str(p) for p in d.iterdir()
        if p.is_file() and YAML_ARTIFACT_RE.match(p.name)
    )


def select_targets(session_dir, session, gate=None, unapproved=False):
    """検証対象の成果物パス一覧と、選択理由を返す。"""
    files = find_artifacts(session_dir)
    if gate:
        wanted = {gate}
        reason = "ゲート {} が束ねる成果物".format(gate)
    elif unapproved:
        wanted = unsettled_gates(session)
        reason = "未承認ゲート({})が束ねる成果物".format(
            ", ".join(sorted(wanted)) if wanted else "なし"
        )
    else:
        return files, "セッション内の全成果物", []

    selected, excluded = [], []
    for f in files:
        g = gate_of_artifact(f, session)
        if g in wanted:
            selected.append(f)
        else:
            excluded.append((os.path.basename(f), g or "(ゲート不明)"))
    return selected, reason, excluded


# ---------------------------------------------------------------------------
# 検査の実行
# ---------------------------------------------------------------------------

def run_lint(paths):
    """lint_output を import して実行し、結果リストを返す。"""
    return [lint_output.lint_file(p) for p in paths]


def run_trace(session_dir):
    """trace_check.py を別プロセスで実行し、JSON を返す。

    trace_check.py の検査ロジックは main() の中にあり関数として切り出されて
    いないため、既存ファイルを変更せずに使うにはサブプロセス実行が確実。
    """
    script = Path(__file__).resolve().parent / "trace_check.py"
    if not script.is_file():
        return {"available": False, "note": "trace_check.py が見つかりません"}
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(session_dir), "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as e:
        return {"available": False, "note": "trace_check.py を実行できません: {}".format(e)}
    if proc.returncode == 2:
        return {"available": False, "note": (proc.stderr or "").strip() or "使用法エラー"}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"available": False, "note": "trace_check.py の出力を解釈できません"}
    payload["available"] = True
    return payload


def run_schema(paths):
    """構造化成果物をスキーマ検証する(validate_artifact を import して実行)。"""
    return [validate_artifact.validate(p) for p in paths]


def run_render_check(paths):
    """Markdown が YAML から生成された内容と一致するかを見る。

    一致しない場合は「Markdownを直接編集した」か「YAMLを変えて再生成していない」。
    どちらも『YAMLが正』の前提が壊れているので検出する。
    """
    out = []
    for p in paths:
        status, msg = render_md.process(p, check=True)
        if status in ("ok", "skipped"):
            continue
        out.append({"file": os.path.basename(p), "status": status, "detail": msg})
    return out


def trace_findings(trace, scope=None):
    """trace_check の結果から、対応が要る検出(status=finding)だけを平坦化する。

    trace_check.py はセッションディレクトリ全体を突合するため、ゲートで絞って
    いるときは**対象外の成果物だけに起因する検出を落とす**。他ゲートの問題で
    目の前のゲートを止めないため。`scope` は対象ファイル名(basename)の集合。
    """
    out = []
    for c in trace.get("checks", []) or []:
        if c.get("status") != "finding":
            continue
        for f in c.get("findings", []) or []:
            if scope is not None:
                fname = f.get("file")
                if fname and os.path.basename(fname) not in scope:
                    continue
            out.append({"check": c.get("name"), "detail": f.get("detail", "")})
    return out


# ---------------------------------------------------------------------------
# レポート
# ---------------------------------------------------------------------------

def build_report(args, session_dir, session, targets, reason, excluded,
                 lint_results, trace, schema_results=None, render_findings=None):
    run_mode = (session or {}).get("run_mode")
    errors = sum(r.errors for r in lint_results)
    warnings = sum(r.warnings for r in lint_results)
    schema_results = schema_results or []
    render_findings = render_findings or []
    schema_errors = sum(r.errors for r in schema_results)
    schema_warnings = sum(r.warnings for r in schema_results)
    # ゲートで絞っているときは、対象成果物に起因する検出だけを見る
    narrowed = bool(args.gate or args.unapproved)
    scope = {os.path.basename(t) for t in targets} if narrowed else None
    tfindings = trace_findings(trace, scope) if trace.get("available") else []

    # trace_check.py 自身の exit code 意味論に合わせる: status=finding は失敗、
    # status=info(未展開観点・未反映シナリオ)は失敗にしない。判定基準を
    # こちらで勝手に緩めない(緩めるべきなら trace_check.py 側を直す)。
    failed = errors > 0 or schema_errors > 0 or bool(render_findings)
    if tfindings and not args.lint_only:
        failed = True

    return {
        "session_dir": str(session_dir) if session_dir else None,
        "run_mode": run_mode,
        "gate": args.gate,
        "selection": reason,
        "excluded": [{"file": f, "gate": g} for f, g in excluded],
        "targets": [os.path.basename(t) for t in targets],
        "lint": {
            "errors": errors,
            "warnings": warnings,
            "files": [
                {
                    "path": r.path,
                    "artifact_type": r.artifact_type,
                    "errors": r.errors,
                    "warnings": r.warnings,
                    "issues": r.issues,
                }
                for r in lint_results
            ],
        },
        "trace": {
            "ran": bool(trace.get("available")),
            "note": trace.get("note"),
            "findings": tfindings,
        },
        "schema": {
            "ran": bool(schema_results),
            "errors": schema_errors,
            "warnings": schema_warnings,
            "files": [
                {"path": r.path, "artifact": r.artifact,
                 "errors": r.errors, "warnings": r.warnings, "issues": r.issues}
                for r in schema_results
            ],
        },
        "render": {"findings": render_findings},
        "failed": failed,
        "warn_only": bool(args.warn_only),
        "note": (
            "書式とID突合の機械チェック。指摘の妥当性・網羅性は判定しない"
            "(scripts/README.md 責務の境界)"
        ),
    }


def print_text_report(rep):
    print("# ゲート検証レポート(機械チェック)")
    print()
    print("> ⚠️ 書式とID突合だけを見ている。**内容の質は判定していない。**")
    print()
    if rep["session_dir"]:
        print("対象ディレクトリ: {}".format(rep["session_dir"]))
    print("実行モード      : {}".format(rep["run_mode"] or "(不明 — セッションファイルなし)"))
    print("選択            : {}".format(rep["selection"]))
    print()

    if not rep["targets"]:
        print("検証対象の成果物はありません。")
    else:
        print("## 検証対象")
        for name in rep["targets"]:
            print("- {}".format(name))
        print()

    if rep["excluded"]:
        print("## 対象外(他ゲートに属する成果物)")
        for e in rep["excluded"]:
            print("- {} [{}]".format(e["file"], e["gate"]))
        print()

    print("## lint(書式・evidence_level・ID書式)")
    print("ERROR {} 件 / WARN {} 件".format(rep["lint"]["errors"], rep["lint"]["warnings"]))
    for f in rep["lint"]["files"]:
        shown = [i for i in f["issues"] if i["severity"] == "ERROR"]
        if not shown:
            continue
        print("  {}".format(os.path.basename(f["path"])))
        for i in shown:
            loc = " {}行目".format(i["line"]) if i.get("line") else ""
            print("    - ERROR{}: [{}] {}".format(loc, i["check"], i["message"]))
    print()

    print("## trace(成果物間のID突合)")
    if not rep["trace"]["ran"]:
        print("スキップ: {}".format(rep["trace"]["note"] or "実行しませんでした"))
    else:
        fs = rep["trace"]["findings"]
        print("検出 {} 件".format(len(fs)))
        for f in fs:
            print("    - [{}] {}".format(f["check"], f["detail"]))
    print()

    if rep["schema"]["ran"]:
        print("## schema(構造化成果物の規約検証)")
        print("ERROR {} 件 / WARN {} 件".format(
            rep["schema"]["errors"], rep["schema"]["warnings"]))
        for f in rep["schema"]["files"]:
            shown = [i for i in f["issues"] if i["severity"] == "ERROR"]
            if not shown:
                continue
            print("  {}".format(os.path.basename(f["path"])))
            for i in shown:
                where = " [{}]".format(i["where"]) if i.get("where") else ""
                print("    - ERROR{}: [{}] {}".format(where, i["rule"], i["message"]))
        print()

    if rep["render"]["findings"]:
        print("## render(Markdown が YAML と一致しているか)")
        for f in rep["render"]["findings"]:
            first = str(f["detail"]).splitlines()[0]
            print("    - {}: {}".format(f["file"], first))
        print()

    if rep["failed"]:
        parts = []
        if rep["lint"]["errors"]:
            parts.append("lint ERROR {} 件".format(rep["lint"]["errors"]))
        if rep["schema"]["errors"]:
            parts.append("schema ERROR {} 件".format(rep["schema"]["errors"]))
        if rep["trace"]["findings"]:
            parts.append("trace 検出 {} 件".format(len(rep["trace"]["findings"])))
        if rep["render"]["findings"]:
            parts.append("render ずれ {} 件".format(len(rep["render"]["findings"])))
        detail = " / ".join(parts)
        if rep["warn_only"]:
            print("判定: 未解消あり({})(--warn-only のため exit 0)".format(detail))
        else:
            print("判定: **BLOCK** — {} を解消してから次へ進むこと(conventions.md §9)"
                  .format(detail))
    else:
        print("判定: PASS(書式・突合の範囲で未解消なし)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="gate_check.py",
        description=(
            "承認ゲート単位で成果物を検証する単一の入口。"
            "lint_output.py と trace_check.py を束ねる。"
            "書式とID突合のみを見ており、内容の質は判定しない。"
        ),
        epilog=(
            "exit code: 0=未解消なし / 1=ERROR あり / 2=使用法エラー。"
            "定義元: skill-map.md §3(ゲート)・conventions.md §6(成果物名)・§9(規律)。"
        ),
    )
    parser.add_argument("session_dir", nargs="?",
                        help="セッションディレクトリ(qa-output/<セッション名>)")
    parser.add_argument("--files", nargs="+", metavar="FILE",
                        help="セッションを介さず個別の成果物を検証する(lint のみ)")
    parser.add_argument("--gate", choices=VALID_GATES,
                        help="このゲートが束ねる成果物だけを検証する")
    parser.add_argument("--unapproved", action="store_true",
                        help="未承認・未スキップのゲートに属する成果物だけを検証する")
    parser.add_argument("--lint-only", action="store_true", dest="lint_only",
                        help="trace の検出を失敗に数えない(書式だけを見る)")
    parser.add_argument("--warn-only", action="store_true",
                        help="検出があっても exit 0 を返す(段階導入時の慣らし運転用)")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="機械可読JSONで出力する")
    args = parser.parse_args(argv)

    if args.files and args.session_dir:
        parser.error("--files とセッションディレクトリは同時に指定できません")
    if args.files and (args.gate or args.unapproved):
        parser.error("--files は --gate / --unapproved と併用できません")
    if args.gate and args.unapproved:
        parser.error("--gate と --unapproved は併用できません")

    # --- 個別ファイルモード(PostToolUse 用): 1ファイル単位で見られる検査だけ ---
    if args.files:
        missing = [p for p in args.files if not os.path.isfile(p)]
        if missing:
            parser.error("ファイルが存在しません: {}".format(", ".join(missing)))
        md_files = [p for p in args.files if p.lower().endswith(".md")]
        yaml_files = [p for p in args.files
                      if YAML_ARTIFACT_RE.match(os.path.basename(p))]
        lint_results = run_lint(md_files)
        schema_results = run_schema(yaml_files)
        render_findings = run_render_check(yaml_files)
        rep = build_report(
            args, None, None, args.files, "指定されたファイル", [],
            lint_results, {"available": False, "note": "個別ファイルモードでは実行しない"},
            schema_results, render_findings,
        )
        if args.as_json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            print_text_report(rep)
        return 0 if (args.warn_only or not rep["failed"]) else 1

    if not args.session_dir:
        parser.error("セッションディレクトリまたは --files を指定してください")
    session_dir = Path(args.session_dir)
    if not session_dir.is_dir():
        print("エラー: ディレクトリが存在しません: {}".format(session_dir), file=sys.stderr)
        return 2

    session = load_session(session_dir)
    targets, reason, excluded = select_targets(
        session_dir, session, gate=args.gate, unapproved=args.unapproved
    )
    lint_results = run_lint(targets)

    # skill-map.md §2: Quick モード(およびセッションファイルが無い場合)には
    # 網羅の手続きを課さない。trace_check は実行しない。
    run_mode = (session or {}).get("run_mode")
    if session is None:
        trace = {"available": False,
                 "note": "セッションファイルなし(Quick 想定) — skill-map.md §2 により実行しない"}
    elif run_mode == "quick":
        trace = {"available": False,
                 "note": "run_mode=quick — skill-map.md §2 により実行しない"}
    elif not targets:
        trace = {"available": False, "note": "検証対象の成果物がないため実行しない"}
    else:
        trace = run_trace(session_dir)

    # 構造化成果物(YAMLが正)。ゲートで絞るときは Markdown 側と同じ割り当てで絞る
    structured = find_structured(session_dir)
    if args.gate or args.unapproved:
        wanted = {args.gate} if args.gate else unsettled_gates(session)
        structured = [
            p for p in structured
            if gate_of_artifact(Path(p).with_suffix(".md").name, session) in wanted
        ]
    schema_results = run_schema(structured)
    render_findings = run_render_check(structured)

    rep = build_report(args, session_dir, session, targets, reason, excluded,
                       lint_results, trace, schema_results, render_findings)
    if args.as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print_text_report(rep)
    return 0 if (args.warn_only or not rep["failed"]) else 1


if __name__ == "__main__":
    sys.exit(main())
