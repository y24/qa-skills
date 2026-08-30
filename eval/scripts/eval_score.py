#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""評価ランの採点(答えキー照合)。

スキルセットの実効性を測るための採点スクリプト。評価用フィクスチャ
(eval/fixtures/<名前>/)に対して QA フローを1本回した結果のセッション
ディレクトリを、あらかじめ用意した**答えキー**(eval/answer-key/<名前>/)と
機械的に突き合わせ、検出率・未照合エントリ・成果物指標を1枚にまとめる。

**採点は評価ではない。** ここで出るのは「仕込んだ項目が拾えたか」であって、
成果物の良し悪しではない。誤指摘(答えキーに無い指摘が妥当かどうか)は
機械判定しない — 未照合エントリとして列挙し、人が見る(eval/README.md §5)。

サブコマンド:
  score     セッションディレクトリを答えキーと突き合わせ、採点結果を出力する
  compare   ラン台帳(runs.csv)の2ランを比較し、差分を表示する
  selftest  採点ロジック自身の自己検査(検出できること・誤検出しないこと)

使用例:
  python eval/scripts/eval_score.py score qa-output/eval-prq-01 --key eval/answer-key/prq
  python eval/scripts/eval_score.py score qa-output/eval-prq-01 --key eval/answer-key/prq \
      --run-id 2026-09-01-a --append eval/runs/runs.csv --out eval/runs/2026-09-01-a.json
  python eval/scripts/eval_score.py compare eval/runs/runs.csv --baseline 2026-09-01-a --target 2026-09-08-a
  python eval/scripts/eval_score.py selftest

依存: Python 3.9+ 標準ライブラリのみ。metrics.py があれば取り込むが、無くても動く。

exit code: 0=採点完了 / 2=使用法エラー / 3=採点無効(答えキーがランの入力に混入)
"""

import argparse
import csv
import io
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
QA_SCRIPTS = REPO_ROOT / ".github" / "skills" / "_shared" / "scripts"

# 答えキーの列(定義元は本ファイル。eval/answer-key/<名前>/*.csv が従う)
KEY_COLUMNS = ("id", "category", "title", "target", "match", "difficulty", "rationale")

# カテゴリごとの既定の探索先と「エントリの目印」。
#   targets  : セッションディレクトリからの glob。答えキーの target 列で上書きできる
#   entry_re : 指摘・項目1件を表すID。これを含むレコードだけを照合対象にすることで、
#              叙述文の言い回しがたまたま一致する誤ヒットを避ける(None なら全レコード)
# 成果物名の定義元は conventions.md §6、ID体系は §6-1。
CATEGORY_SPEC = {
    "ambiguity": {
        "targets": ["40-spec-review*.md", "42-test-design-review.md"],
        "entry_re": r"AMB-\d+",
        "label": "曖昧性・仕様の欠落",
    },
    "transition": {
        "targets": ["10-intent-recovery.md"],
        "entry_re": r"TRN-\d+",
        "label": "状態遷移",
    },
    "handoff": {
        "targets": ["10-intent-recovery.md", "11-scenario-design.md"],
        "entry_re": None,
        "label": "ロール間の引き継ぎ",
    },
    "scenario": {
        "targets": ["11-scenario-design.md"],
        "entry_re": r"SC-\d+",
        "label": "業務シナリオ",
    },
    "regression": {
        "targets": ["01-defect-analysis.md", "30-test-viewpoint.md"],
        "entry_re": None,
        "label": "回帰観点",
    },
}

CATEGORY_ORDER = ("ambiguity", "transition", "handoff", "scenario", "regression")
DIFFICULTIES = ("A", "B", "C")

RUNS_COLUMNS = [
    "run_id", "date", "fixture", "session_dir", "run_mode", "model", "skillset_rev",
    "recall_overall", "recall_ambiguity", "recall_transition", "recall_handoff",
    "recall_scenario", "recall_regression", "recall_a", "recall_b", "recall_c",
    "unmatched", "groundless_rate", "trace_rate", "gates_approved", "loopbacks",
    "hits", "note",
]


def err(msg):
    print(msg, file=sys.stderr)


def die(msg, code=2):
    err("エラー: {}".format(msg))
    sys.exit(code)


# ---------------------------------------------------------------------------
# 正規化と照合
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(r"[\s,、]+")


def normalize(text):
    """照合用の正規化。

    全角/半角・大文字小文字・空白・カンマの違いを吸収する(「10万」「１０万」
    「100,000」が同じ土俵に乗る)。意味は変えない — 語そのものは削らない。
    """
    text = unicodedata.normalize("NFKC", text or "").lower()
    return _STRIP_RE.sub("", text)


def parse_match(expr):
    """`グループ;グループ` / 各グループは `語|語` の別表記。全グループが必要。"""
    groups = []
    for raw in (expr or "").split(";"):
        alts = [normalize(a) for a in raw.split("|") if a.strip()]
        if alts:
            groups.append(alts)
    return groups


def matches(record_norm, groups):
    return bool(groups) and all(
        any(alt in record_norm for alt in alts) for alts in groups
    )


# ---------------------------------------------------------------------------
# 成果物の読み込み(レコード分割)
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|?$")


def read_text(path):
    for enc in ("utf-8-sig", "cp932"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def split_records(path):
    """成果物を「1件の主張」に近い単位へ割る。

    表の1行、または空行で区切られた段落を1レコードとし、**直近の見出しを
    前置する**。見出しを前置するのは、詳細節(`### SC-06 …`)の中の手順行にも
    その項目のIDと題名を持たせるため — これでIDを目印にした絞り込みが効く。
    """
    records = []
    heading = ""
    buf = []

    def flush():
        if buf:
            records.append((heading + " " + " ".join(buf)).strip())
            del buf[:]

    for line in read_text(path).splitlines():
        stripped = line.strip()
        m = _HEADING_RE.match(stripped)
        if m:
            flush()
            heading = m.group(1).strip()
            records.append(heading)
            continue
        if not stripped:
            flush()
            continue
        if stripped.startswith("|"):
            flush()
            if _TABLE_SEP_RE.match(stripped):
                continue
            records.append((heading + " " + stripped).strip())
            continue
        buf.append(stripped)
    flush()
    return records


def collect_records(session_dir, patterns):
    """対象ファイル群のレコードを (ファイル名, 原文, 正規化後) で返す。"""
    out = []
    seen = set()
    for pat in patterns:
        for path in sorted(Path(session_dir).glob(pat)):
            if not path.is_file() or path.name in seen:
                continue
            seen.add(path.name)
            for rec in split_records(path):
                out.append((path.name, rec, normalize(rec)))
    return out


# ---------------------------------------------------------------------------
# 答えキー
# ---------------------------------------------------------------------------

def load_key(key_dir):
    key_dir = Path(key_dir)
    if not key_dir.is_dir():
        die("答えキーのディレクトリがありません: {}".format(key_dir))
    items = []
    for path in sorted(key_dir.glob("*.csv")):
        rows = list(csv.DictReader(io.StringIO(read_text(path))))
        for i, row in enumerate(rows, start=2):
            missing = [c for c in KEY_COLUMNS if c not in row]
            if missing:
                die("{}: 列が足りません: {}".format(path.name, ", ".join(missing)))
            cat = (row["category"] or "").strip()
            if cat not in CATEGORY_SPEC:
                die("{} {}行目: 未知の category「{}」(有効: {})".format(
                    path.name, i, cat, " / ".join(CATEGORY_ORDER)))
            groups = parse_match(row["match"])
            if not groups:
                die("{} {}行目: match が空です({})".format(path.name, i, row["id"]))
            items.append({
                "id": (row["id"] or "").strip(),
                "category": cat,
                "title": (row["title"] or "").strip(),
                "targets": [t.strip() for t in (row["target"] or "").split(";") if t.strip()]
                           or CATEGORY_SPEC[cat]["targets"],
                "groups": groups,
                "difficulty": (row["difficulty"] or "").strip().upper() or "B",
                "rationale": (row["rationale"] or "").strip(),
            })
    if not items:
        die("答えキーが1件もありません: {}".format(key_dir))
    return items


# ---------------------------------------------------------------------------
# 採点
# ---------------------------------------------------------------------------

def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def score_session(session_dir, key_items):
    session_dir = Path(session_dir)
    cache = {}

    def records_for(patterns):
        k = tuple(patterns)
        if k not in cache:
            cache[k] = collect_records(session_dir, patterns)
        return cache[k]

    results = []
    matched_records = set()  # (ファイル名, 原文) 照合に使われたレコード
    for item in key_items:
        recs = records_for(item["targets"])
        hit = None
        for fname, raw, norm in recs:
            if matches(norm, item["groups"]):
                hit = {"file": fname, "excerpt": raw[:160]}
                matched_records.add((fname, raw))
                break
        results.append(dict(item, detected=hit is not None, hit=hit))

    # 未照合エントリ: 答えキーのどれにも当たらなかった「ID付きの指摘・項目」。
    # 誤指摘かもしれないし、キーに無い正しい発見かもしれない。**機械では決めない。**
    unmatched = []
    for cat in CATEGORY_ORDER:
        spec = CATEGORY_SPEC[cat]
        if not spec["entry_re"]:
            continue
        entry_re = re.compile(spec["entry_re"], re.IGNORECASE)
        targets = spec["targets"]
        seen_ids = {}
        for fname, raw, _norm in records_for(targets):
            for eid in entry_re.findall(raw):
                seen_ids.setdefault(eid.upper(), []).append((fname, raw))
        for eid, recs in sorted(seen_ids.items()):
            if any((f, r) in matched_records for f, r in recs):
                continue
            unmatched.append({
                "category": cat, "entry_id": eid,
                "file": recs[0][0], "excerpt": recs[0][1][:160],
            })
    return results, unmatched


def summarize(results):
    by_cat = {}
    for cat in CATEGORY_ORDER:
        rows = [r for r in results if r["category"] == cat]
        if rows:
            hits = sum(1 for r in rows if r["detected"])
            by_cat[cat] = {"hit": hits, "total": len(rows), "率": pct(hits, len(rows))}
    by_diff = {}
    for d in DIFFICULTIES:
        rows = [r for r in results if r["difficulty"] == d]
        if rows:
            hits = sum(1 for r in rows if r["detected"])
            by_diff[d] = {"hit": hits, "total": len(rows), "率": pct(hits, len(rows))}
    hits = sum(1 for r in results if r["detected"])
    return {
        "カテゴリ別": by_cat,
        "難易度別": by_diff,
        "全体": {"hit": hits, "total": len(results), "率": pct(hits, len(results))},
    }


# ---------------------------------------------------------------------------
# 周辺情報(既存スクリプト・セッションファイルからの取り込み)
# ---------------------------------------------------------------------------

def run_metrics(session_dir):
    """metrics.py を呼んで指標を取り込む(無ければ None)。"""
    script = QA_SCRIPTS / "metrics.py"
    if not script.is_file():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(session_dir), "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
        )
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout.decode("utf-8", "replace"))
    except Exception:
        return None


def read_session(session_dir):
    path = Path(session_dir) / "qa-session.json"
    if not path.is_file():
        return None
    try:
        return json.loads(read_text(path))
    except Exception:
        return None


def session_stats(session):
    if not session:
        return {"run_mode": "", "承認済みゲート": 0, "ループバック": 0, "改善メモ": 0}
    gates = [g for g in session.get("gates", []) if g.get("status") == "approved"]
    loops = [d for d in session.get("decisions", [])
             if any(w in (d.get("decision") or "") for w in ("戻", "ループバック", "やり直"))]
    return {
        "run_mode": session.get("run_mode", ""),
        "承認済みゲート": len(gates),
        "ループバック": len(loops),
        "改善メモ": len(session.get("improvement_notes", [])),
    }


def guard_answer_key_leak(session, key_dir):
    """答えキーがランの入力に混入していたら採点を無効にする。

    答えを見せて解かせた結果は、検出率としての意味を持たない。
    """
    if not session:
        return []
    bad = []
    for item in session.get("inputs", []):
        joined = (item.get("path") or "") + " " + (item.get("converted_path") or "")
        norm = joined.replace("\\", "/").lower()
        if "answer-key" in norm or "answer_key" in norm:
            bad.append(item.get("path"))
    return bad


def git_rev():
    try:
        proc = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
        if proc.returncode == 0:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

def fmt_ratio(d):
    return "{}/{} ({}%)".format(d["hit"], d["total"], d["率"])


def fmt_metric(v):
    """metrics.py は分母0のとき null を返す(算出不能)。0% と区別して出す。"""
    return "—" if v is None else "{}%".format(v)


def cell(v):
    return "" if v is None else v


def render(payload):
    s = payload["採点"]
    out = []
    a = out.append
    a("# 評価ラン採点: {}".format(payload["run_id"]))
    a("")
    a("> ⚠️ これは**答えキーとの照合結果**であり、成果物の良し悪しの評価ではない。")
    a("> 検出率は「仕込んだ項目を拾えたか」だけを表す。答えキーに無い指摘の妥当性は")
    a("> 機械判定していない — §2 の未照合エントリを人が見ること(eval/README.md §5)。")
    a("")
    a("| 項目 | 値 |")
    a("|---|---|")
    a("| フィクスチャ | {} |".format(payload["fixture"]))
    a("| セッション | {} |".format(payload["session_dir"]))
    a("| 実行モード | {} |".format(payload["session"]["run_mode"] or "(不明)"))
    a("| モデル | {} |".format(payload["model"] or "(未記録)"))
    a("| スキルセット版 | {} |".format(payload["skillset_rev"]))
    a("| 採点日時 | {} |".format(payload["date"]))
    a("")
    a("## 1. 検出率(答えキー照合)")
    a("")
    a("| カテゴリ | 検出/期待 | 未検出 |")
    a("|---|---|---|")
    for cat in CATEGORY_ORDER:
        d = s["カテゴリ別"].get(cat)
        if not d:
            continue
        miss = [r["id"] for r in payload["明細"]
                if r["category"] == cat and not r["detected"]]
        a("| {} | {} | {} |".format(
            CATEGORY_SPEC[cat]["label"], fmt_ratio(d), ", ".join(miss) if miss else "—"))
    a("| **全体** | **{}** | |".format(fmt_ratio(s["全体"])))
    a("")
    a("難易度別(A=文書間の明示的な矛盾 / B=記述の欠落 / C=資料に手掛かりが薄い暗黙知):")
    a("")
    a("| 難易度 | 検出/期待 |")
    a("|---|---|")
    for d in DIFFICULTIES:
        if d in s["難易度別"]:
            a("| {} | {} |".format(d, fmt_ratio(s["難易度別"][d])))
    a("")
    miss_rows = [r for r in payload["明細"] if not r["detected"]]
    if miss_rows:
        a("### 未検出の内訳")
        a("")
        a("| ID | 難易度 | 内容 | 仕込みの意図 |")
        a("|---|---|---|---|")
        for r in miss_rows:
            a("| {} | {} | {} | {} |".format(
                r["id"], r["difficulty"], r["title"], r["rationale"]))
        a("")
    a("## 2. 未照合エントリ(人が見る)")
    a("")
    a("答えキーのどれにも当たらなかった指摘・項目。**誤指摘とは限らない** —")
    a("キーに無い正しい発見であれば、答えキー側に追加する(eval/README.md §6)。")
    a("")
    if not payload["未照合"]:
        a("該当なし")
    else:
        a("| カテゴリ | ID | ファイル | 抜粋 |")
        a("|---|---|---|---|")
        for u in payload["未照合"]:
            a("| {} | {} | {} | {} |".format(
                CATEGORY_SPEC[u["category"]]["label"], u["entry_id"], u["file"],
                u["excerpt"].replace("|", "\\|")))
    a("")
    a("## 3. 成果物指標(metrics.py)")
    a("")
    m = payload["metrics"]
    if not m:
        a("(取得できず。metrics.py が実行できない環境か、成果物が読めない)")
    else:
        ev = m.get("根拠の規律", {})
        tr = m.get("トレース", {})
        a("| 指標 | 値 | 目標 |")
        a("|---|---|---|")
        a("| 根拠参照率 | {} | 高いほどよい |".format(fmt_metric(ev.get("根拠参照率"))))
        a("| 根拠なし事実主張率 | {} | **0%** |".format(fmt_metric(ev.get("根拠なし事実主張率"))))
        a("| トレース率 | {} | 高いほどよい |".format(fmt_metric(tr.get("トレース率"))))
        viol = ev.get("違反行") or []
        if viol:
            a("")
            a("**根拠なし事実主張(規約違反)**: {}件 — 内容は metrics.py の出力を見ること".format(len(viol)))
    a("")
    a("## 4. セッションの手数")
    a("")
    ss = payload["session"]
    a("| 項目 | 値 |")
    a("|---|---|")
    a("| 承認済みゲート数 | {} |".format(ss["承認済みゲート"]))
    a("| ループバック回数 | {} |".format(ss["ループバック"]))
    a("| 改善メモ件数 | {} |".format(ss["改善メモ"]))
    a("")
    a("## 5. 次にやること")
    a("")
    a("1. §1 の未検出を、スキルの手順・参照ナレッジで説明できるか診断する(なぜ拾えなかったか)")
    a("2. §2 の未照合エントリを人が見て、誤指摘 / キー漏れ を仕分ける")
    a("3. 診断結果を 90-improvement.md の改善提案に落とし、maintenance-log.md のトリアージへ回す")
    return "\n".join(out)


def append_runs(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    s = payload["採点"]
    m = payload["metrics"] or {}
    ev = m.get("根拠の規律", {})
    tr = m.get("トレース", {})

    def cat(c):
        d = s["カテゴリ別"].get(c)
        return d["率"] if d else ""

    def diff(d):
        x = s["難易度別"].get(d)
        return x["率"] if x else ""

    row = {
        "run_id": payload["run_id"],
        "date": payload["date"],
        "fixture": payload["fixture"],
        "session_dir": payload["session_dir"],
        "run_mode": payload["session"]["run_mode"],
        "model": payload["model"],
        "skillset_rev": payload["skillset_rev"],
        "recall_overall": s["全体"]["率"],
        "recall_ambiguity": cat("ambiguity"),
        "recall_transition": cat("transition"),
        "recall_handoff": cat("handoff"),
        "recall_scenario": cat("scenario"),
        "recall_regression": cat("regression"),
        "recall_a": diff("A"), "recall_b": diff("B"), "recall_c": diff("C"),
        "unmatched": len(payload["未照合"]),
        "groundless_rate": cell(ev.get("根拠なし事実主張率")),
        "trace_rate": cell(tr.get("トレース率")),
        "gates_approved": payload["session"]["承認済みゲート"],
        "loopbacks": payload["session"]["ループバック"],
        "hits": ";".join("{}={}/{}".format(c[:3], s["カテゴリ別"][c]["hit"], s["カテゴリ別"][c]["total"])
                         for c in CATEGORY_ORDER if c in s["カテゴリ別"]),
        "note": payload.get("note", ""),
    }
    exists = path.is_file()
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RUNS_COLUMNS)
        if not exists:
            w.writeheader()
        w.writerow(row)
    return row


# ---------------------------------------------------------------------------
# サブコマンド
# ---------------------------------------------------------------------------

def cmd_score(args):
    session_dir = Path(args.session_dir)
    if not session_dir.is_dir():
        die("セッションディレクトリがありません: {}".format(session_dir))

    key_items = load_key(args.key)
    session = read_session(session_dir)

    leaked = guard_answer_key_leak(session, args.key)
    if leaked and not args.allow_key_in_inputs:
        err("採点無効: 答えキーがランの入力に含まれています: {}".format(", ".join(map(str, leaked))))
        err("答えを見せて解かせた結果は検出率としての意味を持ちません(eval/README.md §4)。")
        return 3

    results, unmatched = score_session(session_dir, key_items)
    payload = {
        "run_id": args.run_id or datetime.now().strftime("%Y%m%d-%H%M"),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fixture": args.fixture or Path(args.key).resolve().name,
        "session_dir": str(session_dir).replace("\\", "/"),
        "model": args.model,
        "skillset_rev": args.rev or git_rev(),
        "note": args.note,
        "採点": summarize(results),
        "明細": results,
        "未照合": unmatched,
        "metrics": None if args.no_metrics else run_metrics(session_dir),
        "session": session_stats(session),
    }

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(payload))

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        err("採点結果を書き出しました: {}".format(out))
    if args.append:
        append_runs(args.append, payload)
        err("ラン台帳に追記しました: {}".format(args.append))
    return 0


def _read_runs(path):
    path = Path(path)
    if not path.is_file():
        die("ラン台帳がありません: {}".format(path))
    return list(csv.DictReader(io.StringIO(read_text(path))))


def cmd_compare(args):
    rows = _read_runs(args.runs)
    if len(rows) < 2:
        die("比較には2ラン以上必要です(現在 {} 件)".format(len(rows)))
    by_id = {r["run_id"]: r for r in rows}
    target = by_id.get(args.target) if args.target else rows[-1]
    base = by_id.get(args.baseline) if args.baseline else rows[-2]
    if target is None or base is None:
        die("指定の run_id が台帳にありません")

    metrics = [
        ("全体検出率", "recall_overall"), ("曖昧性", "recall_ambiguity"),
        ("状態遷移", "recall_transition"), ("引き継ぎ", "recall_handoff"),
        ("シナリオ", "recall_scenario"), ("回帰観点", "recall_regression"),
        ("難易度A", "recall_a"), ("難易度B", "recall_b"), ("難易度C", "recall_c"),
        ("未照合エントリ数", "unmatched"), ("根拠なし事実主張率", "groundless_rate"),
        ("トレース率", "trace_rate"), ("ループバック", "loopbacks"),
    ]
    print("# ラン比較: {} → {}".format(base["run_id"], target["run_id"]))
    print()
    print("| 項目 | {} | {} | 差分 |".format(base["run_id"], target["run_id"]))
    print("|---|---|---|---|")
    for label, col in metrics:
        b, t = base.get(col, ""), target.get(col, "")
        try:
            d = float(t) - float(b)
            delta = "{:+.1f}".format(d)
        except (TypeError, ValueError):
            delta = "—"
        print("| {} | {} | {} | {} |".format(label, b or "—", t or "—", delta))
    print()
    print("条件: モデル {} → {} / スキルセット版 {} → {}".format(
        base.get("model") or "?", target.get("model") or "?",
        base.get("skillset_rev") or "?", target.get("skillset_rev") or "?"))
    print()
    print("> ⚠️ 生成はばらつく。**1回の差分で採否を決めない**(eval/README.md §7)。")
    print("> 条件(モデル・フィクスチャ・モード)が違うランの比較は無効。")
    return 0


# ---------------------------------------------------------------------------
# 自己検査
# ---------------------------------------------------------------------------

SELFTEST_KEY = """id,category,title,target,match,difficulty,rationale
AMB-T01,ambiguity,拾えるはずの矛盾,,10万|100000;境界|以上,A,検出できること
AMB-T02,ambiguity,拾えないはずの欠落,,分納|一部検収;残数,B,検出されないこと
SCN-T01,scenario,同時実行シナリオ,,edi|送信;取消;競合|同時,B,見出しの前置が効くこと
"""

SELFTEST_REVIEW = """# 仕様レビュー: 自己検査

## 2. 検出一覧

| ID | 分類 | 内容 | 影響 |
|---|---|---|---|
| AMB-001 | 矛盾 | 二段階承認の境界が10万円以上と10万円超で食い違う | 承認経路が決まらない |
| AMB-002 | 未定義 | 通知の再送条件が書かれていない | 運用が決まらない |
"""

SELFTEST_SCENARIO = """# 業務シナリオ: 自己検査

## 3. シナリオ詳細

### SC-06 EDI送信中の取消要求

- 前提: 発注済みで未送信
- 手順: バッチ実行と競合させる
"""


def cmd_selftest(args):
    """採点ロジックの自己検査。

    **採点が誤って高い点を返すようになると、改善ループ全体が黙って無効になる**。
    仕込んだものを拾えること・拾えないものを拾ったことにしないことの両方を見る。
    """
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        key_dir = tmp / "key"
        key_dir.mkdir()
        (key_dir / "k.csv").write_text(SELFTEST_KEY, encoding="utf-8")
        sess = tmp / "session"
        sess.mkdir()
        (sess / "40-spec-review-requirements.md").write_text(SELFTEST_REVIEW, encoding="utf-8")
        (sess / "11-scenario-design.md").write_text(SELFTEST_SCENARIO, encoding="utf-8")

        items = load_key(key_dir)
        results, unmatched = score_session(sess, items)
        got = {r["id"]: r["detected"] for r in results}

        expected = {"AMB-T01": True, "AMB-T02": False, "SCN-T01": True}
        for k, want in expected.items():
            if got.get(k) is not want:
                failures.append("{}: 期待 {} / 実際 {}".format(k, want, got.get(k)))

        # AMB-002 はキーに無い指摘。未照合エントリとして出ていること
        if not any(u["entry_id"] == "AMB-002" for u in unmatched):
            failures.append("未照合エントリに AMB-002 が出ていない(誤指摘の見落とし検知が効かない)")
        # 照合済みの AMB-001 が未照合に混ざっていないこと
        if any(u["entry_id"] == "AMB-001" for u in unmatched):
            failures.append("照合済みの AMB-001 が未照合に混ざっている")

        # 正規化の確認(全角・カンマ・大文字小文字)
        if normalize("１０万，０００ EDI") != "10万000edi":
            failures.append("正規化が期待どおりでない: {}".format(normalize("１０万，０００ EDI")))

        # 答えキー混入ガード
        leaked = guard_answer_key_leak(
            {"inputs": [{"path": "eval/answer-key/prq/ambiguities.csv"}]}, key_dir)
        if not leaked:
            failures.append("答えキー混入ガードが発火しない")
        if guard_answer_key_leak({"inputs": [{"path": "eval/fixtures/prq/requirements.md"}]}, key_dir):
            failures.append("正常な入力を混入と誤判定した")

    if args.key:
        # 実際の答えキーが壊れていないことも見る(列・重複・条件の衝突)
        items = load_key(args.key)
        seen = {}
        for it in items:
            if it["id"] in seen:
                failures.append("答えキーのIDが重複しています: {}".format(it["id"]))
            seen[it["id"]] = it
            if it["difficulty"] not in DIFFICULTIES:
                failures.append("{}: 難易度が A/B/C ではありません: {}".format(
                    it["id"], it["difficulty"]))
        by_sig = {}
        for it in items:
            sig = (it["category"], tuple(tuple(g) for g in it["groups"]))
            if sig in by_sig:
                failures.append("{} と {} の照合条件が同一です(区別できません)".format(
                    by_sig[sig], it["id"]))
            by_sig[sig] = it["id"]
        if not failures:
            print("OK: 答えキー {} 件を読めました({})".format(len(items), args.key))

    if failures:
        for f in failures:
            print("NG: {}".format(f))
        return 1
    print("OK: 採点ロジックの自己検査に合格しました(検出 / 非検出 / 未照合 / 正規化 / 混入ガード)")
    return 0


# ---------------------------------------------------------------------------

def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="評価ランを答えキーと突き合わせて採点する(eval/README.md)。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="exit code: 0=採点完了 / 2=使用法エラー / 3=採点無効(答えキーの混入)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("score", help="セッションを答えキーと突き合わせる")
    p.add_argument("session_dir", help="評価ランのセッションディレクトリ")
    p.add_argument("--key", required=True, help="答えキーのディレクトリ(例: eval/answer-key/prq)")
    p.add_argument("--fixture", default="", help="フィクスチャ名(既定: 答えキーのディレクトリ名)")
    p.add_argument("--run-id", dest="run_id", default="", help="ラン識別子(既定: 日時)")
    p.add_argument("--model", default="", help="使用モデル(記録用。比較の前提になる)")
    p.add_argument("--rev", default="", help="スキルセットのリビジョン(既定: git rev-parse)")
    p.add_argument("--note", default="", help="このランの条件・気づき(台帳に残す)")
    p.add_argument("--append", default="", help="ラン台帳CSVに1行追記する(例: eval/runs/runs.csv)")
    p.add_argument("--out", default="", help="採点結果JSONの書き出し先")
    p.add_argument("--json", action="store_true", dest="as_json", help="JSONで出力する")
    p.add_argument("--no-metrics", action="store_true", help="metrics.py を呼ばない")
    p.add_argument("--allow-key-in-inputs", action="store_true",
                   help="答えキー混入ガードを無効にする(採点の意味が失われる。原則使わない)")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("compare", help="ラン台帳の2ランを比較する")
    p.add_argument("runs", help="ラン台帳CSV(例: eval/runs/runs.csv)")
    p.add_argument("--baseline", default="", help="比較元の run_id(既定: 最後から2件目)")
    p.add_argument("--target", default="", help="比較先の run_id(既定: 最新)")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("selftest", help="採点ロジック自身の自己検査")
    p.add_argument("--key", default="", help="実在の答えキーも検査する(列・ID重複・条件の衝突)")
    p.set_defaults(func=cmd_selftest)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
