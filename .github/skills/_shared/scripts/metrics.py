#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA成果物の指標測定(機械算出)。

conventions.md §11 の指標を、セッションディレクトリの成果物から機械的に算出する。
qa-improvement が振り返りレポート(90-improvement.md)のセクション2に使う。

**測定は評価ではない。** 件数の多寡ではなく「根拠の規律」と「トレースの連続性」を
測ることが目的であり、数値の意味づけ・原因の特定はAIと人間が行う(conventions.md §9)。

使用例:
    python metrics.py qa-output/2026-08-invoice-approval
    python metrics.py qa-output/2026-08-invoice-approval --json

算出する指標:
    1. 根拠参照率           出典列を持つ表の行のうち、出典が埋まっている割合
    2. 根拠なし事実主張率   derivation:explicit なのに出典が空の割合(目標 0%)
    3. トレース率           traces_to の参照のうち、上流に実在するIDを指す割合
    4. モデルカバレッジ     意図モデルの ACT/STT/TRN/HO のうちシナリオが触れた割合
    5. シナリオ種別カバレッジ 正常・代替・例外・回復・取消の各種別の有無
    6. 業務オラクル保有率   期待結果が画面表示以外の業務結果を検証している割合(推定)

指標6はキーワード推定であり誤差がある(出力に「推定」と明記される)。

表の解析は trace_check.py の実装を共有する(同一ディレクトリに配置されている前提)。

exit code: 0=算出成功 / 2=使用法エラー(ディレクトリ不存在等)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from trace_check import (  # noqa: E402
    _EMPTY_VALUES,
    _MODEL_PREFIXES,
    cell_at,
    clean_cell,
    extract_defined_ids,
    find_column,
    parse_tables,
    split_ids,
)

# 出典を表す列名(部分一致)
SOURCE_COLUMNS = ("出典", "sources", "根拠")

# シナリオ種別(skill-map.md / business-scenario-patterns.md)
SCENARIO_KINDS = ("正常", "代替", "例外", "回復", "取消")

# 業務オラクル(画面表示以外の確認手段)を示す語。指標6の推定に使う
ORACLE_KEYWORDS = (
    "テーブル", "db", "レコード", "api", "レスポンス", "ログ", "監査",
    "通知", "メール", "帳票", "csv", "エクスポート", "バッチ", "連携",
    "履歴", "集計",
)
# 画面のみの確認を示す語(オラクル語が無いときの分母確認用)
SCREEN_KEYWORDS = ("画面", "表示", "一覧", "ボタン", "メッセージ")


def pct(num, den):
    """割合を % で返す(分母0なら None)。"""
    if not den:
        return None
    return round(100.0 * num / den, 1)


def fmt_pct(value):
    return "—" if value is None else f"{value}%"


def iter_artifacts(session_dir):
    """セッションディレクトリの成果物Markdownを (種別キー, path, text) で列挙する。"""
    for path in sorted(session_dir.glob("*.md")):
        stem = path.stem
        # NN-<名前> から <名前> を取り出す(接尾辞はそのまま残す)
        key = stem.split("-", 1)[1] if "-" in stem and stem[:2].isdigit() else stem
        yield key, path, path.read_text(encoding="utf-8")


def measure_evidence(artifacts):
    """指標1・2: 根拠参照率と根拠なし事実主張率。"""
    rows_total = rows_with_source = 0
    explicit_total = explicit_without_source = 0
    offenders = []

    for key, path, text in artifacts:
        for header, rows in parse_tables(text):
            src_col = None
            for name in SOURCE_COLUMNS:
                src_col = find_column(header, name)
                if src_col is not None:
                    break
            if src_col is None:
                continue
            der_col = find_column(header, "derivation")
            id_col = find_column(header, "ID", exclude="観点ID")
            for row in rows:
                if all(c in _EMPTY_VALUES for c in row):
                    continue
                rows_total += 1
                has_source = cell_at(row, src_col) not in _EMPTY_VALUES
                if has_source:
                    rows_with_source += 1
                if der_col is None:
                    continue
                if "explicit" not in clean_cell(cell_at(row, der_col)).lower():
                    continue
                explicit_total += 1
                if not has_source:
                    explicit_without_source += 1
                    offenders.append({
                        "file": path.name,
                        "id": cell_at(row, id_col) if id_col is not None else "",
                        "detail": (
                            f"{path.name}: "
                            f"{cell_at(row, id_col) if id_col is not None else '(ID不明)'}"
                            "(derivation: explicit だが出典が空)"
                        ),
                    })
    return {
        "根拠参照率": pct(rows_with_source, rows_total),
        "根拠参照_分子分母": [rows_with_source, rows_total],
        "根拠なし事実主張率": pct(explicit_without_source, explicit_total),
        "根拠なし事実主張_分子分母": [explicit_without_source, explicit_total],
        "違反行": offenders,
    }


def measure_trace(artifacts):
    """指標3: トレース率(traces_to が実在IDを指す割合)。"""
    defined = set()
    prefixes = _MODEL_PREFIXES + ("SC", "VP", "TC")
    for _key, _path, text in artifacts:
        defined |= extract_defined_ids(text, prefixes)

    refs_total = refs_resolved = 0
    dangling = []
    for _key, path, text in artifacts:
        for header, rows in parse_tables(text):
            ref_col = find_column(header, "traces_to")
            if ref_col is None:
                continue
            for row in rows:
                for ref in split_ids(cell_at(row, ref_col)):
                    if ref.split("-")[0] not in prefixes:
                        continue
                    refs_total += 1
                    if ref in defined:
                        refs_resolved += 1
                    else:
                        dangling.append({"file": path.name, "ref": ref})
    return {
        "トレース率": pct(refs_resolved, refs_total),
        "トレース_分子分母": [refs_resolved, refs_total],
        "未解決参照": dangling,
    }


def measure_model_coverage(artifacts):
    """指標4: 意図モデルの要素をシナリオがどれだけ触れたか。"""
    model_text = "".join(t for k, _p, t in artifacts if k.startswith("intent-recovery"))
    scenario_text = "".join(t for k, _p, t in artifacts if k.startswith("scenario-design"))
    if not model_text or not scenario_text:
        return {"利用可能": False, "理由": "意図モデルまたはシナリオが無い"}

    coverage = {"利用可能": True, "軸": {}}
    for label, prefix in (("Actor", "ACT"), ("状態", "STT"),
                          ("遷移", "TRN"), ("引き継ぎ", "HO")):
        defined = extract_defined_ids(model_text, (prefix,))
        touched = {i for i in defined if i in scenario_text}
        coverage["軸"][label] = {
            "全体": len(defined),
            "到達": len(touched),
            "率": pct(len(touched), len(defined)),
            "未到達": sorted(defined - touched),
        }
    return coverage


def measure_scenario_kinds(artifacts):
    """指標5: シナリオ種別カバレッジ。"""
    text = "".join(t for k, _p, t in artifacts if k.startswith("scenario-design"))
    if not text:
        return {"利用可能": False, "理由": "シナリオが無い"}
    counts = {kind: 0 for kind in SCENARIO_KINDS}
    for header, rows in parse_tables(text):
        kind_col = find_column(header, "種別")
        if kind_col is None:
            continue
        for row in rows:
            value = cell_at(row, kind_col)
            for kind in SCENARIO_KINDS:
                if kind in value:
                    counts[kind] += 1
    return {
        "利用可能": True,
        "件数": counts,
        "欠落種別": [k for k, n in counts.items() if n == 0],
    }


def measure_oracles(artifacts):
    """指標6: 業務オラクル保有率(キーワードによる推定)。"""
    text_rows = []
    for key, _path, text in artifacts:
        if not key.startswith("test-case"):
            continue
        for header, rows in parse_tables(text):
            exp_col = find_column(header, "期待結果")
            if exp_col is None:
                continue
            chk_col = find_column(header, "確認手段")
            for row in rows:
                if all(c in _EMPTY_VALUES for c in row):
                    continue
                blob = cell_at(row, exp_col)
                if chk_col is not None:
                    blob += " " + cell_at(row, chk_col)
                text_rows.append(blob.lower())
    if not text_rows:
        return {"利用可能": False, "理由": "テストケースが無い(または期待結果列が無い)"}

    with_oracle = sum(
        1 for blob in text_rows if any(kw in blob for kw in ORACLE_KEYWORDS)
    )
    return {
        "利用可能": True,
        "率": pct(with_oracle, len(text_rows)),
        "分子分母": [with_oracle, len(text_rows)],
        "注記": "キーワード推定のため誤差がある。0件でも正当な場合がある(単純な表示確認)",
    }


def render(session_dir, files, ev, tr, mc, sk, orc):
    out = []
    a = out.append
    a("# 成果物指標(機械算出)")
    a("")
    a("> ⚠️ これは metrics.py による機械算出である。**数値の意味づけと原因の特定は")
    a("> AI/人間が行う**(conventions.md §11: 指標を目標にしてはならない)。")
    a("")
    a(f"対象ディレクトリ: {session_dir}")
    a(f"対象成果物: {', '.join(files) if files else '(なし)'}")
    a("")
    a("## 根拠の規律")
    a("")
    a("| 指標 | 値 | 分子/分母 | 目標 |")
    a("|---|---|---|---|")
    a("| 根拠参照率 | {} | {}/{} | 高いほどよい |".format(
        fmt_pct(ev["根拠参照率"]), *ev["根拠参照_分子分母"]))
    a("| 根拠なし事実主張率 | {} | {}/{} | **0%** |".format(
        fmt_pct(ev["根拠なし事実主張率"]), *ev["根拠なし事実主張_分子分母"]))
    a("| トレース率 | {} | {}/{} | 高いほどよい |".format(
        fmt_pct(tr["トレース率"]), *tr["トレース_分子分母"]))
    a("")
    if ev["違反行"]:
        a("### 根拠なし事実主張(規約違反 — conventions.md §5-3)")
        a("")
        for o in ev["違反行"]:
            a(f"- {o['detail']}")
        a("")
    if tr["未解決参照"]:
        a("### 未解決の traces_to 参照")
        a("")
        for d in tr["未解決参照"]:
            a(f"- {d['file']}: {d['ref']}(定義が見つからない)")
        a("")

    a("## モデルカバレッジ")
    a("")
    if not mc.get("利用可能"):
        a(f"(算出不能: {mc.get('理由')})")
    else:
        a("| 軸 | 全体 | 到達 | 率 | 未到達 |")
        a("|---|---|---|---|---|")
        for label, d in mc["軸"].items():
            missing = ", ".join(d["未到達"]) if d["未到達"] else "—"
            a(f"| {label} | {d['全体']} | {d['到達']} | {fmt_pct(d['率'])} | {missing} |")
    a("")

    a("## シナリオ種別カバレッジ")
    a("")
    if not sk.get("利用可能"):
        a(f"(算出不能: {sk.get('理由')})")
    else:
        a("| 種別 | 本数 |")
        a("|---|---|")
        for kind, n in sk["件数"].items():
            a(f"| {kind} | {n} |")
        if sk["欠落種別"]:
            a("")
            a("**欠落種別**: {} — 対象外なら理由が成果物に書かれているか確認する".format(
                ", ".join(sk["欠落種別"])))
    a("")

    a("## 業務オラクル保有率(推定)")
    a("")
    if not orc.get("利用可能"):
        a(f"(算出不能: {orc.get('理由')})")
    else:
        a("- 率: {} ({}/{} ケース)".format(fmt_pct(orc["率"]), *orc["分子分母"]))
        a(f"- 注記: {orc['注記']}")
    a("")

    a("## 機械測定できない指標(qa-improvement のヒアリングで記録する)")
    a("")
    a("- 採用率(成果物のうち実際に使われた割合)")
    a("- 修正量(人が手を入れた量)")
    a("- 再実行一致率・flaky率(自動化フェーズが必要)")
    return "\n".join(out)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="QA成果物の指標を機械算出する(conventions.md §11)。",
    )
    parser.add_argument("session_dir",
                        help="セッションディレクトリ(qa-output/<セッション名>)")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="機械可読JSONで出力する")
    args = parser.parse_args()

    session_dir = Path(args.session_dir)
    if not session_dir.is_dir():
        print(f"エラー: ディレクトリが存在しません: {session_dir}", file=sys.stderr)
        return 2

    artifacts = list(iter_artifacts(session_dir))
    files = [p.name for _k, p, _t in artifacts]

    ev = measure_evidence(artifacts)
    tr = measure_trace(artifacts)
    mc = measure_model_coverage(artifacts)
    sk = measure_scenario_kinds(artifacts)
    orc = measure_oracles(artifacts)

    if args.as_json:
        print(json.dumps({
            "session_dir": str(session_dir),
            "files": files,
            "根拠の規律": ev,
            "トレース": tr,
            "モデルカバレッジ": mc,
            "シナリオ種別": sk,
            "業務オラクル": orc,
            "note": "機械算出の結果であり、意味づけはAI/人間が行う",
        }, ensure_ascii=False, indent=2))
    else:
        print(render(session_dir, files, ev, tr, mc, sk, orc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
