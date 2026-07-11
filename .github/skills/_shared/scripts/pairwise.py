#!/usr/bin/env python3
"""ペアワイズ(全ペア網羅)テストケース生成CLI。

qa-test-case-design スキル手順2「組み合わせが爆発する場合はペアワイズ適用を提案し、
削減前後のケース数を示す」で使う。どのパラメータ(因子)と値(水準)を組み合わせるかの
判断はAIが行い、全ペア網羅という数学的な組み合わせ生成をこのスクリプトが保証する。
定型処理はスクリプトに、判断はAIに。

参照: .github/skills/_shared/references/test-design-techniques.md §5 ペアワイズ

使用例:
    python pairwise.py params.json                  # Markdown表(既定)
    python pairwise.py params.json --format csv     # CSV(サマリーは stderr)
    python pairwise.py params.json --format json    # JSON(summary + cases)
    python pairwise.py params.json --verify-only    # 入力検証と規模の目安のみ表示

入力形式(JSON, UTF-8):
    {
      "parameters": {
        "OS": ["Windows", "macOS", "Linux"],
        "ブラウザ": ["Chrome", "Edge", "Safari"],
        "権限": ["管理者", "一般", "閲覧のみ"]
      },
      "constraints": [
        {"exclude": {"OS": "Windows", "ブラウザ": "Safari"}}
      ]
    }
    - parameters: 2個以上。各値リストは1個以上、重複不可。
    - constraints(任意): exclude はちょうど2つの「パラメータ: 値」の組。
      その2値ペアを含むケースを生成せず、網羅対象からも除外する。

アルゴリズム:
    貪欲法(greedy)。未カバーの有効ペアのうち辞書順(パラメータ定義順・値定義順)で
    最小のものを種としてケースを作り、残りのパラメータには「未カバーペアを最も多く
    新規カバーする値」を割り当てる(同点は定義順が先の値)。制約で行き詰まった場合は
    バックトラックで完成可能な割り当てを探索する。乱数を使わず処理順が安定しているため
    決定論的(同じ入力 → 常に同じ出力)。
    生成後、全有効ペアが生成ケースでカバーされているか・禁止ペアが混入していないかを
    総当たりで自己検証し、カバレッジ100%でなければ内部エラーとして exit 1。

出力:
    サマリー(全組み合わせ数=直積、生成ケース数、削減率、ペアカバレッジ、
    制約による除外ペア数)とケース一覧。--format csv のときサマリーは stderr に
    出力し、stdout は純粋なCSV(テスト管理ツール取込用)とする。

既知の制限:
    - 2因子間網羅(2-wise)のみ対応。3因子以上の組み合わせ網羅(3-wise等)は非対応。
      「3因子の組み合わせで発生」した過去不具合の組は、AIが個別ケースとして追加する。
    - 貪欲法のため生成ケース数は理論最小とは限らない(最小に近い値にはなる)。

exit code: 0=成功, 1=検証エラー・内部エラー, 2=使用法エラー
"""

import argparse
import itertools
import json
import os
import sys


def _reconfigure_streams():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _fail(message):
    """検証エラー・内部エラー: 日本語メッセージを stderr へ出して exit 1。"""
    print("エラー: " + message, file=sys.stderr)
    sys.exit(1)


class _JapaneseArgumentParser(argparse.ArgumentParser):
    """使用法エラーを日本語で stderr へ出して exit 2。"""

    def error(self, message):
        print("使用法エラー: " + message, file=sys.stderr)
        self.print_usage(sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------------------
# 入力の読み込みと検証
# ---------------------------------------------------------------------------

def load_input(path):
    """入力JSONを読み込み検証する。

    戻り値: (param_names, value_lists, forbidden_pairs)
        param_names: パラメータ名のリスト(定義順)
        value_lists: param_names と同順の値リストのリスト
        forbidden_pairs: {((i, a), (j, b)), ...}  i<j はパラメータ番号、a/b は値番号
    """
    if not os.path.isfile(path):
        _fail("入力ファイルが見つかりません: {}".format(path))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        _fail("入力JSONの解析に失敗しました({}): {}".format(path, e))
    except OSError as e:
        _fail("入力ファイルを読み込めません({}): {}".format(path, e))

    if not isinstance(data, dict):
        _fail("入力JSONのトップレベルはオブジェクトである必要があります。")
    params = data.get("parameters")
    if not isinstance(params, dict) or not params:
        _fail('入力JSONに "parameters"(オブジェクト)が必要です。')
    if len(params) < 2:
        _fail("パラメータは2個以上必要です(現在: {}個)。"
              "組み合わせが発生しないためペアワイズは適用できません。".format(len(params)))

    param_names = list(params.keys())
    value_lists = []
    for name in param_names:
        raw = params[name]
        if not isinstance(raw, list):
            _fail("パラメータ「{}」の値は配列で指定してください。".format(name))
        if not raw:
            _fail("パラメータ「{}」の値リストが空です。1個以上の値が必要です。".format(name))
        vals = []
        for v in raw:
            if isinstance(v, (dict, list)):
                _fail("パラメータ「{}」の値にオブジェクト・配列は使えません: {!r}".format(name, v))
            vals.append(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
        if len(set(vals)) != len(vals):
            _fail("パラメータ「{}」の値に重複があります: {}".format(name, vals))
        value_lists.append(vals)

    param_index = {name: i for i, name in enumerate(param_names)}
    value_index = [{v: a for a, v in enumerate(vals)} for vals in value_lists]

    forbidden_pairs = set()
    constraints = data.get("constraints", [])
    if not isinstance(constraints, list):
        _fail('"constraints" は配列で指定してください。')
    for k, item in enumerate(constraints, start=1):
        if not isinstance(item, dict) or set(item.keys()) != {"exclude"}:
            _fail('constraints の{}番目が不正です。{{"exclude": {{...}}}} の形式で'
                  "指定してください。".format(k))
        excl = item["exclude"]
        if not isinstance(excl, dict) or len(excl) != 2:
            _fail("constraints の{}番目: exclude はちょうど2つの「パラメータ: 値」の"
                  "組で指定してください(現在: {}個)。".format(
                      k, len(excl) if isinstance(excl, dict) else "不正"))
        entries = []
        for pname, pval in excl.items():
            if pname not in param_index:
                _fail("constraints の{}番目: 未定義のパラメータ「{}」が指定されています。".format(
                    k, pname))
            if not isinstance(pval, str):
                pval = json.dumps(pval, ensure_ascii=False)
            i = param_index[pname]
            if pval not in value_index[i]:
                _fail("constraints の{}番目: パラメータ「{}」に値「{}」は定義されていません。".format(
                    k, pname, pval))
            entries.append((i, value_index[i][pval]))
        entries.sort()
        forbidden_pairs.add((entries[0], entries[1]))

    return param_names, value_lists, forbidden_pairs


# ---------------------------------------------------------------------------
# ペア集合の構築と実現可能性チェック
# ---------------------------------------------------------------------------

def compute_valid_pairs(param_names, value_lists, forbidden_pairs):
    """網羅対象の全有効ペアを列挙する(禁止ペアは除外)。"""
    valid = set()
    n = len(param_names)
    for i, j in itertools.combinations(range(n), 2):
        for a in range(len(value_lists[i])):
            for b in range(len(value_lists[j])):
                pair = ((i, a), (j, b))
                if pair not in forbidden_pairs:
                    valid.add(pair)
    return valid


def check_feasibility(param_names, value_lists, forbidden_pairs):
    """各「パラメータ: 値」が他の全パラメータと組める値を持つか確認する。

    ある値が他パラメータの全値と禁止されている場合、その値を含む有効ペアは
    どのケースにも載せられず全ペア網羅が不可能になるため、エラーで終了する。
    """
    n = len(param_names)
    for i in range(n):
        for a in range(len(value_lists[i])):
            for j in range(n):
                if i == j:
                    continue
                lo, hi = (i, j) if i < j else (j, i)
                ok = False
                for b in range(len(value_lists[j])):
                    pair = ((lo, a if lo == i else b), (hi, b if hi == j else a))
                    if pair not in forbidden_pairs:
                        ok = True
                        break
                if not ok:
                    _fail("制約が矛盾しています: パラメータ「{}」の値「{}」は"
                          "パラメータ「{}」のどの値とも組み合わせられず、"
                          "全ペア網羅が不可能です。制約を見直してください。".format(
                              param_names[i], value_lists[i][a], param_names[j]))


# ---------------------------------------------------------------------------
# 貪欲法によるペアワイズ生成(決定論的)
# ---------------------------------------------------------------------------

def _canonical(i, a, j, b):
    return ((i, a), (j, b)) if i < j else ((j, b), (i, a))


def _build_case(seed, n_params, value_lists, forbidden_pairs, uncovered):
    """種ペアから1ケースを構築する。構築不能なら None。

    残りパラメータを定義順に埋める。各パラメータでは「未カバーペアの新規カバー数が
    最大」の値を優先し(同点は値の定義順)、禁止ペアで行き詰まったらバックトラック。
    """
    (si, sa), (sj, sb) = seed
    assignment = {si: sa, sj: sb}
    order = [k for k in range(n_params) if k not in assignment]

    def compatible(k, c):
        for m, vm in assignment.items():
            if _canonical(k, c, m, vm) in forbidden_pairs:
                return False
        return True

    def backtrack(pos):
        if pos == len(order):
            return True
        k = order[pos]
        candidates = []
        for c in range(len(value_lists[k])):
            if not compatible(k, c):
                continue
            gain = sum(1 for m, vm in assignment.items()
                       if _canonical(k, c, m, vm) in uncovered)
            candidates.append((-gain, c))
        candidates.sort()
        for _, c in candidates:
            assignment[k] = c
            if backtrack(pos + 1):
                return True
            del assignment[k]
        return False

    if not backtrack(0):
        return None
    return tuple(assignment[k] for k in range(n_params))


def generate_cases(param_names, value_lists, forbidden_pairs, valid_pairs):
    """全有効ペアをカバーするケース群を貪欲法で生成する(決定論的)。"""
    n = len(param_names)
    uncovered = set(valid_pairs)
    cases = []
    while uncovered:
        seed = min(uncovered)  # 辞書順最小 → 決定論的
        case = _build_case(seed, n, value_lists, forbidden_pairs, uncovered)
        if case is None:
            (i, a), (j, b) = seed
            _fail("制約が矛盾しています: ペア({}: {}, {}: {})を含む有効なケースを"
                  "構成できず、全ペア網羅が不可能です。制約を見直してください。".format(
                      param_names[i], value_lists[i][a],
                      param_names[j], value_lists[j][b]))
        cases.append(case)
        for i, j in itertools.combinations(range(n), 2):
            uncovered.discard(((i, case[i]), (j, case[j])))
    return cases


def self_verify(cases, n_params, forbidden_pairs, valid_pairs):
    """自己検証: 全有効ペアのカバーと禁止ペアの非混入を総当たりで確認する。

    戻り値: カバーされたペア数。失敗時は内部エラーとして exit 1。
    """
    covered = set()
    for case in cases:
        for i, j in itertools.combinations(range(n_params), 2):
            pair = ((i, case[i]), (j, case[j]))
            if pair in forbidden_pairs:
                _fail("内部エラー: 生成ケースに禁止ペアが含まれています。"
                      "このスクリプトの不具合です。結果を使用しないでください。")
            covered.add(pair)
    missing = valid_pairs - covered
    if missing:
        _fail("内部エラー: {}個の有効ペアがカバーされていません"
              "(カバレッジ100%未達)。このスクリプトの不具合です。"
              "結果を使用しないでください。".format(len(missing)))
    return len(valid_pairs & covered)


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------

def _total_combinations(value_lists):
    total = 1
    for vals in value_lists:
        total *= len(vals)
    return total


def build_summary(param_names, value_lists, forbidden_pairs, valid_pairs, cases):
    total = _total_combinations(value_lists)
    n_cases = len(cases)
    reduction = (1 - n_cases / total) * 100 if total else 0.0
    return {
        "パラメータ数": len(param_names),
        "パラメータ": {name: len(vals) for name, vals in zip(param_names, value_lists)},
        "全組み合わせ数(直積)": total,
        "生成ケース数": n_cases,
        "削減率": round(reduction, 1),
        "カバーした有効ペア数": len(valid_pairs),
        "全有効ペア数": len(valid_pairs),
        "ペアカバレッジ": 100.0,
        "制約による除外ペア数": len(forbidden_pairs),
    }


def _summary_lines(summary):
    params_desc = ", ".join(
        "{}: {}値".format(name, cnt) for name, cnt in summary["パラメータ"].items())
    return [
        "- パラメータ数: {}({})".format(summary["パラメータ数"], params_desc),
        "- 全組み合わせ数(直積): {}".format(summary["全組み合わせ数(直積)"]),
        "- 生成ケース数: {}(削減率: {}%)".format(
            summary["生成ケース数"], summary["削減率"]),
        "- ペアカバレッジ: {}/{}(100%)".format(
            summary["カバーした有効ペア数"], summary["全有効ペア数"]),
        "- 制約による除外ペア数: {}".format(summary["制約による除外ペア数"]),
    ]


def output_md(param_names, value_lists, cases, summary):
    print("# ペアワイズテストケース")
    print()
    print("## サマリー")
    print()
    for line in _summary_lines(summary):
        print(line)
    print()
    print("## テストケース一覧")
    print()
    print("| No. | " + " | ".join(param_names) + " |")
    print("|---|" + "---|" * len(param_names))
    for no, case in enumerate(cases, start=1):
        row = [value_lists[i][case[i]] for i in range(len(param_names))]
        print("| {} | ".format(no) + " | ".join(row) + " |")


def output_csv(param_names, value_lists, cases, summary):
    import csv
    # stdout を純粋なCSVに保つため、サマリーは stderr へ出す
    print("サマリー:", file=sys.stderr)
    for line in _summary_lines(summary):
        print(line, file=sys.stderr)
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["No."] + param_names)
    for no, case in enumerate(cases, start=1):
        writer.writerow([no] + [value_lists[i][case[i]] for i in range(len(param_names))])


def output_json(param_names, value_lists, cases, summary):
    payload = {
        "summary": summary,
        "cases": [
            {name: value_lists[i][case[i]] for i, name in enumerate(param_names)}
            for case in cases
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def output_verify_only(param_names, value_lists, forbidden_pairs, valid_pairs):
    total = _total_combinations(value_lists)
    counts = sorted((len(vals) for vals in value_lists), reverse=True)
    est_low = counts[0] * counts[1]  # 理論下限: 最大2水準の積
    est_high = max(est_low, int(round(est_low * 1.5)))
    print("入力検証: OK")
    print("- パラメータ数: {}".format(len(param_names)))
    for name, vals in zip(param_names, value_lists):
        print("  - {}: {}値({})".format(name, len(vals), ", ".join(vals)))
    print("- 全組み合わせ数(直積): {}".format(total))
    print("- 全有効ペア数: {}(制約による除外ペア数: {})".format(
        len(valid_pairs), len(forbidden_pairs)))
    print("- 推定生成ケース数の目安: {}〜{}(理論下限は最大2水準の積 = {})".format(
        est_low, est_high, est_low))
    print("- 判断の目安: 全組み合わせ数が推定生成ケース数を大きく上回る場合、"
          "ペアワイズ適用を提案する価値がある。")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    _reconfigure_streams()
    parser = _JapaneseArgumentParser(
        prog="pairwise.py",
        description="ペアワイズ(全ペア網羅)テストケース生成。"
                    "入力はパラメータ定義JSONファイル。")
    parser.add_argument("input", help="パラメータ定義JSONファイルのパス")
    parser.add_argument("--format", choices=["md", "csv", "json"], default="md",
                        help="出力形式(既定: md)")
    parser.add_argument("--verify-only", action="store_true",
                        help="生成せず入力の妥当性と規模の目安のみ表示する")
    args = parser.parse_args(argv)

    param_names, value_lists, forbidden_pairs = load_input(args.input)
    check_feasibility(param_names, value_lists, forbidden_pairs)
    valid_pairs = compute_valid_pairs(param_names, value_lists, forbidden_pairs)
    if not valid_pairs:
        _fail("制約により有効なペアが1つも残りません。制約を見直してください。")

    if args.verify_only:
        output_verify_only(param_names, value_lists, forbidden_pairs, valid_pairs)
        return 0

    cases = generate_cases(param_names, value_lists, forbidden_pairs, valid_pairs)
    self_verify(cases, len(param_names), forbidden_pairs, valid_pairs)

    summary = build_summary(param_names, value_lists, forbidden_pairs, valid_pairs, cases)
    if args.format == "md":
        output_md(param_names, value_lists, cases, summary)
    elif args.format == "csv":
        output_csv(param_names, value_lists, cases, summary)
    else:
        output_json(param_names, value_lists, cases, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
