#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA成果物フォーマットlint(機械チェック)

「定型処理はスクリプトに、判断はAIに」の方針に基づき、qa-improvement 手順2の
セルフレビュー観点のうち機械化できる部分(フォーマット準拠・evidence_level
付与漏れ等)を検査する。**内容の質(指摘の妥当性・分析の正しさ)は判定しない。**

使用例:
    python lint_output.py qa-output/session1/08-test-viewpoint.md
    python lint_output.py 07-code-review.md 10-test-case.md
    python lint_output.py --session-dir qa-output/session1
    python lint_output.py --session-dir qa-output/session1 --json

チェック項目:
    1. ファイル名規約     conventions.md §6 の `NN-<固定名>.md` に合致するか。
                          番号と固定名の対応も確認(規約外は警告)。
    2. 必須セクション     各スキルの SKILL.md「出力フォーマット」節で定義された
                          h2 見出し(## N. <タイトル>)が揃っているか。
                          照合は寛容(番号+先頭キーワードの部分一致)。
                          欠落=エラー、順序・番号違い=警告。
    3. evidence_level     分析・レビュー系成果物で、evidence_level 列の空セルが
                          ないか、文書中に evidence_level への言及があるか
                          (conventions.md §5)。
    4. ID書式             QC-ID は `QC-[A-Z]+-\\d+`、AMB-ID は `AMB-\\d+` 形式か。
                          表のID列(ヘッダが「ID」の列)内の重複がないか。
    5. 曖昧語             期待結果・判定基準の列に「正しく」「適切に」等の
                          合否判定できない語がないか(誤検出があり得るため警告)。

exit code: 0=エラーなし(警告のみ含む) / 1=エラーあり / 2=使用法エラー
"""

import argparse
import json
import os
import re
import sys
import unicodedata

# Windows コンソール等での文字化け防止
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

TOOL_NOTE = (
    "QA成果物フォーマットlint(機械チェック。内容の質=指摘や分析の妥当性は判定しません)"
)

# ---------------------------------------------------------------------------
# conventions.md §6: 成果物の出力先と命名
# 固定名 → (規約上の番号, 成果物種別)
# ---------------------------------------------------------------------------
FIXED_NAMES = {
    "code-overview": ("00", "code-overview"),
    "defect-analysis": ("01", "defect-analysis"),
    "test-analysis": ("02", "test-analysis"),
    "criteria-analysis": ("03", "criteria-analysis"),
    "spec-review-mode1": ("04", "spec-review"),
    "test-planning": ("05", "test-planning"),
    "feature-investigation": ("06", "feature-investigation"),
    "code-review": ("07", "code-review"),
    "test-viewpoint": ("08", "test-viewpoint"),
    "spec-review-mode2": ("09", "spec-review"),
    "test-case": ("10", "test-case"),
    "test-data": ("11", "test-data"),
    "test-design-review": ("12", "test-design-review"),
    "improvement": ("99", "improvement"),
}

# conventions.md §5: 分析・レビュー系(evidence_level を必ず付ける成果物種別)
EVIDENCE_TYPES = {
    "defect-analysis",
    "test-analysis",
    "criteria-analysis",
    "spec-review",
    "code-review",
    "test-design-review",
    "code-overview",
}

EVIDENCE_VALUES = ("confirmed", "likely", "hypothesis")

# qa-test-case-design / qa-criteria-analysis の品質基準に対応する曖昧語
# (単独では合否判定できない語。誤検出があり得るため warning 扱い)
AMBIGUOUS_WORDS = (
    "正しく", "正しい", "適切に", "適切な", "適切で", "適切。",
    "速い", "速く", "十分", "問題ない", "問題なく",
    "ちゃんと", "きちんと", "妥当", "いい感じ",
    "正常に", "期待通り", "期待どおり", "想定通り", "想定どおり",
)
# 曖昧語チェックの対象列(ヘッダにこの語を含む列)
AMBIGUOUS_TARGET_COLUMNS = ("期待結果", "判定基準")

# ---------------------------------------------------------------------------
# 必須セクション対応表
# 各エントリ: (規約上の番号, セクション名, 照合キーワード群, 必須か)
# 照合は「見出しタイトルにキーワードのいずれかが含まれるか」の寛容一致。
# 出典: 各スキルの SKILL.md「出力フォーマット」節(コメント参照)
# ---------------------------------------------------------------------------
SECTION_SPECS = {
    # 出典: qa-defect-analysis/SKILL.md「出力フォーマット(NN-defect-analysis.md)」
    "defect-analysis": {
        "label": "不具合分析レポート",
        "sections": [
            (1, "サマリー", ("サマリ",), True),
            (2, "分類結果", ("分類",), True),
            (3, "クラスタと頻出パターン", ("クラスタ", "頻出パターン"), True),
            (4, "根本原因の仮説", ("根本原因",), True),
            (5, "導出した回帰テスト観点", ("回帰テスト観点", "回帰観点"), True),
            (6, "不足情報・次のアクション", ("不足情報",), True),
        ],
    },
    # 出典: qa-test-analysis/SKILL.md「出力フォーマット(NN-test-analysis.md)」
    "test-analysis": {
        "label": "テスト分析",
        "sections": [
            (1, "変更概要", ("変更概要",), True),
            (2, "影響範囲", ("影響範囲",), True),
            (3, "リスク評価", ("リスク評価",), True),
            (4, "テスト方針", ("テスト方針",), True),
            (5, "不足情報", ("不足情報",), True),
        ],
    },
    # 出典: qa-criteria-analysis/SKILL.md「出力フォーマット(NN-criteria-analysis.md)」
    "criteria-analysis": {
        "label": "品質基準一覧",
        "sections": [
            (1, "対象と範囲", ("対象と範囲", "対象"), True),
            (2, "品質リスクサマリ", ("品質リスク",), True),
            (3, "品質基準一覧(品質特性別)", ("品質基準一覧", "品質基準"), True),
            (4, "策定例一覧", ("策定例",), True),
            (5, "除外した品質特性と理由", ("除外",), True),
            (6, "不足情報", ("不足情報",), True),
        ],
    },
    # 出典: qa-spec-review/SKILL.md「出力フォーマット(NN-spec-review-modeN.md)」
    # モード1/2 共通フォーマット
    "spec-review": {
        "label": "仕様レビュー",
        "sections": [
            (1, "サマリー", ("サマリ",), True),
            (2, "カテゴリ別走査結果", ("カテゴリ別", "走査"), True),
            (3, "検出一覧", ("検出一覧", "検出"), True),
            (4, "ユーザー判定結果", ("ユーザー判定",), True),
            (5, "用語集への追記候補", ("用語集",), True),
        ],
    },
    # 出典: qa-test-planning/SKILL.md「出力フォーマット(NN-test-planning.md)」
    "test-planning": {
        "label": "テスト計画",
        "sections": [
            (1, "目的とスコープ(除外を含む)", ("目的", "スコープ"), True),
            (2, "実施項目一覧", ("実施項目",), True),
            (3, "スケジュール(フェーズと目安)", ("スケジュール",), True),
            (4, "環境・データ・体制の前提", ("前提", "体制"), True),
            (5, "リスクと縮退案", ("縮退", "リスク"), True),
            (6, "完了基準(品質ゲート)", ("完了基準", "品質ゲート"), True),
            (7, "未確定事項", ("未確定",), True),
        ],
    },
    # 出典: qa-feature-investigation/SKILL.md「出力フォーマット(NN-feature-investigation.md)」
    "feature-investigation": {
        "label": "機能調査",
        "sections": [
            (1, "処理の流れ(入口→出口の要約)", ("処理の流れ",), True),
            (2, "入力仕様・バリデーション一覧", ("バリデーション", "入力仕様"), True),
            (3, "権限制御", ("権限",), True),
            (4, "状態と遷移条件", ("状態", "遷移"), True),
            (5, "分岐・設定依存", ("分岐",), True),
            (6, "データ・外部連携への影響", ("外部連携",), True),
            (7, "仕様書との差分(要確認事項)", ("差分", "仕様書"), True),
            (8, "未調査領域", ("未調査",), True),
        ],
    },
    # 出典: qa-code-review/SKILL.md「出力フォーマット(NN-code-review.md)」
    "code-review": {
        "label": "QAコードレビュー",
        "sections": [
            (1, "レビュー範囲と走査した品質特性", ("レビュー範囲",), True),
            (2, "指摘一覧", ("指摘",), True),
            (3, "コードで保証済みの事項(テスト軽減候補)", ("保証済み",), True),
            (4, "テスト観点への引き継ぎ", ("引き継ぎ", "テスト観点"), True),
            (5, "回帰観点カタログとの突合結果", ("突合", "回帰観点カタログ"), True),
            (6, "ユーザー判定と対応結果", ("ユーザー判定",), True),
            (7, "チェックポイント更新の提案", ("チェックポイント",), True),
        ],
    },
    # 出典: qa-test-viewpoint/SKILL.md「出力フォーマット(NN-test-viewpoint.md)」
    "test-viewpoint": {
        "label": "テスト観点一覧",
        "sections": [
            (1, "機能分解表", ("機能分解",), True),
            (2, "テスト観点一覧", ("テスト観点一覧", "観点一覧"), True),
            (3, "対象外とした観点とその理由", ("対象外",), True),
            (4, "期待結果が定義できなかった観点", ("定義できなかった", "期待結果"), True),
        ],
    },
    # 出典: qa-test-case-design/SKILL.md「出力フォーマット(NN-test-case.md)」
    "test-case": {
        "label": "テストケース",
        "sections": [
            (1, "展開サマリー", ("サマリ",), True),
            (2, "テストケース一覧", ("テストケース一覧", "ケース一覧"), True),
            (3, "実行順序・依存関係の注意", ("実行順序", "依存関係"), True),
            (4, "未展開の観点とその理由", ("未展開",), True),
        ],
    },
    # 出典: qa-test-data-design/SKILL.md「出力フォーマット(NN-test-data.md)」
    "test-data": {
        "label": "テストデータ設計",
        "sections": [
            (1, "データ要件マトリクス", ("データ要件", "マトリクス"), True),
            (2, "データ定義", ("データ定義",), True),
            (3, "作成手順 / 生成スクリプト", ("作成手順", "生成スクリプト"), True),
            (4, "投入・リセットの手順(再実行時の戻し方)", ("リセット", "投入"), True),
            (5, "注意事項(マスキング・環境制約)", ("注意事項",), True),
        ],
    },
    # 出典: qa-test-design-review/SKILL.md「出力フォーマット(NN-test-design-review.md)」
    "test-design-review": {
        "label": "テスト設計レビュー",
        "sections": [
            (1, "総合評価", ("総合評価",), True),
            (2, "指摘一覧", ("指摘",), True),
            (3, "良い点(維持すべきこと)", ("良い点",), True),
            (4, "ユーザー判定と対応結果", ("ユーザー判定",), True),
            (5, "チェックリスト更新の提案", ("チェックリスト",), True),
        ],
    },
    # 出典: qa-improvement/SKILL.md「99-improvement.md の構成」
    # セクション6は「KB連携時のみ」のため必須にしない
    "improvement": {
        "label": "振り返りレポート",
        "sections": [
            (1, "セッションサマリ", ("セッションサマリ", "サマリ"), True),
            (2, "成果物セルフレビュー所見", ("セルフレビュー",), True),
            (3, "スキル改善提案(メンテナー向け)", ("改善提案",), True),
            (4, "ナレッジ追記候補", ("ナレッジ",), True),
            (5, "運用フィードバック", ("フィードバック",), True),
            (6, "KB ingest 候補(KB連携時のみ)", ("kb",), False),
        ],
    },
}

# 出典: qa-code-overview/SKILL.md「出力フォーマット(00-code-overview.md)」
# モードA/B/C で見出し構成が異なるため h1 と見出しから自動判別する
CODE_OVERVIEW_MODES = {
    # モードA: プロダクト概要
    "A": {
        "label": "コード概要(モードA: プロダクト概要)",
        "h1_keywords": ("プロダクト概要",),
        "sections": [
            (1, "これは何のシステムか(3行要約)", ("これは何のシステム", "何のシステム"), True),
            (2, "主要機能マップ", ("主要機能",), True),
            (3, "代表的な業務フロー", ("業務フロー",), True),
            (4, "データの全体像", ("データの全体像",), True),
            (5, "外部連携・依存", ("外部連携",), True),
            (6, "設定・権限・環境による挙動差", ("挙動差", "設定・権限"), True),
            (7, "ドキュメントとの対応と食い違い", ("食い違い", "ドキュメント"), True),
            (8, "QAが押さえるべき勘所", ("勘所",), True),
            (9, "用語対応表", ("用語対応",), True),
            (10, "未調査領域と読み方ガイド", ("未調査",), True),
        ],
    },
    # モードB: 改修概要
    "B": {
        "label": "コード概要(モードB: 改修概要)",
        "h1_keywords": ("改修概要",),
        "sections": [
            (1, "何のための変更か(意図の要約)", ("何のための変更", "意図の要約"), True),
            (2, "変更内容の要約(機能単位)", ("変更内容",), True),
            (3, "意図と実装の対応", ("意図と実装",), True),
            (4, "影響範囲", ("影響範囲",), True),
            (5, "挙動が変わる操作・画面・帳票", ("挙動が変わる",), True),
            (6, "回帰リスクが高そうな箇所とその理由", ("回帰リスク",), True),
            (7, "ドキュメントとの食い違い・要確認事項", ("食い違い", "ドキュメント"), True),
            (8, "テスト分析へのインプット要約", ("テスト分析", "インプット"), True),
            (9, "未調査領域", ("未調査",), True),
        ],
    },
    # モードC: 機能概要
    "C": {
        "label": "コード概要(モードC: 機能概要)",
        "h1_keywords": ("機能概要",),
        "sections": [
            (1, "機能の目的と利用シーン", ("機能の目的", "利用シーン"), True),
            (2, "画面・API・バッチの構成", ("構成",), True),
            (3, "処理の流れ(正常系の要約)", ("処理の流れ",), True),
            (4, "主要な分岐・状態(概要レベル)", ("分岐",), True),
            (5, "データ・他機能との関係", ("他機能", "データ・他機能"), True),
            (6, "ドキュメントとの対応と食い違い", ("食い違い", "ドキュメント"), True),
            (7, "QAが押さえるべき勘所", ("勘所",), True),
            (8, "未調査領域", ("未調査",), True),
        ],
    },
}

# ---------------------------------------------------------------------------
# 解析ユーティリティ
# ---------------------------------------------------------------------------

H2_RE = re.compile(r"^##\s+([^#].*)$")
H1_RE = re.compile(r"^#\s+([^#].*)$")
H2_NUM_RE = re.compile(r"^(\d+)\s*[\.．。、:::]?\s*(.*)$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
TABLE_SEP_RE = re.compile(r"^[\s:|\-]+$")
QC_ID_FINDER = re.compile(r"QC-[0-9A-Za-z_\-]+")
QC_ID_VALID = re.compile(r"QC-[A-Z]+-\d+$")
AMB_ID_FINDER = re.compile(r"AMB-[0-9A-Za-z_\-]+")
AMB_ID_VALID = re.compile(r"AMB-\d+$")
FILENAME_RE = re.compile(r"^(\d{2})-([0-9a-z][0-9a-z\-]*)\.md$")
SESSION_FILE_RE = re.compile(r"^\d{2}-.+\.md$")


def norm_text(s):
    """NFKC正規化+小文字化(全角半角・大文字小文字の揺れを許容)"""
    return unicodedata.normalize("NFKC", s).strip().lower()


def iter_lines_outside_fences(lines):
    """フェンスコードブロック外の行だけを (行番号1始まり, 行) で返す"""
    in_fence = False
    fence_mark = None
    for i, line in enumerate(lines, start=1):
        m = FENCE_RE.match(line)
        if m:
            mark = m.group(1)
            if not in_fence:
                in_fence, fence_mark = True, mark
            elif mark == fence_mark:
                in_fence, fence_mark = False, None
            continue
        if not in_fence:
            yield i, line


def parse_headings(lines):
    """フェンス外の h1/h2 見出しを抽出する。

    戻り値: (h1_list, h2_list)
      h1_list: [(行番号, タイトル)]
      h2_list: [(行番号, 番号 or None, タイトル)]
    """
    h1s, h2s = [], []
    for lineno, line in iter_lines_outside_fences(lines):
        m2 = H2_RE.match(line)
        if m2:
            title = m2.group(1).strip()
            mnum = H2_NUM_RE.match(title)
            if mnum:
                h2s.append((lineno, int(mnum.group(1)), mnum.group(2).strip()))
            else:
                h2s.append((lineno, None, title))
            continue
        m1 = H1_RE.match(line)
        if m1:
            h1s.append((lineno, m1.group(1).strip()))
    return h1s, h2s


def split_table_row(line):
    """Markdown表の1行をセルのリストに分割する(エスケープされた | は非対応)"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def parse_tables(lines):
    """フェンス外の Markdown 表を抽出する。

    戻り値: [{"header_line": n, "header": [...], "rows": [(行番号, [セル...])]}]
    """
    tables = []
    block = []  # [(lineno, line)]
    fence_lines = set()
    outside = dict(iter_lines_outside_fences(lines))

    def flush(blk):
        if len(blk) < 2:
            return
        header_line, header_raw = blk[0]
        sep_line = blk[1][1]
        sep_cells = split_table_row(sep_line)
        if not sep_cells or not all(TABLE_SEP_RE.match(c or "-") for c in sep_cells):
            return
        header = split_table_row(header_raw)
        rows = []
        for lineno, raw in blk[2:]:
            rows.append((lineno, split_table_row(raw)))
        tables.append({"header_line": header_line, "header": header, "rows": rows})

    prev_no = None
    for lineno in sorted(outside):
        line = outside[lineno]
        is_table_line = line.lstrip().startswith("|")
        contiguous = prev_no is not None and lineno == prev_no + 1
        if is_table_line:
            if block and not contiguous:
                flush(block)
                block = []
            block.append((lineno, line))
            prev_no = lineno
        else:
            if block:
                flush(block)
                block = []
            prev_no = lineno
    if block:
        flush(block)
    return tables


# ---------------------------------------------------------------------------
# チェック本体
# ---------------------------------------------------------------------------

class FileResult:
    def __init__(self, path):
        self.path = path
        self.artifact_type = None
        self.mode = None
        self.issues = []  # [{"severity","line","check","message"}]

    def add(self, severity, line, check, message):
        self.issues.append(
            {"severity": severity, "line": line, "check": check, "message": message}
        )

    @property
    def errors(self):
        return sum(1 for i in self.issues if i["severity"] == "ERROR")

    @property
    def warnings(self):
        return sum(1 for i in self.issues if i["severity"] == "WARN")


def check_filename(result, path):
    """チェック1: ファイル名規約(conventions.md §6)。成果物種別も特定する。"""
    base = os.path.basename(path)
    m = FILENAME_RE.match(base)
    if not m:
        result.add(
            "WARN", None, "filename",
            "ファイル名が規約 `NN-<固定名>.md`(conventions.md §6)に合致しません: %s"
            "(単独実行・任意名の可能性があるため警告扱い。セクション検査は見出しから推定します)"
            % base,
        )
        return None
    num, name = m.group(1), m.group(2)
    if name in FIXED_NAMES:
        expected_num, artifact_type = FIXED_NAMES[name]
        if num != expected_num:
            result.add(
                "WARN", None, "filename",
                "番号と固定名の対応が規約と異なります: %s(規約では %s-%s.md)"
                % (base, expected_num, name),
            )
        return artifact_type
    # 固定名の部分一致(例: spec-review 単体など)を救済
    for fixed, (_n, artifact_type) in FIXED_NAMES.items():
        if name.startswith(fixed):
            result.add(
                "WARN", None, "filename",
                "固定名 `%s` の変形と推定します: %s(規約の固定名一覧にはありません)"
                % (fixed, base),
            )
            return artifact_type
    result.add(
        "WARN", None, "filename",
        "規約外のファイル名です: %s(conventions.md §6 の固定名一覧に該当なし)" % base,
    )
    return None


def detect_code_overview_mode(result, h1s, h2s):
    """qa-code-overview のモードA/B/Cを h1・見出し構成から自動判別する"""
    for lineno, title in h1s:
        for mode, spec in CODE_OVERVIEW_MODES.items():
            if any(kw in title for kw in spec["h1_keywords"]):
                return mode
    # h1 で判別できない場合は見出しキーワードの一致数で推定
    best_mode, best_score = None, -1
    titles = [norm_text(t) for (_l, _n, t) in h2s]
    for mode, spec in CODE_OVERVIEW_MODES.items():
        score = 0
        for _num, _title, keywords, _req in spec["sections"]:
            if any(any(norm_text(kw) in t for t in titles) for kw in keywords):
                score += 1
        if score > best_score:
            best_mode, best_score = mode, score
    result.add(
        "WARN", h1s[0][0] if h1s else None, "section",
        "h1 からモードを判別できないため、見出し構成からモード%sと推定して検査します"
        % best_mode,
    )
    return best_mode


def check_sections(result, artifact_type, h1s, h2s):
    """チェック2: 必須セクション(各 SKILL.md 出力フォーマット節)"""
    if artifact_type == "code-overview":
        mode = detect_code_overview_mode(result, h1s, h2s)
        result.mode = mode
        spec = CODE_OVERVIEW_MODES[mode]
    else:
        spec = SECTION_SPECS[artifact_type]

    assigned = set()  # 既にどれかの期待セクションに割り当てた h2 のインデックス
    matched = []      # [(期待番号, h2インデックス)]

    for exp_num, exp_title, keywords, required in spec["sections"]:
        found_idx = None
        # 第一候補: 番号一致かつキーワード一致
        for idx, (lineno, num, title) in enumerate(h2s):
            if idx in assigned:
                continue
            nt = norm_text(title)
            if num == exp_num and any(norm_text(kw) in nt for kw in keywords):
                found_idx = idx
                break
        # 第二候補: キーワードのみ一致(番号違い・番号なしを許容)
        if found_idx is None:
            for idx, (lineno, num, title) in enumerate(h2s):
                if idx in assigned:
                    continue
                nt = norm_text(title)
                if any(norm_text(kw) in nt for kw in keywords):
                    found_idx = idx
                    break
        if found_idx is None:
            if required:
                result.add(
                    "ERROR", None, "section",
                    "必須セクション「## %d. %s」が見つかりません(出典: %s の出力フォーマット)"
                    % (exp_num, exp_title, spec["label"]),
                )
            continue
        assigned.add(found_idx)
        matched.append((exp_num, found_idx))
        lineno, num, title = h2s[found_idx]
        if num is None:
            result.add(
                "WARN", lineno, "section",
                "セクション「%s」に番号がありません(規約では「## %d. %s」)"
                % (title, exp_num, exp_title),
            )
        elif num != exp_num:
            result.add(
                "WARN", lineno, "section",
                "セクション番号が規約と異なります: 「## %d. %s」(規約では %d 番)"
                % (num, title, exp_num),
            )

    # 順序チェック(出現順が期待順と逆転していたら警告)
    doc_order = [idx for (_e, idx) in matched]
    if doc_order != sorted(doc_order):
        for (exp_num, idx), (prev_exp, prev_idx) in zip(matched[1:], matched[:-1]):
            if idx < prev_idx:
                lineno, _num, title = h2s[idx]
                result.add(
                    "WARN", lineno, "section",
                    "セクションの順序が規約と異なります: 「%s」(%d番)が %d 番より前にあります"
                    % (title, exp_num, prev_exp),
                )


def check_evidence_level(result, artifact_type, text, tables):
    """チェック3: evidence_level の付与(conventions.md §5)"""
    if artifact_type not in EVIDENCE_TYPES:
        return
    # 文書全体で evidence_level への言及がゼロでないか
    if "evidence_level" not in text and not any(v in text for v in EVIDENCE_VALUES):
        result.add(
            "ERROR", None, "evidence",
            "分析・レビュー系成果物ですが evidence_level への言及がありません"
            "(conventions.md §5: 各指摘・結論に証拠レベルを必ず付ける)",
        )
        return
    # evidence_level 列を持つ表の空セル・不正値
    for table in tables:
        col = None
        for i, h in enumerate(table["header"]):
            if "evidence_level" in norm_text(h):
                col = i
                break
        if col is None:
            continue
        for lineno, cells in table["rows"]:
            if all(not c for c in cells):
                continue  # 完全な空行は無視
            value = cells[col].strip() if col < len(cells) else ""
            if not value or value in ("-", "—", "ー"):
                result.add(
                    "ERROR", lineno, "evidence",
                    "evidence_level 列が空です(confirmed / likely / hypothesis のいずれかを付与)",
                )
            elif not any(v in value for v in EVIDENCE_VALUES):
                result.add(
                    "WARN", lineno, "evidence",
                    "evidence_level の値が規約外です: 「%s」(規約値: confirmed / likely / hypothesis)"
                    % value,
                )


def check_id_formats(result, lines, tables):
    """チェック4: QC-ID / AMB-ID の書式と、表のID列内の重複"""
    for lineno, line in enumerate(lines, start=1):
        for m in QC_ID_FINDER.finditer(line):
            token = m.group(0)
            if not QC_ID_VALID.match(token):
                result.add(
                    "ERROR", lineno, "id-format",
                    "QC-ID の書式が不正です: 「%s」(正しい書式: QC-<英大文字の特性略号>-<番号> 例 QC-PERF-01)"
                    % token,
                )
        for m in AMB_ID_FINDER.finditer(line):
            token = m.group(0)
            if not AMB_ID_VALID.match(token):
                result.add(
                    "ERROR", lineno, "id-format",
                    "AMB-ID の書式が不正です: 「%s」(正しい書式: AMB-<番号> 例 AMB-001)" % token,
                )
    # 表のID列(ヘッダが「ID」ちょうどの列)の重複
    for table in tables:
        for i, h in enumerate(table["header"]):
            if norm_text(h) != "id":
                continue
            seen = {}
            for lineno, cells in table["rows"]:
                value = cells[i].strip() if i < len(cells) else ""
                if not value:
                    continue
                if value in seen:
                    result.add(
                        "ERROR", lineno, "id-duplicate",
                        "ID列に重複があります: 「%s」(初出: L%d)" % (value, seen[value]),
                    )
                else:
                    seen[value] = lineno


def check_ambiguous_words(result, tables):
    """チェック5: 期待結果・判定基準の列の曖昧語(warning。誤検出があり得る)"""
    for table in tables:
        target_cols = [
            i for i, h in enumerate(table["header"])
            if any(t in h for t in AMBIGUOUS_TARGET_COLUMNS)
        ]
        if not target_cols:
            continue
        for lineno, cells in table["rows"]:
            for i in target_cols:
                value = cells[i] if i < len(cells) else ""
                for word in AMBIGUOUS_WORDS:
                    if word in value:
                        result.add(
                            "WARN", lineno, "ambiguous",
                            "「%s」列に曖昧語「%s」があります。合否判定できる表現"
                            "(数値・表示・状態)にできないか確認してください"
                            % (table["header"][i], word.rstrip("。")),
                        )
                        break  # 1セル1警告
    return


def lint_file(path):
    """1ファイルをlintして FileResult を返す"""
    result = FileResult(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        result.add("ERROR", None, "io", "ファイルを読み込めません: %s" % e)
        return result

    lines = text.splitlines()
    artifact_type = check_filename(result, path)
    result.artifact_type = artifact_type

    h1s, h2s = parse_headings(lines)
    tables = parse_tables(lines)

    if artifact_type is not None:
        check_sections(result, artifact_type, h1s, h2s)
        check_evidence_level(result, artifact_type, text, tables)
    check_id_formats(result, lines, tables)
    check_ambiguous_words(result, tables)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def collect_targets(args, parser):
    if args.session_dir and args.files:
        parser.error("--session-dir とファイル指定は同時に使えません")
    if args.session_dir:
        if not os.path.isdir(args.session_dir):
            parser.error("ディレクトリが存在しません: %s" % args.session_dir)
        targets = sorted(
            os.path.join(args.session_dir, fn)
            for fn in os.listdir(args.session_dir)
            if SESSION_FILE_RE.match(fn)
        )
        if not targets:
            parser.error(
                "lint対象(NN-*.md)が見つかりません: %s" % args.session_dir
            )
        return targets
    if not args.files:
        parser.error("lint対象のファイルまたは --session-dir を指定してください")
    for p in args.files:
        if not os.path.isfile(p):
            parser.error("ファイルが存在しません: %s" % p)
    return args.files


def print_text_report(results):
    print(TOOL_NOTE)
    print()
    for r in results:
        print("=== %s ===" % r.path)
        if r.artifact_type:
            label = (
                CODE_OVERVIEW_MODES[r.mode]["label"]
                if r.artifact_type == "code-overview" and r.mode
                else SECTION_SPECS.get(r.artifact_type, {}).get("label", r.artifact_type)
            )
            print("種別: %s (%s)" % (r.artifact_type, label))
        for issue in r.issues:
            loc = "L%d" % issue["line"] if issue["line"] else "-"
            print(
                "%-5s %-5s [%s] %s"
                % (issue["severity"], loc, issue["check"], issue["message"])
            )
        if not r.issues:
            print("OK    問題は検出されませんでした")
        elif r.errors == 0:
            print("OK    エラーなし(警告 %d 件)" % r.warnings)
        print()
    n = len(results)
    e = sum(r.errors for r in results)
    w = sum(r.warnings for r in results)
    print("サマリー: %d files, %d errors, %d warnings" % (n, e, w))


def print_json_report(results):
    payload = {
        "note": TOOL_NOTE,
        "files": [
            {
                "path": r.path,
                "artifact_type": r.artifact_type,
                "mode": r.mode,
                "errors": r.errors,
                "warnings": r.warnings,
                "issues": r.issues,
            }
            for r in results
        ],
        "summary": {
            "files": len(results),
            "errors": sum(r.errors for r in results),
            "warnings": sum(r.warnings for r in results),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="lint_output.py",
        description=(
            "QA成果物(qa-output/<セッション名>/NN-*.md)のフォーマットlint。"
            "ファイル名規約・必須セクション・evidence_level・ID書式・曖昧語を機械チェックします。"
            "これは機械チェックであり、内容の質(指摘や分析の妥当性)は判定しません。"
        ),
        epilog=(
            "exit code: 0=エラーなし(警告のみ含む) / 1=エラーあり / 2=使用法エラー。"
            "規約の出典: _shared/conventions.md §5・§6 および各スキルの SKILL.md 出力フォーマット節。"
        ),
    )
    parser.add_argument("files", nargs="*", help="lint対象の成果物 .md(複数可)")
    parser.add_argument(
        "--session-dir",
        help="セッションディレクトリ(配下の NN-*.md をすべてlint)",
    )
    parser.add_argument(
        "--json", action="store_true", help="機械可読なJSONで出力する"
    )
    args = parser.parse_args(argv)

    targets = collect_targets(args, parser)
    results = [lint_file(p) for p in targets]

    if args.json:
        print_json_report(results)
    else:
        print_text_report(results)

    return 1 if any(r.errors for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
