#!/usr/bin/env python3
"""不具合一覧の下見・正規化・集計スクリプト(qa-defect-analysis 用)。

「定型処理はスクリプトに、判断はAIに」の方針に基づき、
qa-defect-analysis スキルの手順1(正規化)と手順3(傾向分析)のうち
機械的にできる部分を担当する。ラベル付けの判断そのものはAIが行う。

**正規化の出力は台帳CSV**(conventions.md §6-2)。表計算でそのまま開けて、
そのまま集計にかけられる。チケット一覧は現場ごとに列がまちまちなので、
**どの列を分析に持ち込むかはAIが選ぶ** — `inspect` で列を下見し、
`normalize --keep` で必要な列だけを持ち越す(--keep 省略時は全列を持ち越す。
正規化で情報を落とさないため)。

サブコマンド:
  inspect    不具合一覧CSVの列を下見する(列名・充足率・代表値・行数)。
             どの列を持ち越すかを選ぶための材料。判断はAIが行う。
  normalize  不具合一覧CSVを台帳CSVに変換する。ID・タイトル・持ち越した列に
             加えて、defect-taxonomy.md の4軸などの**空欄のラベル列**を付ける
             (AIが埋める)。
  stats      AIがラベルを埋めた台帳CSVを読み、件数集計を Markdown
             (または --json でJSON)で出力する。
  table      台帳CSVを Markdown 表にする(成果物の「分類結果」節に貼る。
             LLMに転記させないため)。

使用例:
  python defect_stats.py inspect bugs.csv
  python defect_stats.py normalize bugs.csv -o 01-defect-analysis/defects.csv
  python defect_stats.py normalize bugs.csv --id-col 番号 --title-col 件名 --keep 画面名
  python defect_stats.py stats defects.csv --by 画面名 --cross 画面名:test_gap
  python defect_stats.py table defects.csv --columns id,title,type,test_gap

依存: Python 3.9+ 標準ライブラリのみ。

exit code: 0=成功 / 1=検証エラー / 2=使用法エラー
"""

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter, OrderedDict

# ---------------------------------------------------------------------------
# 共通
# ---------------------------------------------------------------------------

AXIS_FIELDS = ["type", "injected", "detected", "test_gap"]

# normalize が付ける空欄のラベル列(defect-taxonomy.md「記録フォーマット」が定義元)
LABEL_FIELDS = AXIS_FIELDS + ["root_cause", "evidence_level", "sources"]

TAXONOMY_NOTE = "_shared/references/defect-taxonomy.md"

UNSET = "(未設定)"


def err(msg):
    print(msg, file=sys.stderr)


def die(msg, code=1):
    err("エラー: {}".format(msg))
    sys.exit(code)


def read_table(path):
    """CSVを (headers, rows, encoding) で読む。utf-8-sig → cp932 の順に試す。

    rows は dict にせずリストのまま返す(同名列があっても落とさないため)。
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        die("CSVファイルを読み込めません: {}".format(e))
    text = None
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        die("{} を utf-8-sig / cp932 のいずれでもデコードできませんでした。".format(path))

    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        die("CSVが空です。")
    headers = [h.strip() for h in rows[0]]
    return headers, rows[1:], enc


def cell(row, index):
    """行から列を取り出す(短い行・欠損を許容する)。"""
    if index is None or index >= len(row):
        return ""
    return (row[index] or "").strip()


def write_csv(path, header, rows):
    """台帳CSVを書き出す(BOM付きUTF-8。Excelでそのまま開ける)。"""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    text = out.getvalue()
    if path:
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(text)
        except OSError as e:
            die("出力できません: {}".format(e))
        err("{} に出力しました".format(path))
    else:
        sys.stdout.write(text)


def md_escape(value):
    """Markdownの表セルとして安全にする(改行は <br>、パイプはエスケープ)。"""
    value = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return value.replace("|", "\\|").replace("\n", "<br>")


# ---------------------------------------------------------------------------
# 列の推定
# ---------------------------------------------------------------------------

ID_KEYWORDS = ["id", "チケット", "番号", "連番", "キー", "key"]
TITLE_KEYWORDS = ["title", "タイトル", "件名", "概要", "summary", "現象", "事象"]


def guess_column(headers, keywords, exclude=()):
    """列名をキーワードで推定する。完全一致(大文字小文字無視)を優先し、次に部分一致。"""
    lowered = [(h, h.lower()) for h in headers if h not in exclude]
    for kw in keywords:
        for h, hl in lowered:
            if hl == kw.lower():
                return h
    for kw in keywords:
        for h, hl in lowered:
            if kw.lower() in hl:
                return h
    return None


# ---------------------------------------------------------------------------
# inspect サブコマンド
# ---------------------------------------------------------------------------


def sample_values(values, limit=2, width=40):
    """列の代表値(空でない先頭のユニーク値)を返す。"""
    seen = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
        if len(seen) >= limit:
            break
    out = []
    for v in seen:
        v = " ".join(v.split())
        out.append(v if len(v) <= width else v[:width] + "…")
    return " / ".join(out)


def cmd_inspect(args):
    headers, rows, enc = read_table(args.csvfile)
    total = len(rows)

    print("# 不具合一覧の下見: {}".format(args.csvfile))
    print("")
    print("- エンコーディング: {}".format(enc))
    print("- 行数(ヘッダー除く): {}件".format(total))
    print("- 列数: {}".format(len(headers)))
    print("")
    print("| 列名 | 充足率 | ユニーク数 | 代表値 |")
    print("|---|--:|--:|---|")
    for i, h in enumerate(headers):
        values = [cell(r, i) for r in rows]
        filled = sum(1 for v in values if v)
        ratio = "{:.0f}%".format(filled / total * 100) if total else "-"
        uniq = len(set(v for v in values if v))
        print("| {} | {} | {} | {} |".format(
            md_escape(h), ratio, uniq, md_escape(sample_values(values))))
    print("")

    id_col = args.id_col or guess_column(headers, ID_KEYWORDS)
    title_col = args.title_col or guess_column(
        headers, TITLE_KEYWORDS, {id_col} if id_col else ())
    print("自動推定: id 列 = {} / title 列 = {}".format(
        id_col or "(推定できず)", title_col or "(推定できず)"))
    print("")
    print("次の手順: 分析に使う列を選んで `normalize --keep <列名>` で持ち越す"
          "(--keep 省略時は全列を持ち越す)。")


# ---------------------------------------------------------------------------
# normalize サブコマンド
# ---------------------------------------------------------------------------


def parse_keep(spec, headers):
    """`元列名` または `元列名=出力列名` を (元列名, 出力列名) に解く。"""
    if "=" in spec:
        src, dst = spec.split("=", 1)
        src, dst = src.strip(), dst.strip()
    else:
        src = dst = spec.strip()
    if src not in headers:
        die("--keep で指定された列「{}」がCSVにありません。利用可能な列: {}".format(
            src, ", ".join(headers)))
    if not dst:
        die("--keep の出力列名が空です: {}".format(spec))
    return src, dst


def resolve_column(explicit, option, headers, keywords, exclude):
    """明示指定を優先し、無ければキーワードで推定する。見つからなければ None。"""
    if explicit:
        if explicit not in headers:
            die("{} で指定された列「{}」がCSVにありません。利用可能な列: {}".format(
                option, explicit, ", ".join(headers)))
        return explicit
    return guess_column(headers, keywords, exclude)


def cmd_normalize(args):
    headers, rows, enc = read_table(args.csvfile)
    err("エンコーディング: {} で読み込みました".format(enc))

    id_col = resolve_column(args.id_col, "--id-col", headers, ID_KEYWORDS, ())
    if id_col:
        if not args.id_col:
            err("id 列を自動推定: 「{}」".format(id_col))
    else:
        err("警告: ID列を推定できませんでした。全行に仮ID(NOID-NN)を割り当てます"
            "(--id-col で指定できます)")

    title_col = resolve_column(args.title_col, "--title-col", headers, TITLE_KEYWORDS,
                               {id_col} if id_col else ())
    if title_col:
        if not args.title_col:
            err("title 列を自動推定: 「{}」".format(title_col))
    else:
        die("title 列を推定できませんでした。--title-col で指定してください"
            "(列の下見は `defect_stats.py inspect` を使う)。\n利用可能な列: {}".format(
                ", ".join(headers)))

    # 持ち越す列。既定は id/title 以外の全列(正規化で情報を落とさないため)
    mapped = set(c for c in (id_col, title_col) if c)
    if args.keep:
        keeps = [parse_keep(spec, headers) for spec in args.keep]
    else:
        keeps = [(h, h) for h in headers if h not in mapped]
        if keeps:
            err("持ち越す列(既定=全列): {}".format(", ".join(dst for _, dst in keeps)))

    carried = [dst for _, dst in keeps]
    dup = sorted(c for c, n in Counter(["id", "title"] + carried).items() if n > 1)
    if dup:
        die("出力列名が重複します: {}(--keep の `元列名=出力列名` で改名してください)".format(
            ", ".join(dup)))

    # 空欄のラベル列。持ち越した列と同名のものは、既に値があるとみなして追加しない
    labels = [f for f in LABEL_FIELDS if f not in carried] + list(args.add_label or [])

    header = ["id", "title"] + carried + labels
    idx = {h: i for i, h in enumerate(headers)}

    out_rows = []
    noid = 0
    seen_ids = Counter()
    for n, row in enumerate(rows, start=2):  # n = CSV上の行番号(ヘッダー=1行目)
        bug_id = cell(row, idx.get(id_col)) if id_col else ""
        if not bug_id:
            noid += 1
            bug_id = "NOID-{:02d}".format(noid)
            if id_col:  # ID列自体が無い場合は列単位で警告済みなので行ごとには出さない
                err("警告: {}行目のIDが空のため {} を割り当てました".format(n, bug_id))
        seen_ids[bug_id] += 1

        values = [bug_id, cell(row, idx[title_col])]
        for src, _dst in keeps:
            v = cell(row, idx[src])
            if args.max_cell and len(v) > args.max_cell:
                v = v[:args.max_cell] + "…"
            values.append(v)
        for f in labels:
            values.append(bug_id if f == "sources" else "")
        out_rows.append(values)

    for bug_id, count in sorted(seen_ids.items()):
        if count > 1:
            err("警告: ID {} が{}件重複しています(集計が二重計上になります)".format(bug_id, count))

    write_csv(args.output, header, out_rows)
    err("{}件を正規化しました。空欄のラベル列({})は {} を参照してAIが埋めます。".format(
        len(out_rows), ", ".join(labels) or "なし", TAXONOMY_NOTE))


# ---------------------------------------------------------------------------
# stats サブコマンド
# ---------------------------------------------------------------------------

_SEP_RE = re.compile(r"[;\n]+")
_SEP_SLASH_RE = re.compile(r"[;\n/]+")


def load_records(path):
    """台帳CSVを (list of dict, headers) で読む。"""
    headers, rows, _enc = read_table(path)
    records = [OrderedDict((h, cell(row, i)) for i, h in enumerate(headers)) for row in rows]
    return records, headers


def split_multi(value, slash=False):
    """複数値のセルを分割する(`;` とセル内改行。type だけは `/` でも分割する)。"""
    if not value:
        return []
    pattern = _SEP_SLASH_RE if slash else _SEP_RE
    return [p.strip() for p in pattern.split(value) if p.strip()]


def labels_of(rec, column):
    """集計対象のラベルを返す(未設定なら (未設定))。"""
    return split_multi(rec.get(column, ""), slash=(column == "type")) or [UNSET]


def distribution(records, column):
    c = Counter()
    for r in records:
        for label in labels_of(r, column):
            c[label] += 1
    return c


def cross_tab(records, row_col, col_col):
    table = {}
    for r in records:
        for a in labels_of(r, row_col):
            for b in labels_of(r, col_col):
                table.setdefault(a, Counter())[b] += 1
    return table


def aggregate(records, headers, by_cols, cross_pairs):
    missing = []
    for i, r in enumerate(records, start=1):
        gaps = [a for a in AXIS_FIELDS if not r.get(a, "").strip()]
        if gaps:
            missing.append({"id": r.get("id", "") or "(id欠落 {}件目)".format(i),
                            "missing": gaps})

    return {
        "total": len(records),
        "absent_columns": [c for c in AXIS_FIELDS + ["evidence_level"] if c not in headers],
        "evidence_level": distribution(records, "evidence_level"),
        "dist": OrderedDict((axis, distribution(records, axis)) for axis in AXIS_FIELDS),
        "escape": sum(1 for r in records if r.get("detected", "").strip() == "本番流出"),
        "by": OrderedDict((c, distribution(records, c)) for c in by_cols),
        "cross": OrderedDict(((a, b), cross_tab(records, a, b)) for a, b in cross_pairs),
        "missing": missing,
    }


def sorted_counter(c):
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))


def pct(n, total):
    return "{:.1f}%".format(n / total * 100) if total else "-"


AXIS_TITLE = {
    "type": "軸1: 不具合の種類(type)の分布",
    "injected": "軸2: 混入工程(injected)の分布",
    "detected": "軸3: 検出工程(detected)の分布",
    "test_gap": "軸4: テストギャップ(test_gap)の分布",
}


def render_markdown(agg):
    total = agg["total"]
    lines = []
    add = lines.append
    add("# 不具合集計レポート(defect_stats.py による機械集計)")
    add("")
    add("> 本集計はスクリプトによる機械カウントであり、LLMによる手数えではありません。")
    add("")
    if agg["absent_columns"]:
        add("> 注意: 台帳に無い列があります(全件が「{}」として数えられます): {}".format(
            UNSET, ", ".join(agg["absent_columns"])))
        add("")

    num = [0]

    def heading(title):
        num[0] += 1
        add("## {}. {}".format(num[0], title))
        add("")

    heading("総件数と evidence_level")
    add("総件数: **{}件**".format(total))
    add("")
    add("| evidence_level | 件数 | 比率 |")
    add("|---|--:|--:|")
    order = ["confirmed", "likely", "hypothesis"]
    ev = agg["evidence_level"]
    keys = [k for k in order if k in ev] + sorted(k for k in ev if k not in order and k != UNSET)
    if UNSET in ev:
        keys.append(UNSET)
    for k in keys:
        add("| {} | {} | {} |".format(k, ev[k], pct(ev[k], total)))
    add("")

    def dist_section(title, counter, note=""):
        heading(title)
        if note:
            add(note)
            add("")
        add("| ラベル | 件数 | 比率 |")
        add("|---|--:|--:|")
        for label, n in sorted_counter(counter):
            style = "**" if label == "本番流出" else ""
            add("| {s}{}{s} | {s}{}{s} | {s}{}{s} |".format(
                md_escape(label), n, pct(n, total), s=style))
        add("")

    for axis in AXIS_FIELDS:
        note = ("※ `;` `/` 区切りの複数値は分割して各ラベルにカウント(合計は総件数を超えうる)。"
                if axis == "type" else "")
        dist_section(AXIS_TITLE[axis], agg["dist"][axis], note)
        if axis == "detected":
            add("**本番流出: {}件 / {}件({})**".format(
                agg["escape"], total, pct(agg["escape"], total)))
            add("")

    for col, counter in agg["by"].items():
        dist_section("列「{}」の分布".format(col), counter,
                     "※ `;` 区切り・セル内改行の複数値は分割してカウント。")

    for (a, b), table in agg["cross"].items():
        heading("クロス集計: {} × {}".format(a, b))
        col_totals = Counter()
        for counter in table.values():
            col_totals.update(counter)
        cols = [c for c, _ in sorted_counter(col_totals)]
        add("| {} \\ {} | ".format(md_escape(a), md_escape(b))
            + " | ".join(md_escape(c) for c in cols) + " | 計 |")
        add("|---|" + "--:|" * (len(cols) + 1))
        for key, counter in sorted(table.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
            cells = [str(counter.get(c, "")) or "" for c in cols]
            add("| {} | ".format(md_escape(key)) + " | ".join(cells)
                + " | {} |".format(sum(counter.values())))
        add("")

    heading("ラベル未設定(埋め漏れ)")
    missing = agg["missing"]
    if not missing:
        add("未設定の軸ラベルはありません(4軸すべて設定済み)。")
    else:
        add("4軸のいずれかが未設定の不具合: **{}件**".format(len(missing)))
        add("")
        add("| ID | 未設定の軸 |")
        add("|---|---|")
        for m in missing:
            add("| {} | {} |".format(md_escape(m["id"]), ", ".join(m["missing"])))
    add("")
    return "\n".join(lines)


def render_json(agg):
    out = {
        "generated_by": "defect_stats.py(機械集計)",
        "total": agg["total"],
        "absent_columns": agg["absent_columns"],
        "evidence_level": dict(sorted_counter(agg["evidence_level"])),
        "production_escape": {
            "count": agg["escape"],
            "ratio": round(agg["escape"] / agg["total"], 4) if agg["total"] else None,
        },
        "by": {col: dict(sorted_counter(c)) for col, c in agg["by"].items()},
        "cross": {"{} x {}".format(a, b): {k: dict(sorted_counter(v)) for k, v in table.items()}
                  for (a, b), table in agg["cross"].items()},
        "missing_labels": {"count": len(agg["missing"]), "items": agg["missing"]},
    }
    for axis in AXIS_FIELDS:
        out[axis] = dict(sorted_counter(agg["dist"][axis]))
    return json.dumps(out, ensure_ascii=False, indent=2)


def cmd_stats(args):
    records, headers = load_records(args.csvfile)
    if not records:
        die("対象レコードが0件です。")

    for col in args.by or []:
        if col not in headers:
            die("--by で指定された列「{}」が台帳にありません。利用可能な列: {}".format(
                col, ", ".join(headers)))

    # 種類×テストギャップ(流出パターン)は常に出す。--cross はそこへの追加
    pairs = [("type", "test_gap")]
    for spec in (args.cross or []):
        if ":" not in spec:
            die("--cross は `行の列:列の列` の形式で指定してください(例 type:test_gap): {}".format(spec))
        a, b = (p.strip() for p in spec.split(":", 1))
        for col in (a, b):
            if col not in headers and col not in AXIS_FIELDS:
                die("--cross で指定された列「{}」が台帳にありません。利用可能な列: {}".format(
                    col, ", ".join(headers)))
        if (a, b) not in pairs:
            pairs.append((a, b))

    agg = aggregate(records, headers, args.by or [], pairs)
    print(render_json(agg) if args.json else render_markdown(agg))


# ---------------------------------------------------------------------------
# table サブコマンド
# ---------------------------------------------------------------------------


def cmd_table(args):
    records, headers = load_records(args.csvfile)
    if args.columns:
        cols = [c.strip() for c in args.columns.split(",") if c.strip()]
        for c in cols:
            if c not in headers:
                die("--columns で指定された列「{}」が台帳にありません。利用可能な列: {}".format(
                    c, ", ".join(headers)))
    else:
        cols = headers

    lines = ["| " + " | ".join(md_escape(c) for c in cols) + " |",
             "|" + "---|" * len(cols)]
    for r in records:
        cells = []
        for c in cols:
            v = r.get(c, "")
            if args.max_cell and len(v) > args.max_cell:
                v = v[:args.max_cell] + "…"
            cells.append(md_escape(v))
        lines.append("| " + " | ".join(cells) + " |")
    print("\n".join(lines))
    err("{}件 / {}列を表にしました".format(len(records), len(cols)))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="defect_stats.py",
        description="不具合一覧の下見・正規化(CSV→台帳CSV)と、ラベル付け後の件数集計。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ins = sub.add_parser("inspect", help="不具合一覧CSVの列を下見する(列名・充足率・代表値)")
    p_ins.add_argument("csvfile", help="不具合一覧CSVファイル")
    p_ins.add_argument("--id-col", help="ID列の列名(省略時は自動推定)")
    p_ins.add_argument("--title-col", help="タイトル列の列名(省略時は自動推定)")
    p_ins.set_defaults(func=cmd_inspect)

    p_norm = sub.add_parser("normalize", help="不具合一覧CSVをラベル列付きの台帳CSVに変換する")
    p_norm.add_argument("csvfile", help="不具合一覧CSVファイル")
    p_norm.add_argument("--id-col", help="ID列の列名(省略時は自動推定。無ければ NOID-NN)")
    p_norm.add_argument("--title-col", help="タイトル列の列名(省略時は自動推定)")
    p_norm.add_argument("--keep", action="append", metavar="列名[=出力列名]",
                        help="持ち越す列(複数指定可)。省略時は id/title 以外の全列")
    p_norm.add_argument("--add-label", action="append", metavar="列名",
                        help="4軸以外に追加したい空欄のラベル列(複数指定可)")
    p_norm.add_argument("--max-cell", type=int, default=0, metavar="N",
                        help="持ち越す列の最大文字数(既定 0 = 制限なし)")
    p_norm.add_argument("-o", "--output", help="出力ファイル(省略時は stdout)")
    p_norm.set_defaults(func=cmd_normalize)

    p_stats = sub.add_parser("stats", help="ラベル付き台帳CSVを集計してMarkdownで出力する")
    p_stats.add_argument("csvfile", help="ラベル付き台帳CSVファイル")
    p_stats.add_argument("--json", action="store_true", help="機械可読JSONで出力する")
    p_stats.add_argument("--by", action="append", metavar="列名",
                         help="任意の列の分布も集計する(複数指定可。例: 画面名)")
    p_stats.add_argument("--cross", action="append", metavar="行の列:列の列",
                         help="クロス集計を追加する(複数指定可。type:test_gap は常に出力)")
    p_stats.set_defaults(func=cmd_stats)

    p_table = sub.add_parser("table", help="台帳CSVをMarkdown表にする(成果物への転記用)")
    p_table.add_argument("csvfile", help="台帳CSVファイル")
    p_table.add_argument("--columns", metavar="列名,列名,...", help="出力する列(既定は全列)")
    p_table.add_argument("--max-cell", type=int, default=0, metavar="N",
                         help="セルの最大文字数(既定 0 = 制限なし)")
    p_table.set_defaults(func=cmd_table)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
