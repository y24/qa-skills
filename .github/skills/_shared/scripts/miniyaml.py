#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""限定サブセットのYAMLパーサー(標準ライブラリのみ)。

QA成果物の構造化データ(観点一覧・テストケース等)とスキーマを読むために使う。
`defect_stats.py` が内蔵していたパーサーを抽出し、ネストとブロックスカラーに
対応させたもの。**PyYAML を要求しない**という制約([README](README.md))と
YAML を両立させるための土台。

## 最重要の不変条件: 真のYAMLの厳密なサブセットであること

**このパーサーが受理するものは、必ず本物のYAMLパーサーでも同じ意味で読める。**
逆(YAMLでは有効だがここでは読めない)は許す。この向きを守ることで、成果物が
将来どんなYAMLツールからでも読めることを保証する。CI では PyYAML との
差分テストでこの不変条件を検査している。

そのため、YAMLが誤りとする書き方は**受理せずエラーにする**。特に:

    viewpoint: 申請できないこと: 補足    ← エラー(本物のYAMLでも誤り)
    viewpoint: "申請できないこと: 補足"  ← 正しい書き方

## 対応する構文

    key: value                  マッピング
    key:                        ネストしたマッピング / シーケンス
      nested: value
    - item                      シーケンス(スカラー項目)
    - key: value                シーケンス(マッピング項目)。継続行も可
      key2: value2
    key: [a, b, c]              インラインシーケンス(スカラーのみ)
    key: |                      ブロックスカラー(改行を保持)
      複数行の
      テキスト
    key: >                      ブロックスカラー(改行を空白に畳む)
    key: |-  /  |+              チョンピング指定
    "..." / '...'               引用符付きスカラー
    # comment                   コメント(行全体・行末)
    ---                         ドキュメント区切り(1つ目のみ。複数文書は非対応)

## 対応しない構文(いずれも明確なエラーにする)

    アンカー・エイリアス(&x / *x)、タグ(!!str)、フローマッピング({a: 1})、
    複数ドキュメント、タブインデント、複雑キー(? )

## 型

スカラーは**すべて文字列**として返す(`true` / `123` も文字列)。QA成果物では
IDや日本語テキストしか扱わず、型推論はかえって事故のもとになるため。
真偽・数値が要るときは呼び出し側で変換する。

使用例:
    import miniyaml
    data = miniyaml.parse(open("30-test-viewpoint.yaml", encoding="utf-8").read())
    records = miniyaml.parse_records(text)   # list of dict であることを保証する
"""

import re
import sys

__all__ = ["YamlError", "parse", "parse_records", "load", "load_records"]


class YamlError(Exception):
    """YAMLとして解釈できない、または対応していない構文。"""


_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.\-]*)[ \t]*:(?:[ \t]+(.*))?$")
_BLOCK_RE = re.compile(r"^([|>])([-+]?)$")
_RESERVED_START = ("&", "*", "!", "%", "@", "`", "{", "?")


def _err(lineno, msg):
    raise YamlError("{}行目: {}".format(lineno, msg))


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
    """スカラー1つを文字列として返す。YAMLが誤りとする書き方はエラーにする。"""
    raw = raw.strip()
    if raw == "":
        return ""
    if raw[0] == '"':
        if len(raw) < 2 or raw[-1] != '"':
            _err(lineno, '二重引用符が閉じていません: {}'.format(raw))
        try:
            import json
            return json.loads(raw)
        except ValueError:
            _err(lineno, "二重引用符付き文字列を解釈できません: {}".format(raw))
    if raw[0] == "'":
        if len(raw) < 2 or raw[-1] != "'":
            _err(lineno, "単一引用符が閉じていません: {}".format(raw))
        return raw[1:-1].replace("''", "'")
    if raw[0] in _RESERVED_START:
        _err(lineno,
             "`{}` で始まる値には対応していません(アンカー・タグ・フローマッピング等)。"
             "文字どおりの値なら引用符で囲んでください: {}".format(raw[0], raw))
    # 真のYAMLのサブセットを保つ: プレーンスカラー中の `: ` と末尾の `:` は
    # 本物のYAMLでもマッピングと解釈されて壊れる
    if ": " in raw or raw.endswith(":"):
        _err(lineno,
             "プレーンな値に `:` を含めることはできません(本物のYAMLでも誤りになります)。"
             '引用符で囲んでください → "{}"'.format(raw.replace('"', '\\"')))
    return raw


def _parse_inline_seq(raw, lineno):
    if not raw.endswith("]"):
        _err(lineno, "インラインシーケンスが `]` で閉じていません: {}".format(raw))
    inner = raw[1:-1].strip()
    if "[" in inner or "{" in inner:
        _err(lineno, "ネストしたインラインシーケンス/マッピングには対応していません: {}".format(raw))
    if inner == "":
        return []
    return [_parse_scalar(p, lineno) for p in inner.split(",")]


def _parse_value(raw, lineno):
    """`key: <ここ>` の値部分を解釈する(ブロックスカラーは呼び出し側で処理)。"""
    raw = _strip_comment(raw or "").strip()
    if raw == "":
        return ""
    if raw.startswith("["):
        return _parse_inline_seq(raw, lineno)
    return _parse_scalar(raw, lineno)


class _Reader:
    """インデントで再帰下降するための行カーソル。"""

    def __init__(self, text):
        self.raw = text.splitlines()
        self.i = 0
        self._seen_content = False

    # --- 位置操作 -----------------------------------------------------

    def _significant(self, idx):
        """idx 行が意味のある行か。空行・コメント行・`---` は違う。"""
        line = self.raw[idx]
        s = line.strip()
        if not s or s.startswith("#"):
            return False
        if s == "---":
            # `---` は本文が始まる前にだけ許す。本文の途中に現れたら2つ目の
            # ドキュメントであり、黙って1つに混ぜてはならない
            if self._seen_content:
                _err(idx + 1, "複数ドキュメント(本文の途中の `---`)には対応していません")
            return False
        if s == "...":
            return False
        return True

    def cur(self):
        """現在の意味のある行 (lineno, indent, content) を返す。無ければ None。"""
        while self.i < len(self.raw):
            if self._significant(self.i):
                line = self.raw[self.i].rstrip()
                lead = line[: len(line) - len(line.lstrip())]
                if "\t" in lead:
                    _err(self.i + 1, "インデントにタブは使えません(空白を使ってください)")
                self._seen_content = True
                return self.i + 1, len(lead), line.strip()
            self.i += 1
        return None

    def advance(self):
        self.i += 1

    # --- ブロックスカラー ---------------------------------------------

    def read_block_scalar(self, key_indent, style, chomp, lineno):
        """`key: |` の続きを読む。key_indent より深い行がブロック本体。"""
        self.advance()
        body = []
        block_indent = None
        while self.i < len(self.raw):
            line = self.raw[self.i].rstrip("\n").rstrip()
            if line.strip() == "":
                body.append("")
                self.i += 1
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= key_indent:
                break
            if block_indent is None:
                block_indent = indent
            if indent < block_indent:
                break
            body.append(line[block_indent:])
            self.i += 1
        while body and body[-1] == "":
            body.pop()
        if not body:
            return ""
        if style == "|":
            text = "\n".join(body)
        else:
            # `>` の畳み込み: 連続する k 個の改行は k-1 個の改行になる
            # (段落内の単独の改行は空白1つに畳まれる)。日本語では語間に
            # 空白が入ってしまうため、散文には `|` を使うこと
            parts, buf, blanks = [], [], 0
            for ln in body:
                if ln == "":
                    if buf:
                        parts.append(" ".join(buf))
                        buf = []
                    blanks += 1
                    continue
                if blanks:
                    parts.append("\n" * blanks)
                    blanks = 0
                buf.append(ln)
            if buf:
                parts.append(" ".join(buf))
            text = ""
            for p in parts:
                if p.startswith("\n"):
                    text += p
                elif text and not text.endswith("\n"):
                    text += " " + p
                else:
                    text += p
        if chomp == "-":
            return text
        if chomp == "+":
            return text + "\n"
        return text + "\n"

    # --- ノード --------------------------------------------------------

    def parse_node(self, indent):
        c = self.cur()
        if c is None:
            return ""
        lineno, cur_indent, content = c
        if cur_indent < indent:
            return ""
        if content == "-" or content.startswith("- "):
            return self.parse_seq(cur_indent)
        return self.parse_map(cur_indent)

    def parse_seq(self, indent):
        items = []
        while True:
            c = self.cur()
            if c is None:
                break
            lineno, cur_indent, content = c
            if cur_indent != indent:
                if cur_indent < indent:
                    break
                _err(lineno, "シーケンス項目のインデントが揃っていません"
                             "(期待: {} 桁 / 実際: {} 桁)".format(indent, cur_indent))
            if not (content == "-" or content.startswith("- ")):
                break

            line = self.raw[self.i]
            dash_at = line.index("-", indent)
            rest = line[dash_at + 1:]
            if rest.strip() == "":
                # `-` だけの行。次の意味のある行が項目の中身
                self.advance()
                nxt = self.cur()
                if nxt is None or nxt[1] <= indent:
                    items.append("")
                    continue
                items.append(self.parse_node(nxt[1]))
                continue

            # `- key: value` / `- スカラー`。`-` を空白に置換して同じ列で読み直す
            item_indent = dash_at + 1 + (len(rest) - len(rest.lstrip()))
            body = rest.strip()
            if _KEY_RE.match(_strip_comment(body)):
                self.raw[self.i] = line[:dash_at] + " " + line[dash_at + 1:]
                items.append(self.parse_map(item_indent))
            else:
                items.append(_parse_value(body, lineno))
                self.advance()
        return items

    def parse_map(self, indent):
        mapping = {}
        while True:
            c = self.cur()
            if c is None:
                break
            lineno, cur_indent, content = c
            if cur_indent < indent:
                break
            if cur_indent > indent:
                _err(lineno, "予期しないインデントです"
                             "(期待: {} 桁 / 実際: {} 桁)".format(indent, cur_indent))
            if content.startswith("- "):
                break
            m = _KEY_RE.match(content)
            if not m:
                _err(lineno, "`key: value` として解釈できません: {}".format(content))
            key = m.group(1)
            if key in mapping:
                _err(lineno, "キーが重複しています: {}".format(key))
            rawval = _strip_comment(m.group(2) or "").strip()

            bm = _BLOCK_RE.match(rawval)
            if bm:
                mapping[key] = self.read_block_scalar(
                    indent, bm.group(1), bm.group(2), lineno)
                continue
            if rawval != "":
                mapping[key] = _parse_value(rawval, lineno)
                self.advance()
                continue

            # 値なし → ネストしたブロックか空
            self.advance()
            nxt = self.cur()
            if nxt is None or nxt[1] <= indent:
                mapping[key] = ""
            else:
                mapping[key] = self.parse_node(nxt[1])
        return mapping


def parse(text):
    """限定サブセットのYAMLを dict / list / str に解釈する。"""
    reader = _Reader(text)
    c = reader.cur()
    if c is None:
        return {}
    value = reader.parse_node(c[1])
    trailing = reader.cur()
    if trailing is not None:
        _err(trailing[0], "解釈できない残りの行があります: {}".format(trailing[2]))
    return value


def parse_records(text):
    """`- key: value` の並び(list of dict)であることを保証して返す。"""
    data = parse(text)
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise YamlError("トップレベルは `- key: value` のリストである必要があります")
    return data


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load(path):
    """ファイルを読んで parse する。`.json` は json として読む。"""
    if path.lower().endswith(".json"):
        import json
        return json.loads(_read(path))
    return parse(_read(path))


def load_records(path):
    if path.lower().endswith(".json"):
        import json
        data = json.loads(_read(path))
        if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
            raise YamlError("JSONは list of objects 形式である必要があります")
        return data
    return parse_records(_read(path))


def _main(argv):
    """デバッグ用: ファイルを解釈して JSON で出力する。"""
    import argparse
    import json
    parser = argparse.ArgumentParser(
        prog="miniyaml.py",
        description="限定サブセットのYAMLを解釈して JSON で出力する(デバッグ用)。",
        epilog="真のYAMLの厳密なサブセット。受理したものは本物のYAMLパーサーでも同じ意味で読める。",
    )
    parser.add_argument("file", help="読み込むYAMLファイル")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(load(args.file), ensure_ascii=False, indent=2))
    except YamlError as e:
        print("YAMLを解釈できません({}): {}".format(args.file, e), file=sys.stderr)
        return 1
    except OSError as e:
        print("ファイルを読み込めません: {}".format(e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    sys.exit(_main(sys.argv[1:]))
