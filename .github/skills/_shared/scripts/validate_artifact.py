#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""構造化成果物(YAML)のスキーマ検証。

`30-test-viewpoint/` のような**台帳系の成果物**(台帳CSV + notes.md)を `_shared/schemas/` の
スキーマに照らして検証する。Markdown を字面で検査する `lint_output.py` と違い、
**フィールドを直接見るので誤検出しない** — だからこそ hook でブロックできる
(hooks.md §5「ブロックしてよいのは誤検出しない検査だけ」)。

規約との対応(各ルールは conventions.md の節を指す):

    unique_ids                §6-1  ID の重複禁止
    id_pattern                §6-1  ID 書式(VP-NN / TC-NN 等)
    required_fields                 必須フィールドの欠落
    enum_values               §5-1 / §5-2  evidence_level・derivation・優先度の値
    explicit_requires_sources §5-3  **explicit なのに出典がない = 根拠なし事実主張**
    no_vague_expected               期待結果に合否判定できない語を使わない

`explicit_requires_sources` が中心。conventions.md §11 は「根拠なし事実主張率
(目標0%)」を事後の指標として測っていたが、スキーマ検証では**書いた時点で
エラーになる**。「指標の悪化ではなく規約違反として扱う」が文字どおりになる。

使用例:
    python validate_artifact.py qa-output/s1/30-test-viewpoint
    python validate_artifact.py --session-dir qa-output/s1
    python validate_artifact.py qa-output/s1/30-test-viewpoint --json

スキーマは成果物ディレクトリ名から引く(`NN-<名前>/` → `schemas/<名前>.yaml`)。
対応するスキーマが無い成果物は検証をスキップする(段階導入のため)。

exit code: 0=エラーなし / 1=エラーあり / 2=使用法エラー
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import miniyaml  # noqa: E402

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
ARTIFACT_RE = re.compile(r"^(\d{2})-([0-9a-z][0-9a-z\-]*)$")

# lint_output.py §5 と同じ語(定義元: qa-test-case-design の品質基準)
AMBIGUOUS_WORDS = ("正しく", "正しい", "適切に", "適切な", "適切で",
                   "きちんと", "問題なく", "正常に動作")

TRUE_VALUES = ("yes", "true", "on", "1")


def _truthy(v):
    return str(v).strip().lower() in TRUE_VALUES


class Result:
    def __init__(self, path):
        self.path = str(path)
        self.artifact = None
        self.schema = None
        self.issues = []

    def add(self, severity, where, rule, message):
        self.issues.append({"severity": severity, "where": where,
                            "rule": rule, "message": message})

    @property
    def errors(self):
        return sum(1 for i in self.issues if i["severity"] == "ERROR")

    @property
    def warnings(self):
        return sum(1 for i in self.issues if i["severity"] == "WARN")


# ---------------------------------------------------------------------------
# スキーマの解決
# ---------------------------------------------------------------------------

def schema_for(path):
    """成果物ファイル名から対応するスキーマのパスを返す。無ければ None。

    `40-spec-review-requirements.yaml` のように対象別の接尾辞が付くことがある
    (conventions.md §6)ため、末尾のセグメントを削りながら最長一致で探す。
    """
    m = ARTIFACT_RE.match(os.path.basename(str(path)))
    if not m:
        return None
    stem = m.group(2)
    while stem:
        cand = SCHEMA_DIR / "{}.yaml".format(stem)
        if cand.is_file():
            return cand
        if "-" not in stem:
            return None
        stem = stem.rsplit("-", 1)[0]
    return None


def ledgers_of(schema):
    """スキーマの台帳定義を list で返す。1成果物が複数の台帳を持つことがある
    (例: 意図モデルは ACT / STT / TRN / BG / HO / US の6つ)。"""
    if "ledgers" in schema and isinstance(schema["ledgers"], list):
        return schema["ledgers"]
    if "ledger" in schema:
        return [schema["ledger"]]
    return []


# ---------------------------------------------------------------------------
# 成果物の読み込み(台帳はCSV、叙述は notes.md)
#
# 台帳を CSV にしているのは、QAの現場が表計算で成果物を読み書きするため。
# 1台帳=1CSVなので Excel / スプレッドシートでそのまま開ける。
# 副次的に、LLMが書くファイルからYAMLが消える — 自前パーサー(miniyaml)が
# 読むのはメンテナーが書くスキーマだけになり、壊れ方の面が減る。
# ---------------------------------------------------------------------------

# リスト型セルの区切り。日本語テキストにまず現れない文字を選んでいる。
# セル内改行(Excel の Alt+Enter)でも区切れる
LIST_SEPARATOR = ";"

NOTES_FILE = "notes.md"
_SECTION_HEAD_RE = re.compile(r"^##\s*(\d+)\s*[.．]\s*(.*)$")


def artifact_dir_of(path):
    """成果物のディレクトリを返す。`<NN>-<名前>/` そのものか、その中のファイル。"""
    p = Path(path)
    if p.is_dir():
        return p
    return p.parent


def read_table(path):
    """CSVを list of dict で読む。Excel が書く BOM / cp932 を許容する。"""
    for encoding in ("utf-8-sig", "cp932"):
        try:
            with open(path, newline="", encoding=encoding) as f:
                rows = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("文字コードを判別できません(UTF-8 / cp932 のいずれでもない)")
    out = []
    for row in rows:
        rec = {}
        for k, v in row.items():
            if k is None:
                continue
            key = str(k).strip().lstrip("﻿")
            if not key:
                continue
            rec[key] = (v or "").strip()
        if any(rec.values()):
            out.append(rec)
    return out


def split_list(value):
    """リスト型セルを分解する。セル内改行 → `;` の順で区切る。"""
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"\r?\n", text) if "\n" in text else text.split(LIST_SEPARATOR)
    return [p.strip() for p in parts if p.strip()]


def coerce(records, ledger):
    """スキーマの `type: list` に従ってセルを分解する。他は文字列のまま。"""
    list_fields = {f["name"] for f in ledger["fields"] if f.get("type") == "list"}
    for rec in records:
        for name in list_fields:
            if name in rec:
                rec[name] = split_list(rec[name])
    return records


def parse_notes(path, schema):
    """notes.md から対象名と叙述セクションを取り出す。

    見出しは成果物と同じ `## <番号>. <タイトル>` を使う。番号で対応づけるので、
    タイトルの言い回しが多少ぶれても拾える。
    """
    target, narrative = "", {}
    if not Path(path).is_file():
        return target, narrative
    text = Path(path).read_text(encoding="utf-8-sig")
    by_num = {}
    for sec in schema.get("sections", []):
        src = str(sec.get("from", ""))
        if src.startswith("narrative."):
            by_num[str(sec["num"])] = src.split(".", 1)[1]

    current, buf = None, []
    for line in text.splitlines():
        if line.startswith("# ") and not target:
            head = line[2:].strip()
            target = head.split(":", 1)[1].strip() if ":" in head else head
            continue
        m = _SECTION_HEAD_RE.match(line)
        if m:
            if current:
                narrative[current] = "\n".join(buf).strip("\n")
            current, buf = by_num.get(m.group(1)), []
            continue
        if current:
            buf.append(line)
    if current:
        narrative[current] = "\n".join(buf).strip("\n")
    return target, narrative


def run_mode_of(artifact_dir):
    """run_mode は qa-session.json が持つ(成果物側に二重に書かない)。"""
    session = Path(artifact_dir).parent / "qa-session.json"
    if not session.is_file():
        return ""
    try:
        return str(json.loads(session.read_text(encoding="utf-8")).get("run_mode", "") or "")
    except (OSError, ValueError):
        return ""


def load_artifact(path, schema):
    """成果物ディレクトリを読み、検証・描画が使う dict にする。

    戻り値: (data, errors)。errors は [(where, message)]。
    """
    d = artifact_dir_of(path)
    errors = []
    data = {"meta": {}, "narrative": {}}

    for ledger in ledgers_of(schema):
        key = ledger["key"]
        csv_path = d / "{}.csv".format(key)
        if not csv_path.is_file():
            continue
        try:
            data[key] = coerce(read_table(csv_path), ledger)
        except (OSError, ValueError, csv.Error) as e:
            errors.append(("{}.csv".format(key), "読み込めません: {}".format(e)))

    target, narrative = parse_notes(d / NOTES_FILE, schema)
    data["narrative"] = narrative
    data["meta"] = {"target": target, "run_mode": run_mode_of(d)}
    return data, errors


def field_value(record, field):
    """レコードからフィールド値を取り出す。未設定なら default(なければ "")。"""
    v = record.get(field["name"], "")
    if v in ("", [], None) and "default" in field:
        return field["default"]
    return v


def is_empty(v):
    return v in ("", [], None) or (isinstance(v, str) and not v.strip())


# ---------------------------------------------------------------------------
# ルール
# ---------------------------------------------------------------------------

def rule_unique_ids(result, ledger, records):
    seen = {}
    for idx, rec in enumerate(records, start=1):
        rid = str(rec.get("id", "")).strip()
        if not rid:
            continue
        if rid in seen:
            result.add("ERROR", rid, "unique_ids",
                       "IDが重複しています(初出: {}件目 / 再出: {}件目)"
                       .format(seen[rid], idx))
        else:
            seen[rid] = idx


def rule_id_pattern(result, ledger, records):
    for field in ledger["fields"]:
        pat = field.get("pattern")
        if not pat:
            continue
        rx = re.compile(pat)
        for idx, rec in enumerate(records, start=1):
            v = field_value(rec, field)
            if is_empty(v):
                continue
            for one in (v if isinstance(v, list) else [v]):
                if not rx.match(str(one)):
                    result.add("ERROR", "{}件目".format(idx), "id_pattern",
                               "`{}` の書式が規約外です: 「{}」(期待: {})"
                               .format(field["name"], one, pat))


def rule_required_fields(result, ledger, records):
    for idx, rec in enumerate(records, start=1):
        rid = str(rec.get("id", "")).strip() or "{}件目".format(idx)
        for field in ledger["fields"]:
            if not _truthy(field.get("required", "no")):
                continue
            if is_empty(field_value(rec, field)):
                result.add("ERROR", rid, "required_fields",
                           "必須フィールド `{}`({})が空です"
                           .format(field["name"], field.get("label", field["name"])))


def rule_enum_values(result, ledger, records):
    for idx, rec in enumerate(records, start=1):
        rid = str(rec.get("id", "")).strip() or "{}件目".format(idx)
        for field in ledger["fields"]:
            allowed = field.get("enum")
            if not allowed:
                continue
            v = field_value(rec, field)
            if is_empty(v):
                continue
            for one in (v if isinstance(v, list) else [v]):
                if str(one) not in allowed:
                    result.add("ERROR", rid, "enum_values",
                               "`{}` の値が規約外です: 「{}」(許容: {})"
                               .format(field["name"], one, " / ".join(allowed)))


def rule_explicit_requires_sources(result, ledger, records):
    """conventions.md §5-3: explicit(既定)の項目に sources は必須。"""
    names = {f["name"] for f in ledger["fields"]}
    if "sources" not in names or "derivation" not in names:
        return
    for idx, rec in enumerate(records, start=1):
        rid = str(rec.get("id", "")).strip() or "{}件目".format(idx)
        derivation = str(rec.get("derivation", "") or "explicit").strip()
        if derivation != "explicit":
            continue
        if is_empty(rec.get("sources", "")):
            result.add(
                "ERROR", rid, "explicit_requires_sources",
                "出典(sources)が空です。資料に明記された事実(derivation: explicit)"
                "として書くなら出典が要ります。出典を書けないなら、それは explicit では"
                "なく inferred か proposed です(conventions.md §5-3)")


def rule_no_vague_expected(result, ledger, records):
    targets = [f["name"] for f in ledger["fields"]
               if "期待結果" in f.get("label", "") or f["name"] == "expected"]
    for idx, rec in enumerate(records, start=1):
        rid = str(rec.get("id", "")).strip() or "{}件目".format(idx)
        for name in targets:
            text = str(rec.get(name, "") or "")
            for word in AMBIGUOUS_WORDS:
                if word in text:
                    result.add("WARN", rid, "no_vague_expected",
                               "`{}` に曖昧語「{}」があります。合否判定できる表現"
                               "(具体的な値・状態・件数)にしてください"
                               .format(name, word))
                    break


RULES = {
    "unique_ids": rule_unique_ids,
    "id_pattern": rule_id_pattern,
    "required_fields": rule_required_fields,
    "enum_values": rule_enum_values,
    "explicit_requires_sources": rule_explicit_requires_sources,
    "no_vague_expected": rule_no_vague_expected,
}


# ---------------------------------------------------------------------------
# 検証本体
# ---------------------------------------------------------------------------

def validate(path):
    result = Result(path)
    schema_path = schema_for(path)
    if schema_path is None:
        result.add("INFO", None, "schema",
                   "対応するスキーマがないため検証をスキップしました")
        return result
    result.schema = str(schema_path)

    try:
        schema = miniyaml.load(str(schema_path))
    except (miniyaml.YamlError, OSError) as e:
        result.add("ERROR", None, "schema", "スキーマを読めません: {}".format(e))
        return result

    data, io_errors = load_artifact(path, schema)
    for where, message in io_errors:
        result.add("ERROR", where, "io", message)
    result.artifact = schema.get("artifact")
    if not data.get("meta", {}).get("target"):
        result.add("WARN", NOTES_FILE, "structure",
                   "対象名が読み取れません。`# <タイトル>: <対象>` の見出しを "
                   "notes.md の先頭に書いてください")

    ledgers = ledgers_of(schema)
    if not ledgers:
        result.add("ERROR", None, "schema", "スキーマに台帳(ledgers)の定義がありません")
        return result

    usable = []
    for ledger in ledgers:
        key = ledger["key"]
        records = data.get(key, "")
        optional = _truthy(ledger.get("optional", "no"))
        if is_empty(records):
            if not optional:
                result.add("ERROR", "{}.csv".format(key), "structure",
                           "台帳 `{0}.csv` がありません(または行が空です)".format(key))
            continue

        # 未知のフィールドは警告(綴り間違いの検出。落としはしない)
        known = set()
        for f in ledger["fields"]:
            known.add(f["name"])
        for idx, rec in enumerate(records, start=1):
            rid = str(rec.get("id", "")).strip() or "{}[{}件目]".format(key, idx)
            for k in rec:
                if k not in known:
                    result.add("WARN", rid, "unknown_field",
                               "スキーマにないフィールドです: `{}`(台帳 {})".format(k, key))
        usable.append((ledger, records))

    # 台帳をまたいだID重複も見る(conventions.md §6-1 のIDは成果物内で一意)
    seen_ids = {}
    for ledger, records in usable:
        for rec in records:
            rid = str(rec.get("id", "")).strip()
            if not rid:
                continue
            if rid in seen_ids and seen_ids[rid] != ledger["key"]:
                result.add("ERROR", rid, "unique_ids",
                           "IDが台帳をまたいで重複しています({} と {})"
                           .format(seen_ids[rid], ledger["key"]))
            seen_ids[rid] = ledger["key"]

    # 叙述セクションの欠落は警告(conventions.md §6「該当なしと1行書く」)
    for sec in schema.get("sections", []):
        src = sec.get("from", "")
        if not src.startswith("narrative."):
            continue
        key = src.split(".", 1)[1]
        if is_empty((data.get("narrative") or {}).get(key, "")):
            result.add("WARN", "narrative.{}".format(key), "empty_section",
                       "セクション{}「{}」の本文が空です。検討して該当なしなら"
                       "「該当なし」と1行書いてください(conventions.md §6)"
                       .format(sec.get("num", "?"), sec.get("title", "")))

    for name in schema.get("rules", []):
        fn = RULES.get(name)
        if fn is None:
            result.add("WARN", None, "schema",
                       "未知のルールです: {}(validate_artifact.py に実装がありません)"
                       .format(name))
            continue
        for ledger, records in usable:
            fn(result, ledger, records)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def collect(args, parser):
    if args.session_dir:
        d = Path(args.session_dir)
        if not d.is_dir():
            parser.error("ディレクトリが存在しません: {}".format(d))
        return sorted(str(p) for p in d.iterdir()
                      if p.is_dir() and ARTIFACT_RE.match(p.name))
    missing = [p for p in args.files if not os.path.isdir(p)]
    if missing:
        parser.error("成果物ディレクトリが存在しません: {}".format(", ".join(missing)))
    return args.files


def print_text(results):
    total_e = total_w = 0
    for r in results:
        print("=== {} ===".format(r.path))
        if r.schema:
            print("スキーマ: {}".format(os.path.basename(r.schema)))
        for i in r.issues:
            where = " [{}]".format(i["where"]) if i["where"] else ""
            print("{:<6}{:<28}{}{}".format(i["severity"], i["rule"], where and where + " ", i["message"]))
        if not r.issues:
            print("エラーなし")
        total_e += r.errors
        total_w += r.warnings
        print()
    print("サマリー: {} files, {} errors, {} warnings".format(
        len(results), total_e, total_w))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="validate_artifact.py",
        description=(
            "構造化成果物(YAML)を _shared/schemas/ のスキーマで検証する。"
            "フィールドを直接見るため誤検出しない。"
        ),
        epilog="exit code: 0=エラーなし / 1=エラーあり / 2=使用法エラー。"
               "規約の出典: conventions.md §5・§6-1。",
    )
    parser.add_argument("files", nargs="*",
                        help="検証する成果物ディレクトリ(例 qa-output/s1/30-test-viewpoint)")
    parser.add_argument("--session-dir", help="セッションディレクトリ配下をすべて検証する")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="機械可読JSONで出力する")
    args = parser.parse_args(argv)
    if not args.files and not args.session_dir:
        parser.error("検証するファイルまたは --session-dir を指定してください")
    if args.files and args.session_dir:
        parser.error("--session-dir とファイル指定は同時に使えません")

    targets = collect(args, parser)
    results = [validate(p) for p in targets]

    if args.as_json:
        print(json.dumps({
            "files": [{"path": r.path, "artifact": r.artifact, "schema": r.schema,
                       "errors": r.errors, "warnings": r.warnings,
                       "issues": r.issues} for r in results],
            "summary": {"files": len(results),
                        "errors": sum(r.errors for r in results),
                        "warnings": sum(r.warnings for r in results)},
            "note": "スキーマ検証(機械チェック)。内容の質は判定しない",
        }, ensure_ascii=False, indent=2))
    else:
        print_text(results)
    return 1 if any(r.errors for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
