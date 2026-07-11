#!/usr/bin/env python3
"""不具合一覧の正規化・集計スクリプト(qa-defect-analysis 用)。

「定型処理はスクリプトに、判断はAIに」の方針に基づき、
qa-defect-analysis スキルの手順1(正規化)と手順3(傾向分析)のうち
機械的にできる部分を担当する。ラベル付けの判断そのものはAIが行う。

サブコマンド:
  normalize  不具合一覧CSVを読み、defect-taxonomy.md の記録フォーマットに
             沿ったYAML雛形を生成する(ラベル欄は空欄。AIが埋める)。
  stats      AIがラベルを埋めたYAML(またはJSON)を読み、件数集計を
             Markdown(または --json でJSON)で出力する。

使用例:
  python defect_stats.py normalize bugs.csv -o 01-normalized.yaml
  python defect_stats.py normalize bugs.csv --id-col チケット番号 --title-col 件名
  python defect_stats.py stats 01-labeled.yaml
  python defect_stats.py stats 01-labeled.yaml --json

依存: Python 3.9+ 標準ライブラリのみ(PyYAML 不要。限定サブセットの
ミニYAMLパーサーを内蔵)。

exit code: 0=成功 / 1=検証エラー / 2=使用法エラー
"""

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# 共通
# ---------------------------------------------------------------------------

AXIS_FIELDS = ["type", "injected", "detected", "test_gap"]

TAXONOMY_NOTE = "_shared/references/defect-taxonomy.md"


def err(msg):
    print(msg, file=sys.stderr)


def die(msg, code=1):
    err(f"エラー: {msg}")
    sys.exit(code)


# ---------------------------------------------------------------------------
# normalize サブコマンド
# ---------------------------------------------------------------------------

ID_KEYWORDS = ["id", "チケット", "番号", "キー", "key"]
TITLE_KEYWORDS = ["title", "タイトル", "件名", "概要", "summary"]
DESC_KEYWORDS = ["description", "説明", "詳細", "内容"]


def read_csv_with_fallback(path):
    """utf-8-sig → cp932 の順にデコードを試み、(テキスト, エンコーディング名) を返す。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        die(f"CSVファイルを読み込めません: {e}")
    for enc in ("utf-8-sig", "cp932"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    die(f"{path} を utf-8-sig / cp932 のいずれでもデコードできませんでした。")


def guess_column(headers, keywords, exclude):
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


_PLAIN_SCALAR_RE = re.compile(r"^[^\s#\[\]{}'\"|>&*!%@`,][^#]*$")


def yaml_scalar(value):
    """雛形出力用: プレーンスカラーで安全に書けない値は二重引用符でエスケープする。"""
    value = str(value)
    if value and ": " not in value and not value.endswith(":") and _PLAIN_SCALAR_RE.match(value) and value == value.strip():
        return value
    return json.dumps(value, ensure_ascii=False)


def cmd_normalize(args):
    text, enc = read_csv_with_fallback(args.csvfile)
    err(f"エンコーディング: {enc} で読み込みました")

    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        die("CSVが空です。")
    headers = [h.strip() for h in rows[0]]
    records = rows[1:]

    chosen = {}
    specs = [
        ("id", args.id_col, ID_KEYWORDS, True),
        ("title", args.title_col, TITLE_KEYWORDS, True),
        ("desc", args.desc_col, DESC_KEYWORDS, False),
    ]
    for role, explicit, keywords, required in specs:
        if explicit:
            if explicit not in headers:
                die(f"指定された列「{explicit}」がCSVにありません。利用可能な列: {', '.join(headers)}")
            chosen[role] = explicit
        else:
            col = guess_column(headers, keywords, set(chosen.values()))
            if col:
                chosen[role] = col
                err(f"{role} 列を自動推定: 「{col}」")
            elif required:
                die(
                    f"{role} 列を推定できませんでした。--{role}-col で指定してください。\n"
                    f"利用可能な列: {', '.join(headers)}"
                )
            else:
                err(f"{role} 列は見つかりませんでした(省略します)")

    idx = {role: headers.index(col) for role, col in chosen.items()}

    out_lines = [f"# defect_stats.py normalize が生成した雛形。空欄ラベルは {TAXONOMY_NOTE} を参照してAIが埋める。"]
    count = 0
    for n, row in enumerate(records, start=2):  # n = CSV上の行番号(ヘッダー=1行目)
        def cell(role):
            i = idx.get(role)
            return row[i].strip() if i is not None and i < len(row) else ""

        bug_id = cell("id") or f"ROW-{n}"
        if not cell("id"):
            err(f"警告: {n}行目のIDが空のため {bug_id} を割り当てました")
        title = cell("title")
        desc = cell("desc").replace("\r", " ").replace("\n", " ").strip()

        out_lines.append(f"- id: {yaml_scalar(bug_id)}")
        out_lines.append(f"  title: {yaml_scalar(title)}")
        if desc:
            if len(desc) > 300:
                desc = desc[:300] + "…"
            out_lines.append(f"  # 説明: {desc}")
        out_lines.append("  type:            # 軸1: 不具合の種類(複数は / 区切り)")
        out_lines.append("  injected:        # 軸2: 混入工程")
        out_lines.append("  detected:        # 軸3: 検出工程")
        out_lines.append("  test_gap:        # 軸4: テストギャップ")
        out_lines.append("  root_cause:")
        out_lines.append("  evidence_level:")
        out_lines.append(f"  sources: [{yaml_scalar(bug_id)}]")
        count += 1

    output = "\n".join(out_lines) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        err(f"{args.output} に出力しました")
    else:
        sys.stdout.write(output)
    err(f"{count}件を正規化しました")


# ---------------------------------------------------------------------------
# ミニYAMLパーサー(限定サブセット)
# ---------------------------------------------------------------------------
# 対応する構文:
#   - `- key: value` で始まるリスト項目と、その継続行 `  key: value`
#   - 値: プレーンスカラー / 引用符付きスカラー / `[a, b]` 形式のインラインリスト
#   - `#` コメント(行全体・行末)、空行、ドキュメント区切り `---`
# 非対応(行番号付きでエラーにする): ネストしたマッピング・リスト、
#   複数行文字列(| や >)、アンカー等その他のYAML構文。

_KEY_RE = re.compile(r"^([A-Za-z0-9_\-]+):(?:\s+(.*))?$")


class YamlError(Exception):
    pass


def _strip_comment(s):
    """引用符の外にある ` #`(または先頭の `#`)以降を落とす。"""
    quote = None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s.rstrip()


def _parse_scalar(raw, lineno):
    raw = raw.strip()
    if raw in ("|", ">") or raw.startswith(("|", ">")) and len(raw) <= 2:
        raise YamlError(f"{lineno}行目: 複数行文字列(| / >)には対応していません")
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise YamlError(f"{lineno}行目: 二重引用符付き文字列を解釈できません: {raw}")
    if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    return raw


def _parse_value(raw, lineno):
    raw = _strip_comment(raw or "").strip()
    if raw == "":
        return ""
    if raw.startswith("["):
        if not raw.endswith("]"):
            raise YamlError(f"{lineno}行目: インラインリストが `]` で閉じていません: {raw}")
        inner = raw[1:-1].strip()
        if "[" in inner or "{" in inner:
            raise YamlError(f"{lineno}行目: ネストしたインラインリスト/マッピングには対応していません: {raw}")
        if inner == "":
            return []
        return [_parse_scalar(p, lineno) for p in inner.split(",")]
    if raw.startswith("{"):
        raise YamlError(f"{lineno}行目: インラインマッピング {{...}} には対応していません")
    return _parse_scalar(raw, lineno)


def parse_mini_yaml(text):
    """限定サブセットのYAMLを list of dict にパースする。非対応構文は YamlError。"""
    records = []
    current = None
    expected_indent = None  # 継続行のキーのインデント

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise YamlError(f"{lineno}行目: インデントにタブは使えません")

        m = re.match(r"^(\s*)-(\s+)(.*)$", line)
        if m and not m.group(3).startswith("-"):
            rest = m.group(3)
            key_m = _KEY_RE.match(rest)
            if not key_m:
                raise YamlError(
                    f"{lineno}行目: リスト項目は `- key: value` 形式のみ対応です(ネストしたリスト・"
                    f"スカラーのみの項目は非対応): {stripped}"
                )
            current = {}
            records.append(current)
            expected_indent = len(m.group(1)) + 1 + len(m.group(2))
            key, value = key_m.group(1), key_m.group(2)
            current[key] = _parse_value(value, lineno)
            continue
        if m:
            raise YamlError(f"{lineno}行目: ネストしたリストには対応していません: {stripped}")

        indent = len(line) - len(line.lstrip())
        if current is None:
            raise YamlError(f"{lineno}行目: リスト項目(`- key: value`)の外にキーがあります: {stripped}")
        if indent != expected_indent:
            raise YamlError(
                f"{lineno}行目: インデントが不正です(期待: {expected_indent} 桁 / 実際: {indent} 桁)。"
                f"ネストしたマッピング等には対応していません: {stripped}"
            )
        key_m = _KEY_RE.match(stripped)
        if not key_m:
            raise YamlError(f"{lineno}行目: `key: value` 形式として解釈できません: {stripped}")
        key, value = key_m.group(1), key_m.group(2)
        current[key] = _parse_value(value, lineno)

    return records


# ---------------------------------------------------------------------------
# stats サブコマンド
# ---------------------------------------------------------------------------


def load_records(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        die(f"ファイルを読み込めません: {e}")
    if path.lower().endswith(".json"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            die(f"JSONを解釈できません({path} {e.lineno}行目): {e.msg}")
        if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
            die("JSONは list of objects 形式である必要があります。")
        return data
    try:
        return parse_mini_yaml(text)
    except YamlError as e:
        die(f"YAMLを解釈できません({path}): {e}")


def field_str(rec, key):
    """レコードのフィールドを正規化して文字列で返す(list は ' / ' 連結)。"""
    v = rec.get(key)
    if v is None:
        return ""
    if isinstance(v, list):
        return " / ".join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip()


def split_multi(value):
    """`/` 区切りの複数値を分割する。空なら空リスト。"""
    return [p.strip() for p in value.split("/") if p.strip()] if value else []


UNSET = "(未設定)"


def aggregate(records):
    total = len(records)

    ev = Counter()
    for r in records:
        ev[field_str(r, "evidence_level") or UNSET] += 1

    dist = {}
    for axis in AXIS_FIELDS:
        c = Counter()
        for r in records:
            v = field_str(r, axis)
            if axis == "type":
                labels = split_multi(v) or [UNSET]
            else:
                labels = [v or UNSET]
            for lb in labels:
                c[lb] += 1
        dist[axis] = c

    escape = sum(1 for r in records if field_str(r, "detected") == "本番流出")

    cross = {}
    for r in records:
        types = split_multi(field_str(r, "type")) or [UNSET]
        gap = field_str(r, "test_gap") or UNSET
        for t in types:
            cross.setdefault(t, Counter())[gap] += 1

    missing = []
    for i, r in enumerate(records, start=1):
        gaps = [a for a in AXIS_FIELDS if not field_str(r, a)]
        if gaps:
            missing.append({"id": field_str(r, "id") or f"(id欠落 {i}件目)", "missing": gaps})

    return {
        "total": total,
        "evidence_level": ev,
        "dist": dist,
        "escape": escape,
        "cross": cross,
        "missing": missing,
    }


def sorted_counter(c):
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))


def pct(n, total):
    return f"{n / total * 100:.1f}%" if total else "-"


def render_markdown(agg):
    total = agg["total"]
    lines = []
    add = lines.append
    add("# 不具合集計レポート(defect_stats.py による機械集計)")
    add("")
    add("> 本集計はスクリプトによる機械カウントであり、LLMによる手数えではありません。")
    add("")

    add("## 1. 総件数と evidence_level")
    add("")
    add(f"総件数: **{total}件**")
    add("")
    add("| evidence_level | 件数 | 比率 |")
    add("|---|--:|--:|")
    order = ["confirmed", "likely", "hypothesis"]
    ev = agg["evidence_level"]
    keys = [k for k in order if k in ev] + sorted(k for k in ev if k not in order and k != UNSET)
    if UNSET in ev:
        keys.append(UNSET)
    for k in keys:
        add(f"| {k} | {ev[k]} | {pct(ev[k], total)} |")
    add("")

    def dist_section(no, axis, title, note=""):
        add(f"## {no}. {title}")
        add("")
        if note:
            add(note)
            add("")
        add("| ラベル | 件数 | 比率 |")
        add("|---|--:|--:|")
        for label, n in sorted_counter(agg["dist"][axis]):
            style = "**" if (axis == "detected" and label == "本番流出") else ""
            add(f"| {style}{label}{style} | {style}{n}{style} | {style}{pct(n, total)}{style} |")
        add("")

    dist_section("2", "type", "軸1: 不具合の種類(type)の分布",
                 "※ `/` 区切りの複数値は分割して各ラベルにカウント(合計は総件数を超えうる)。")
    dist_section("3", "injected", "軸2: 混入工程(injected)の分布")
    dist_section("4", "detected", "軸3: 検出工程(detected)の分布")
    add(f"**本番流出: {agg['escape']}件 / {total}件({pct(agg['escape'], total)})**")
    add("")
    dist_section("5", "test_gap", "軸4: テストギャップ(test_gap)の分布")

    add("## 6. クロス集計: 軸1(type)× 軸4(test_gap)")
    add("")
    add("流出パターンの特定用。type の複数値は分割してカウント。")
    add("")
    cross = agg["cross"]
    gap_totals = Counter()
    for gc in cross.values():
        gap_totals.update(gc)
    gap_cols = [g for g, _ in sorted_counter(gap_totals)]
    add("| type \\ test_gap | " + " | ".join(gap_cols) + " | 計 |")
    add("|---|" + "--:|" * (len(gap_cols) + 1))
    rows = sorted(cross.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    for t, gc in rows:
        cells = [str(gc.get(g, "")) or "" for g in gap_cols]
        add(f"| {t} | " + " | ".join(cells) + f" | {sum(gc.values())} |")
    add("")

    add("## 7. ラベル未設定(埋め漏れ)")
    add("")
    missing = agg["missing"]
    if not missing:
        add("未設定の軸ラベルはありません(4軸すべて設定済み)。")
    else:
        add(f"4軸のいずれかが未設定の不具合: **{len(missing)}件**")
        add("")
        add("| ID | 未設定の軸 |")
        add("|---|---|")
        for m in missing:
            add(f"| {m['id']} | {', '.join(m['missing'])} |")
    add("")
    return "\n".join(lines)


def render_json(agg):
    out = {
        "generated_by": "defect_stats.py(機械集計)",
        "total": agg["total"],
        "evidence_level": dict(sorted_counter(agg["evidence_level"])),
        "type": dict(sorted_counter(agg["dist"]["type"])),
        "injected": dict(sorted_counter(agg["dist"]["injected"])),
        "detected": dict(sorted_counter(agg["dist"]["detected"])),
        "production_escape": {
            "count": agg["escape"],
            "ratio": round(agg["escape"] / agg["total"], 4) if agg["total"] else None,
        },
        "test_gap": dict(sorted_counter(agg["dist"]["test_gap"])),
        "cross_type_x_test_gap": {t: dict(sorted_counter(c)) for t, c in agg["cross"].items()},
        "missing_labels": {"count": len(agg["missing"]), "items": agg["missing"]},
    }
    return json.dumps(out, ensure_ascii=False, indent=2)


def cmd_stats(args):
    records = load_records(args.yamlfile)
    if not records:
        die("対象レコードが0件です。")
    agg = aggregate(records)
    print(render_json(agg) if args.json else render_markdown(agg))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="defect_stats.py",
        description="不具合一覧の正規化(CSV→YAML雛形)と、ラベル付け後の件数集計。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_norm = sub.add_parser("normalize", help="CSVを defect-taxonomy.md 準拠のYAML雛形に変換する")
    p_norm.add_argument("csvfile", help="不具合一覧CSVファイル")
    p_norm.add_argument("--id-col", help="ID列の列名(省略時は自動推定)")
    p_norm.add_argument("--title-col", help="タイトル列の列名(省略時は自動推定)")
    p_norm.add_argument("--desc-col", help="説明列の列名(省略時は自動推定)")
    p_norm.add_argument("-o", "--output", help="出力ファイル(省略時は stdout)")
    p_norm.set_defaults(func=cmd_normalize)

    p_stats = sub.add_parser("stats", help="ラベル付きYAML/JSONを集計してMarkdownで出力する")
    p_stats.add_argument("yamlfile", help="ラベル付きYAMLファイル(.json も可)")
    p_stats.add_argument("--json", action="store_true", help="機械可読JSONで出力する")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
