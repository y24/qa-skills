#!/usr/bin/env python3
"""成果物間トレーサビリティ検証スクリプト(機械検出)。

QAセッションディレクトリ(qa-output/<セッション名>/)内の成果物Markdownを
ファイル名パターンで自動検出し、成果物間のID突合を機械的に行う。
LLMによる目視突合の代替であり、検出された孤児・欠落を「どう埋めるか」の
判断はAI/人間が行う(このスクリプトは判断しない)。

使用例:
    python trace_check.py qa-output/2026-07-login-feature
    python trace_check.py qa-output/2026-07-login-feature --json

対象ファイル(存在しないものは関連チェックをスキップ):
    *-test-viewpoint.md     テスト観点一覧(qa-test-viewpoint)
    *-test-case.md          テストケース(qa-test-case-design)
    *-criteria-analysis.md  品質基準一覧(qa-criteria-analysis)
    *-spec-review-*.md      仕様レビュー(qa-spec-review、複数可)
    *-test-design-review.md テスト設計レビュー(qa-test-design-review。AMB定義の収集のみ)

チェック項目:
    1. 観点ID参照の整合   : テストケースの「観点ID」が観点一覧の「ID」に実在するか
    2. 未展開観点の検出   : どのケースからも参照されない観点(情報提供のみ)
    3. 導出元の欠落       : 観点一覧の「導出元」列が空・「-」のみの行
    4. 未確認の品質基準   : QC-xxx-NN のうち観点一覧に出現しないもの
    5. AMB参照の実在確認  : AMB-NNN 参照が仕様レビューまたはテスト設計レビューの
                            いずれかに定義されているか(テスト設計レビューは仕様由来の
                            指摘を AMB 書式で切り出すことがある)
    6. ID重複             : 観点一覧・テストケース各表内のID重複

exit code:
    0 = 検出なし
    1 = 検出あり(チェック1,3,4,5,6のいずれか。チェック2は影響しない)
    2 = 使用法エラー(ディレクトリ不存在等)
"""

import argparse
import json
import re
import sys
from pathlib import Path

# 「値なし」とみなすセル値(空白除去・マーカー除去後)
_EMPTY_VALUES = {"", "-", "－", "ー", "―", "—", "‐", "なし"}

_AMB_RE = re.compile(r"AMB-\d+")
_QC_RE = re.compile(r"QC-\w+-\d+")


def clean_cell(cell):
    """セル値から太字マーカー・backtick・前後空白を除去する。"""
    s = cell.strip()
    s = s.replace("**", "").replace("`", "")
    return s.strip()


def is_separator_row(cells):
    """|---|:---:| 等の区切り行か判定する。"""
    stripped = [c.strip() for c in cells]
    non_empty = [c for c in stripped if c]
    if not non_empty:
        return False
    return all(re.fullmatch(r":?-{2,}:?|:-+:?|-+", c) for c in non_empty)


def split_row(line):
    """Markdown表の1行をセルのリストに分割する(先頭・末尾の | を除去)。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return s.split("|")


def parse_tables(text):
    """テキスト中のMarkdown表をすべて抽出する。

    Returns: list of (header_cells, data_rows)
        header_cells: clean_cell 済みのヘッダーセル一覧
        data_rows: 各行のセル一覧(clean_cell 済み)
    """
    tables = []
    block = []
    for line in text.splitlines() + [""]:  # 番兵で最終表をflush
        if line.strip().startswith("|"):
            block.append(line)
            continue
        if len(block) >= 2:
            header = [clean_cell(c) for c in split_row(block[0])]
            rows = []
            for raw in block[1:]:
                cells = split_row(raw)
                if is_separator_row(cells):
                    continue
                rows.append([clean_cell(c) for c in cells])
            tables.append((header, rows))
        block = []
    return tables


def find_column(header, keyword, exclude=None):
    """ヘッダーから keyword を部分一致で含む列のインデックスを返す。

    exclude を指定した場合、exclude を含む列は候補から除外する
    (例:「ID」列を探すとき「観点ID」列を除外)。
    完全一致を優先する。
    """
    candidates = []
    for i, cell in enumerate(header):
        if exclude and exclude in cell:
            continue
        if keyword in cell:
            candidates.append(i)
    if not candidates:
        return None
    for i in candidates:
        if header[i] == keyword:
            return i
    return candidates[0]


def cell_at(row, idx):
    """行から idx 番目のセルを安全に取得する(列数不足なら空文字)。"""
    return row[idx] if idx < len(row) else ""


def split_ids(cell):
    """1セル内の複数ID(カンマ・読点・スラッシュ等区切り)を分解する。"""
    tokens = re.split(r"[,、/;・\s]+", cell)
    return [t for t in (clean_cell(t) for t in tokens) if t not in _EMPTY_VALUES]


def extract_viewpoint_rows(text):
    """観点一覧ファイルから (ID, 導出元) の行リストを抽出する。

    「ID」列と「導出元」列(部分一致)を両方持つ表のみ対象。
    """
    rows_out = []
    for header, rows in parse_tables(text):
        id_col = find_column(header, "ID", exclude="観点ID")
        src_col = find_column(header, "導出元")
        if id_col is None or src_col is None:
            continue
        for row in rows:
            vid = cell_at(row, id_col)
            src = cell_at(row, src_col)
            if vid in _EMPTY_VALUES:
                continue
            rows_out.append((vid, src))
    return rows_out


def extract_testcase_rows(text):
    """テストケースファイルから (ID, [観点ID, ...]) の行リストを抽出する。

    「観点ID」列を持つ表のみ対象。
    """
    rows_out = []
    for header, rows in parse_tables(text):
        vp_col = find_column(header, "観点ID")
        if vp_col is None:
            continue
        id_col = find_column(header, "ID", exclude="観点ID")
        for row in rows:
            cid = cell_at(row, id_col) if id_col is not None else ""
            if cid in _EMPTY_VALUES and not cell_at(row, vp_col):
                continue
            rows_out.append((cid, split_ids(cell_at(row, vp_col))))
    return rows_out


def find_duplicates(ids):
    """出現順を保ってID重複を検出する。Returns: [(id, 出現回数), ...]"""
    counts = {}
    for i in ids:
        counts[i] = counts.get(i, 0) + 1
    return [(i, n) for i, n in counts.items() if n > 1]


def read_text(path):
    return path.read_text(encoding="utf-8")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="QA成果物間のトレーサビリティを機械的に突合する。",
    )
    parser.add_argument("session_dir", help="セッションディレクトリ(qa-output/<セッション名>)")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="機械可読JSONで出力する")
    args = parser.parse_args()

    session_dir = Path(args.session_dir)
    if not session_dir.is_dir():
        print(f"エラー: ディレクトリが存在しません: {session_dir}", file=sys.stderr)
        return 2

    # --- ファイル自動検出 ---
    vp_files = sorted(session_dir.glob("*-test-viewpoint.md"))
    tc_files = sorted(session_dir.glob("*-test-case.md"))
    qc_files = sorted(session_dir.glob("*-criteria-analysis.md"))
    sr_files = sorted(session_dir.glob("*-spec-review-*.md"))
    tdr_files = sorted(session_dir.glob("*-test-design-review.md"))

    files_info = {
        "観点一覧": [f.name for f in vp_files],
        "テストケース": [f.name for f in tc_files],
        "品質基準": [f.name for f in qc_files],
        "仕様レビュー": [f.name for f in sr_files],
        "テスト設計レビュー": [f.name for f in tdr_files],
    }

    # --- 読み込みとID抽出 ---
    vp_rows = []          # (file, id, 導出元)
    vp_texts = {}         # file -> text
    for f in vp_files:
        text = read_text(f)
        vp_texts[f.name] = text
        for vid, src in extract_viewpoint_rows(text):
            vp_rows.append((f.name, vid, src))
    vp_ids = {vid for _, vid, _ in vp_rows}

    tc_rows = []          # (file, id, [観点ID])
    tc_texts = {}
    for f in tc_files:
        text = read_text(f)
        tc_texts[f.name] = text
        for cid, refs in extract_testcase_rows(text):
            tc_rows.append((f.name, cid, refs))

    qc_texts = {f.name: read_text(f) for f in qc_files}
    sr_texts = {f.name: read_text(f) for f in sr_files}
    tdr_texts = {f.name: read_text(f) for f in tdr_files}

    checks = []

    def add_check(num, name, status, findings=None, note=None):
        checks.append({
            "no": num,
            "name": name,
            "status": status,   # ok / finding / info / skipped
            "findings": findings or [],
            "note": note,
        })

    # --- チェック1: 観点ID参照の整合 ---
    if not tc_files:
        add_check(1, "観点ID参照の整合", "skipped", note="テストケースファイルなし")
    elif not vp_files:
        add_check(1, "観点ID参照の整合", "skipped", note="観点一覧ファイルなし(参照先を突合できない)")
    else:
        findings = []
        for fname, cid, refs in tc_rows:
            for ref in refs:
                if ref not in vp_ids:
                    findings.append({
                        "file": fname, "case_id": cid, "viewpoint_id": ref,
                        "detail": f"{fname}: {cid or '(ID不明)'} → {ref}(観点一覧に存在しない)",
                    })
        add_check(1, "観点ID参照の整合", "finding" if findings else "ok", findings)

    # --- チェック2: 未展開観点(情報提供のみ)---
    if not tc_files or not vp_files:
        add_check(2, "未展開観点の検出(情報提供)", "skipped",
                  note="観点一覧・テストケースの両方が必要")
    else:
        referenced = {r for _, _, refs in tc_rows for r in refs}
        findings = []
        for fname, vid, _ in vp_rows:
            if vid not in referenced:
                findings.append({
                    "file": fname, "viewpoint_id": vid,
                    "detail": f"{fname}: {vid}(どのテストケースからも参照されていない)",
                })
        add_check(2, "未展開観点の検出(情報提供)", "info" if findings else "ok", findings,
                  note="未展開は正当な場合がある(観点一覧セクション4等を確認)")

    # --- チェック3: 導出元の欠落 ---
    if not vp_files:
        add_check(3, "導出元の欠落", "skipped", note="観点一覧ファイルなし")
    else:
        findings = []
        for fname, vid, src in vp_rows:
            if clean_cell(src) in _EMPTY_VALUES:
                findings.append({
                    "file": fname, "viewpoint_id": vid,
                    "detail": f"{fname}: {vid}(導出元が空または「-」)",
                })
        add_check(3, "導出元の欠落", "finding" if findings else "ok", findings)

    # --- チェック4: 未確認の品質基準 ---
    if not qc_files:
        add_check(4, "未確認の品質基準", "skipped", note="品質基準ファイルなし")
    elif not vp_files:
        add_check(4, "未確認の品質基準", "skipped", note="観点一覧ファイルなし(参照側を突合できない)")
    else:
        vp_all_text = "\n".join(vp_texts.values())
        vp_qc_refs = set(_QC_RE.findall(vp_all_text))
        findings = []
        seen = set()
        for fname, text in qc_texts.items():
            for qc_id in _QC_RE.findall(text):
                if qc_id in vp_qc_refs or qc_id in seen:
                    continue
                seen.add(qc_id)
                findings.append({
                    "file": fname, "qc_id": qc_id,
                    "detail": f"{fname}: {qc_id}(観点一覧に出現しない — テストで確認されない基準の候補)",
                })
        add_check(4, "未確認の品質基準", "finding" if findings else "ok", findings)

    # --- チェック5: AMB参照の実在確認 ---
    if not vp_files and not tc_files:
        add_check(5, "AMB参照の実在確認", "skipped", note="観点一覧・テストケースファイルなし")
    else:
        defined = set()
        for text in list(sr_texts.values()) + list(tdr_texts.values()):
            defined.update(_AMB_RE.findall(text))
        findings = []
        seen = set()
        for fname, text in list(vp_texts.items()) + list(tc_texts.items()):
            for amb_id in _AMB_RE.findall(text):
                if amb_id in defined or (fname, amb_id) in seen:
                    continue
                seen.add((fname, amb_id))
                findings.append({
                    "file": fname, "amb_id": amb_id,
                    "detail": f"{fname}: {amb_id}(どの仕様レビュー・テスト設計レビューファイルにも定義がない)",
                })
        note = None
        if not sr_files and not tdr_files:
            if findings:
                note = "仕様レビュー・テスト設計レビューファイルが存在しないため、全AMB参照が未定義扱い"
            else:
                add_check(5, "AMB参照の実在確認", "skipped",
                          note="仕様レビュー・テスト設計レビューファイルなし・AMB参照もなし")
                findings = None
        if findings is not None:
            add_check(5, "AMB参照の実在確認", "finding" if findings else "ok", findings, note=note)

    # --- チェック6: ID重複 ---
    if not vp_files and not tc_files:
        add_check(6, "ID重複", "skipped", note="観点一覧・テストケースファイルなし")
    else:
        findings = []
        for label, files, rows in (
            ("観点一覧", vp_files, [(f, i) for f, i, _ in vp_rows]),
            ("テストケース", tc_files, [(f, i) for f, i, _ in tc_rows]),
        ):
            if not files:
                continue
            per_file = {}
            for fname, rid in rows:
                if rid in _EMPTY_VALUES:
                    continue
                per_file.setdefault(fname, []).append(rid)
            for fname, ids in per_file.items():
                for dup_id, count in find_duplicates(ids):
                    findings.append({
                        "file": fname, "id": dup_id, "count": count,
                        "detail": f"{fname}: {dup_id}({label}内に{count}回出現)",
                    })
        add_check(6, "ID重複", "finding" if findings else "ok", findings)

    has_findings = any(c["status"] == "finding" for c in checks)

    # --- 出力 ---
    if args.as_json:
        result = {
            "session_dir": str(session_dir),
            "files": files_info,
            "checks": checks,
            "has_findings": has_findings,
            "note": "機械検出の結果であり、対応要否の判断はAI/人間が行う",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("# トレーサビリティ検証レポート(機械検出)")
        print()
        print("> ⚠️ これは trace_check.py による機械的な突合結果である。")
        print("> 検出項目への**対応要否の判断はAI/人間が行う**(未検出=問題なしを保証しない)。")
        print()
        print(f"対象ディレクトリ: {session_dir}")
        print()
        print("## 検出ファイル")
        for label, names in files_info.items():
            shown = ", ".join(names) if names else "(なし — 関連チェックをスキップ)"
            print(f"- {label}: {shown}")
        print()
        print("## チェック結果")
        status_label = {
            "ok": "OK",
            "finding": "検出",
            "info": "情報",
            "skipped": "スキップ",
        }
        for c in checks:
            head = f"[{c['no']}] {c['name']}: {status_label[c['status']]}"
            if c["status"] in ("finding", "info"):
                head += f" {len(c['findings'])}件"
            print(head)
            if c["note"]:
                print(f"    ({c['note']})")
            for f in c["findings"]:
                print(f"    - {f['detail']}")
        print()
        if has_findings:
            n = sum(len(c["findings"]) for c in checks if c["status"] == "finding")
            print(f"結果: 検出 {n}件(チェック2の情報提供を除く) → exit code 1")
        else:
            print("結果: 検出なし → exit code 0")

    return 1 if has_findings else 0


if __name__ == "__main__":
    sys.exit(main())
