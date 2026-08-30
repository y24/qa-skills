#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hook 配線の整合チェック(Copilot 用と Claude Code 用がずれていないか)。

hook の設定ファイルは**形式が違うため2つある**(hooks.md §3)。同じことを2箇所に
書く以上、ずれる。ずれると片方の環境でだけゲートが効かなくなり、しかも**静かに**
効かなくなる。それを機械で防ぐためのチェック。

検査項目:
    1. 両ファイルが同じイベント集合を配線しているか
    2. 各イベントで同じ (action, フラグ) を呼んでいるか
       — 片方だけ --warn-only を外す事故が最も起きやすい
    3. すべての action が hook_entry.py に実在するか
    4. 参照しているスクリプトが実在するか
    5. Copilot 側の各ハンドラにクロスプラットフォームの `command` があるか
    6. VS Code が .claude/settings.json を二重に読まない設定になっているか

使用例:
    python .github/hooks/check_hooks_config.py            # リポジトリルートで実行
    python .github/hooks/check_hooks_config.py --root .

exit code: 0=整合 / 1=不整合 / 2=ファイルが見つからない
"""

import argparse
import json
import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

COPILOT = ".github/hooks/qa-quality-gates.json"
CLAUDE = ".claude/settings.json"
VSCODE = ".vscode/settings.json"
ENTRY = ".github/skills/_shared/scripts/hook_entry.py"

# `hook_entry.py <action> [--flag ...]` を設定ファイルのコマンド文字列から拾う
CMD_RE = re.compile(r"hook_entry\.py\"?\s+([a-z][a-z\-]*)((?:\s+--[a-z\-]+)*)")
SCRIPT_REF_RE = re.compile(r"[.\w/${}]*\.github/skills/_shared/scripts/[\w.]+")


def load_json(path, allow_line_comments=False):
    text = open(path, encoding="utf-8").read()
    if allow_line_comments:
        # .vscode/settings.json は JSONC(行コメントを許す)
        text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    return json.loads(text)


def invocations(commands, errs, label):
    """コマンド文字列の集合から (action, フラグtuple) の集合を作る。"""
    out = set()
    for c in commands:
        m = CMD_RE.search(c or "")
        if not m:
            errs.append("{}: コマンドから action を読み取れません: {}".format(label, c))
            continue
        out.add((m.group(1), tuple(sorted(m.group(2).split()))))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="check_hooks_config.py",
        description="hook 配線(Copilot 用 / Claude Code 用)の整合を検査する。",
        epilog="定義元: .github/skills/_shared/hooks.md。exit code: 0=整合 / 1=不整合 / 2=ファイル不足。",
    )
    parser.add_argument("--root", default=".", help="リポジトリルート(既定: カレント)")
    args = parser.parse_args(argv)
    root = args.root

    paths = {"Copilot": COPILOT, "Claude Code": CLAUDE, "VS Code": VSCODE,
             "hook_entry": ENTRY}
    missing = [
        "{} ({})".format(p, label)
        for label, p in paths.items()
        if not os.path.isfile(os.path.join(root, p))
    ]
    if missing:
        for m in missing:
            print("エラー: ファイルがありません: {}".format(m), file=sys.stderr)
        return 2

    errs = []
    cop = load_json(os.path.join(root, COPILOT))
    cla = load_json(os.path.join(root, CLAUDE))
    vsc = load_json(os.path.join(root, VSCODE), allow_line_comments=True)
    entry_src = open(os.path.join(root, ENTRY), encoding="utf-8").read()

    m = re.search(r"ACTIONS = \{(.*?)\n\}", entry_src, re.S)
    valid_actions = set(re.findall(r'"([a-z][a-z\-]*)":', m.group(1))) if m else set()
    if not valid_actions:
        errs.append("hook_entry.py の ACTIONS を読み取れませんでした")

    # --- Copilot: イベント -> ハンドラの平坦な配列 ---
    cop_map = {}
    for ev, handlers in (cop.get("hooks") or {}).items():
        cmds = []
        for h in handlers:
            if "command" not in h:
                errs.append(
                    "Copilot {}: クロスプラットフォームの `command` がありません"
                    "(bash/linux/osx/windows だけでは未知のホストで動かない)".format(ev))
            for k in ("command", "bash", "linux", "osx", "windows"):
                if k in h:
                    cmds.append(h[k])
        cop_map[ev] = invocations(cmds, errs, "Copilot " + ev)

    # --- Claude Code: イベント -> {matcher, hooks: [...]} の配列(入れ子) ---
    cla_map = {}
    for ev, groups in (cla.get("hooks") or {}).items():
        cmds = []
        for g in groups:
            if "hooks" not in g:
                errs.append(
                    "Claude {}: 入れ子の `hooks` 配列がありません"
                    "(Copilot の平坦な形式と取り違えている可能性)".format(ev))
                continue
            for h in g["hooks"]:
                cmds.append(h.get("command", ""))
        cla_map[ev] = invocations(cmds, errs, "Claude " + ev)

    # 1. イベント集合
    if set(cop_map) != set(cla_map):
        only_cop = sorted(set(cop_map) - set(cla_map))
        only_cla = sorted(set(cla_map) - set(cop_map))
        errs.append("イベント集合が不一致: Copilot にだけある={} / Claude にだけある={}"
                    .format(only_cop or "なし", only_cla or "なし"))

    # 2. 各イベントの呼び出し
    for ev in sorted(set(cop_map) & set(cla_map)):
        if cop_map[ev] != cla_map[ev]:
            errs.append("{} の呼び出しが不一致:\n    Copilot = {}\n    Claude  = {}"
                        .format(ev, sorted(cop_map[ev]), sorted(cla_map[ev])))

    # 3. action の実在
    for ev, invs in list(cop_map.items()) + list(cla_map.items()):
        for act, _ in invs:
            if valid_actions and act not in valid_actions:
                errs.append("{}: hook_entry.py に存在しない action: {}(有効: {})"
                            .format(ev, act, ", ".join(sorted(valid_actions))))

    # 4. 参照先スクリプトの実在
    for blob in (json.dumps(cop), json.dumps(cla)):
        for ref in sorted(set(SCRIPT_REF_RE.findall(blob))):
            rel = ref.replace("${CLAUDE_PROJECT_DIR}/", "")
            if not os.path.isfile(os.path.join(root, rel)):
                errs.append("参照先が存在しません: {}".format(rel))

    # 5. VS Code の二重登録防止(hooks.md §3)
    loc = vsc.get("chat.hookFilesLocations") or {}
    if loc.get(".github/hooks") is not True:
        errs.append(".vscode/settings.json: `.github/hooks` が有効になっていません")
    if loc.get(CLAUDE) is not False:
        errs.append(
            ".vscode/settings.json: `{}` を false にしていません。"
            "VS Code は両方を読むため hook が二重登録され、"
            "Stop の連続ブロック回数が二重に加算されます(hooks.md §3)".format(CLAUDE))

    if errs:
        print("hook 配線に不整合があります(定義元: .github/skills/_shared/hooks.md)\n")
        for e in errs:
            print("NG: {}".format(e))
        return 1

    print("OK: hook 配線は整合しています")
    print("  配線しているイベント: {}".format(", ".join(sorted(cop_map))))
    for ev in sorted(cop_map):
        acts = sorted(cop_map[ev])
        print("    {:<14} {}".format(
            ev, ", ".join("{}{}".format(a, " " + " ".join(f) if f else "") for a, f in acts)))
    warn = sorted({a for invs in cop_map.values() for a, f in invs if "--warn-only" in f})
    if warn:
        print("  慣らし運転中(--warn-only): {}".format(", ".join(warn)))
        print("  → 誤検出が出ないことを確認したら、両方の設定ファイルから外す(hooks.md §5)")
    else:
        print("  慣らし運転は終了しています(すべてブロック有効)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
