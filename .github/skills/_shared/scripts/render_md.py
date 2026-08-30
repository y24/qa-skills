#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""構造化成果物(YAML)から人間向け Markdown を生成する。

**台帳はYAMLが正、Markdown は生成物**という運用の後半を担う。ゲートで人間が
読むのは常に Markdown であり、YAML を人に見せない。

## なぜレンダラを挟むのか

conventions.md §5-3 は「`derivation: proposed` の項目を explicit / inferred と
同じ表に混ぜてはならない」と定めている。これはこのスキルセットで**最も重い
違反**だが、これまでは散文の指示でしかなく、守ったかどうかは目視だった。

YAML では `derivation` はただのフィールドなので、**レンダラが機械的に別表へ
出す**。混ぜること自体ができなくなる — 規約が構造的な保証になる。

## 使い方

    python render_md.py qa-output/s1/30-test-viewpoint.yaml            # .md を生成
    python render_md.py --session-dir qa-output/s1                     # まとめて生成
    python render_md.py --session-dir qa-output/s1 --check             # ずれの検出のみ

`--check` は既存の Markdown が YAML から生成される内容と一致するかを見る。
一致しない場合は**Markdown が直接編集された**か、YAML を変えて再生成していない。
どちらも「YAMLが正」の前提が壊れているので検出する(hook と CI から呼ばれる)。

exit code:
    0 = 生成成功 / (--check)ずれなし
    1 = (--check)ずれあり、または生成できない成果物があった
    2 = 使用法エラー
"""

import argparse
import difflib
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
import validate_artifact  # noqa: E402
from validate_artifact import ARTIFACT_RE, schema_for  # noqa: E402

GENERATED_NOTE = (
    "<!-- このファイルは {src} から render_md.py が生成した。"
    "直接編集しない(編集は YAML 側に行い、再生成する)。 -->"
)

QUICK_NOTE_PREFIX = "> ⚠️"

TRUE_VALUES = ("yes", "true", "on", "1")


def _truthy(v):
    return str(v).strip().lower() in TRUE_VALUES


def cell(value, join=", "):
    """表のセル1つ分の文字列にする。`|` と改行が表を壊さないようにする。"""
    if isinstance(value, list):
        value = join.join(str(v) for v in value)
    text = str(value if value is not None else "").strip()
    if not text:
        return "-"
    text = text.replace("|", "\\|")
    text = re.sub(r"\r?\n", "<br>", text)
    return text


def visible_fields(ledger):
    return [f for f in ledger["fields"]
            if str(f.get("render", "yes")).strip().lower() != "no"]


def render_table(fields, records):
    header = "| " + " | ".join(f.get("label", f["name"]) for f in fields) + " |"
    sep = "|" + "|".join("---" for _ in fields) + "|"
    lines = [header, sep]
    for rec in records:
        cells = [cell(rec.get(f["name"], ""), f.get("join", ", ")) for f in fields]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def is_proposed(rec):
    return str(rec.get("derivation", "") or "explicit") == "proposed"


def _proposed_heading(level="###"):
    return [
        "",
        "{} 要件外提案(AIが資料外から補った項目 — 採否はユーザーが判断する)".format(level),
        "",
        "以下は**インプット資料に根拠がない**。過去障害・ドメイン知識・リスク分析から"
        "導いた提案であり、上とは出所が違う(conventions.md §5-3)。",
        "",
    ]


def select(records, filt):
    """セクションの filter に従ってレコードを絞る。

    `not_proposed` / `proposed` は、提案を独立した節に持つ成果物
    (業務シナリオの「## 3. 提案シナリオ」など)のためのもの。
    filter が無い場合は1つの節の中で本表と別表に分ける。
    """
    if filt == "proposed":
        return [r for r in records if is_proposed(r)], False
    if filt == "not_proposed":
        return [r for r in records if not is_proposed(r)], False
    return records, True


def render_ledger(ledger, data, filt=None):
    """台帳セクション(表)。proposed は必ず別表に分ける(conventions.md §5-3)。"""
    records, split = select(data.get(ledger["key"]) or [], filt)
    fields = visible_fields(ledger)
    if not split:
        return render_table(fields, records) if records else "該当なし"

    main = [r for r in records if not is_proposed(r)]
    proposed = [r for r in records if is_proposed(r)]
    out = [render_table(fields, main) if main else "該当なし"]
    if proposed:
        out.extend(_proposed_heading())
        out.append(render_table(fields, proposed))
    return "\n".join(out)


def render_detail(ledger, data, filt=None):
    """詳細セクション。1レコードを見出し+項目の並びとして展開する。

    シナリオ詳細のように、1件ごとに手順表や複数の属性を持つ台帳のためのもの。
    ここでも proposed は別見出しに分ける。
    """
    records, split = select(data.get(ledger["key"]) or [], filt)
    if not records:
        return "該当なし"
    main = [r for r in records if not is_proposed(r)] if split else records
    proposed = [r for r in records if is_proposed(r)] if split else []

    def one(rec):
        rid = str(rec.get("id", "")).strip()
        title = str(rec.get(ledger.get("detail_title", "title"), "")).strip()
        head = "### {}{}".format(rid, ": " + title if title else "")
        lines = [head, ""]
        for f in ledger["fields"]:
            if str(f.get("detail", "yes")).strip().lower() == "no":
                continue
            name = f["name"]
            if name in ("id", ledger.get("detail_title", "title")):
                continue
            v = rec.get(name, "")
            if v in ("", [], None):
                continue
            label = f.get("label", name)
            if f.get("type") == "table" and isinstance(v, list) and v and isinstance(v[0], dict):
                lines.append("- **{}**:".format(label))
                lines.append("")
                sub = render_table(f.get("fields", []), v)
                lines.extend("  " + ln for ln in sub.splitlines())
                lines.append("")
            elif isinstance(v, str) and "\n" in v.strip():
                lines.append("- **{}**:".format(label))
                lines.append("")
                lines.extend("  " + ln for ln in v.rstrip("\n").splitlines())
                lines.append("")
            else:
                lines.append("- **{}**: {}".format(label, cell(v, f.get("join", ", "))))
        return "\n".join(lines)

    out = [one(r) for r in main] if main else ["該当なし"]
    if proposed:
        out.append("\n".join(_proposed_heading("###")))
        out.extend(one(r) for r in proposed)
    return "\n\n".join(out)


def render(schema, data, src_name):
    target = (data.get("meta") or {}).get("target", "") or "(対象未設定)"
    run_mode = str((data.get("meta") or {}).get("run_mode", "") or "").strip()
    narrative = data.get("narrative") or {}

    lines = ["# {}: {}".format(schema.get("title", schema["artifact"]), target), ""]
    lines.append(GENERATED_NOTE.format(src=src_name))
    lines.append("")
    if run_mode:
        lines.append("> 実行モード: {}".format(run_mode))
        if run_mode == "quick" and schema.get("mode_note"):
            for ln in schema["mode_note"].rstrip("\n").splitlines():
                lines.append("{} {}".format(QUICK_NOTE_PREFIX, ln.strip())
                             if not ln.startswith("⚠️") else "> {}".format(ln.strip()))
        lines.append("")

    by_key = {l["key"]: l for l in validate_artifact.ledgers_of(schema)}
    for sec in schema.get("sections", []):
        lines.append("## {}. {}".format(sec["num"], sec["title"]))
        lines.append("")
        intro = str(sec.get("intro", "") or "")
        if intro:
            body_intro = str(narrative.get(intro.split(".", 1)[-1], "") or "").rstrip("\n")
            if body_intro.strip():
                lines.append(body_intro)
                lines.append("")
        src = str(sec.get("from", ""))
        filt = str(sec.get("filter", "") or "") or None
        kind, _, key = src.partition(".")
        if kind == "ledger":
            ledger = by_key.get(key)
            body = render_ledger(ledger, data, filt) if ledger else "(スキーマに台帳 {} がありません)".format(key)
        elif kind == "detail":
            ledger = by_key.get(key)
            body = render_detail(ledger, data, filt) if ledger else "(スキーマに台帳 {} がありません)".format(key)
        else:
            body = str(narrative.get(key or src, "") or "").rstrip("\n")
            if not body.strip():
                body = "該当なし"
        lines.append(body)
        lines.append("")

    text = "\n".join(lines).rstrip("\n") + "\n"
    return re.sub(r"\n{3,}", "\n\n", text)


def md_path_for(yaml_path):
    p = Path(yaml_path)
    return p.with_suffix(".md")


def process(yaml_path, check):
    """1ファイルを処理する。(status, message) を返す。"""
    schema_path = schema_for(yaml_path)
    if schema_path is None:
        return "skipped", "対応するスキーマがありません"
    try:
        schema = miniyaml.load(str(schema_path))
        with open(yaml_path, encoding="utf-8") as f:
            data = miniyaml.parse(f.read())
    except (miniyaml.YamlError, OSError) as e:
        return "error", "読み込めません: {}".format(e)
    if not isinstance(data, dict):
        return "error", "トップレベルはマッピングである必要があります"

    text = render(schema, data, os.path.basename(str(yaml_path)))
    out = md_path_for(yaml_path)

    if not check:
        try:
            with open(out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except OSError as e:
            return "error", "書き出せません: {}".format(e)
        return "written", str(out)

    if not out.is_file():
        return "drift", "{} がまだ生成されていません(render_md.py を実行してください)".format(out.name)
    try:
        with open(out, encoding="utf-8") as f:
            current = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return "error", "既存の Markdown を読めません: {}".format(e)
    if current.replace("\r\n", "\n") == text:
        return "ok", str(out)
    diff = list(difflib.unified_diff(
        current.replace("\r\n", "\n").splitlines(),
        text.splitlines(),
        fromfile="{}(現在)".format(out.name),
        tofile="{}(YAMLから生成)".format(out.name),
        lineterm="", n=1))
    head = "\n".join(diff[:24])
    if len(diff) > 24:
        head += "\n... ほか {} 行".format(len(diff) - 24)
    return "drift", (
        "Markdown が YAML と一致しません。`render_md.py` で再生成してください"
        "(Markdown は生成物。直したいことがあれば YAML 側を編集する)。\n" + head)


def collect(args, parser):
    if args.session_dir:
        d = Path(args.session_dir)
        if not d.is_dir():
            parser.error("ディレクトリが存在しません: {}".format(d))
        return sorted(str(p) for p in d.iterdir()
                      if p.is_file() and ARTIFACT_RE.match(p.name))
    missing = [p for p in args.files if not os.path.isfile(p)]
    if missing:
        parser.error("ファイルが存在しません: {}".format(", ".join(missing)))
    return args.files


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="render_md.py",
        description=(
            "構造化成果物(YAML)から人間向け Markdown を生成する。"
            "derivation: proposed の項目は機械的に別表へ分けられる(conventions.md §5-3)。"
        ),
        epilog="exit code: 0=成功/ずれなし / 1=ずれあり・生成失敗 / 2=使用法エラー。",
    )
    parser.add_argument("files", nargs="*", help="対象の成果物 .yaml")
    parser.add_argument("--session-dir", help="セッションディレクトリ配下をすべて対象にする")
    parser.add_argument("--check", action="store_true",
                        help="生成せず、既存の Markdown とのずれだけを検出する")
    args = parser.parse_args(argv)
    if not args.files and not args.session_dir:
        parser.error("対象ファイルまたは --session-dir を指定してください")
    if args.files and args.session_dir:
        parser.error("--session-dir とファイル指定は同時に使えません")

    targets = collect(args, parser)
    if not targets:
        print("対象の .yaml がありません(構造化されていないセッションです)")
        return 0

    failed = False
    for path in targets:
        status, msg = process(path, args.check)
        name = os.path.basename(path)
        if status == "written":
            print("生成: {} → {}".format(name, os.path.basename(msg)))
        elif status == "ok":
            print("一致: {}".format(os.path.basename(msg)))
        elif status == "skipped":
            print("スキップ: {} ({})".format(name, msg))
        elif status == "drift":
            print("ずれ: {}\n  {}".format(name, msg.replace("\n", "\n  ")))
            failed = True
        else:
            print("エラー: {} ({})".format(name, msg))
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
