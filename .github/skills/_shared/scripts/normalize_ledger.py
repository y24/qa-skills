#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台帳CSVの正規化(エスケープされた改行を実改行に戻す)。

台帳では、手順のように「1件が複数行を持つ」列を**セル内改行**で持つ
(conventions.md §6-2)。ところがAIツールがCSVを書き出すとき、この改行が
`&#10;`(数値文字参照)のまま残ることがある。そうなると表計算で1行に潰れて
読めないうえ、`render_md.py` も改行として扱えない(リスト型セルの区切りは
実改行か `;`)。

**CSVを書いた直後に一度かける後始末**であり、判断を伴わない定型処理:

    &#10; / &#xA;      → 実改行(LF)
    &#13; / &#xD;      → CR。セル内の改行は LF に揃える(CRLF → LF)
    セル前後の空白      → 除去(検証も描画もどのみち strip して読む)
    全セルが空の行      → 削除(ヘッダ行は残す)
    文字コード・行終端  → BOM付きUTF-8 + CRLF(元が cp932 ならcp932のまま)

`<br>` と `\\n`(バックスラッシュ+n の2文字)は**変換しない**。QAの台帳では
HTMLタグや制御文字の表記そのものがテストデータになりうる(`<br>` を入力する
画面のテストケースなど)ため、機械的に改行へ倒すとデータを壊す。`&#10;` という
文字列自体をセルに入れたいときは `&amp;#10;` と書く(この形は変換されない)。

かけ忘れは検出される: `&#10;` が残った台帳は `validate_artifact.py` が
`escaped_newline` でエラーにする(hook・CI からも同じ判定が走る)。

使用例:
    python normalize_ledger.py qa-output/s1/31-test-case             # 成果物ディレクトリ
    python normalize_ledger.py qa-output/s1/31-test-case/cases.csv   # ファイル指定
    python normalize_ledger.py --session-dir qa-output/s1            # セッション配下すべて
    python normalize_ledger.py --session-dir qa-output/s1 --check    # 書き換えず検出のみ

exit code:
    0 = 正規化した / 正規化不要
    1 = (--check)要正規化のファイルがある、または読み書きできないファイルがある
    2 = 使用法エラー
"""

import argparse
import csv
import io
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# セル内改行が数値文字参照のまま残ったもの。10進・16進・ゼロ詰めのどれも拾う
ESCAPED_LF_RE = re.compile(r"&#(?:0*10|[xX]0*[aA]);")
ESCAPED_CR_RE = re.compile(r"&#(?:0*13|[xX]0*[dD]);")

# 出力の既定。QAの現場は台帳を表計算で開くので、Excel がそのまま読める形に揃える
ROW_TERMINATOR = "\r\n"


def has_escaped_newline(text):
    """セルにエスケープされた改行が残っているか(validate_artifact から使う)。"""
    s = str(text or "")
    return bool(ESCAPED_LF_RE.search(s) or ESCAPED_CR_RE.search(s))


def normalize_cell(text):
    """セル1つ分を正規化する。行頭の空白は残す(手順の字下げを壊さないため)。"""
    s = str(text or "")
    s = ESCAPED_LF_RE.sub("\n", s)
    s = ESCAPED_CR_RE.sub("\r", s)
    s = re.sub(r"\r\n?", "\n", s)
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    return s.strip()


def read_csv_rows(path):
    """CSVを行のリストで読む。(rows, encoding)。Excel が書く cp932 も読む。"""
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("文字コードを判別できません(UTF-8 / cp932 のいずれでもない)")
    return list(csv.reader(io.StringIO(text, newline=""))), encoding


def normalize_rows(rows):
    """(正規化後の行, 変換したセル数, 削除した空行数) を返す。"""
    out, converted, dropped = [], 0, 0
    for row in rows:
        cells = []
        for value in row:
            if has_escaped_newline(value):
                converted += 1
            cells.append(normalize_cell(value))
        if out and not any(cells):
            dropped += 1
            continue
        out.append(cells)
    return out, converted, dropped


def to_bytes(rows, encoding):
    buf = io.StringIO(newline="")
    csv.writer(buf, lineterminator=ROW_TERMINATOR).writerows(rows)
    return buf.getvalue().encode(encoding)


def process(path, check=False):
    """CSV1枚を処理する。(status, message) を返す。"""
    try:
        rows, encoding = read_csv_rows(path)
    except (OSError, ValueError, csv.Error) as e:
        return "error", "読み込めません: {}".format(e)
    if not rows:
        return "ok", "空のファイル"

    normalized, converted, dropped = normalize_rows(rows)
    try:
        new = to_bytes(normalized, encoding)
        old = Path(path).read_bytes()
    except (OSError, UnicodeEncodeError) as e:
        return "error", "書き出せません: {}".format(e)
    if new == old:
        return "ok", "変更なし"

    detail = []
    if converted:
        detail.append("改行エスケープ {}セル".format(converted))
    if dropped:
        detail.append("空行 {}行".format(dropped))
    if not detail:
        detail.append("書式(文字コード・行終端・前後の空白)")
    message = " / ".join(detail)

    if check:
        return "needs", message
    try:
        Path(path).write_bytes(new)
    except OSError as e:
        return "error", "書き出せません: {}".format(e)
    return "normalized", message


def collect(args, parser):
    """対象の台帳CSVを集める。ディレクトリ指定はその直下の *.csv。"""
    if args.session_dir:
        d = Path(args.session_dir)
        if not d.is_dir():
            parser.error("ディレクトリが存在しません: {}".format(d))
        return [str(p) for p in sorted(d.glob("*/*.csv"))]

    targets = []
    for name in args.files:
        p = Path(name)
        if p.is_dir():
            targets.extend(sorted(p.glob("*.csv")))
        elif p.is_file():
            targets.append(p)
        else:
            parser.error("ファイルまたはディレクトリが存在しません: {}".format(name))
    return [str(p) for p in targets]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="normalize_ledger.py",
        description=(
            "台帳CSVを正規化する。セル内改行が `&#10;` のまま書き出されたものを"
            "実改行に戻し、表計算でそのまま読める形に揃える(conventions.md §6-2)。"
        ),
        epilog="exit code: 0=正規化した/不要 / 1=(--check)要正規化・読み書き失敗 / 2=使用法エラー。",
    )
    parser.add_argument("files", nargs="*",
                        help="成果物ディレクトリまたはCSV(例 qa-output/s1/31-test-case)")
    parser.add_argument("--session-dir", help="セッションディレクトリ配下の台帳をすべて対象にする")
    parser.add_argument("--check", action="store_true",
                        help="書き換えず、正規化が要るファイルだけを検出する")
    args = parser.parse_args(argv)
    if not args.files and not args.session_dir:
        parser.error("対象ファイルまたは --session-dir を指定してください")
    if args.files and args.session_dir:
        parser.error("--session-dir とファイル指定は同時に使えません")

    targets = collect(args, parser)
    if not targets:
        print("台帳CSVがありません(この成果物は Markdown 直書きです)")
        return 0

    failed = False
    for path in targets:
        status, message = process(path, args.check)
        name = Path(path).name
        if status == "normalized":
            print("正規化: {} ({})".format(name, message))
        elif status == "ok":
            print("変更なし: {}".format(name))
        elif status == "needs":
            print("要正規化: {} ({})".format(name, message))
            failed = True
        else:
            print("エラー: {} ({})".format(name, message))
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
