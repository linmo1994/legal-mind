"""Parse KB search queries: law name hints, article numbers, FTS MATCH strings."""

from __future__ import annotations

import re
from typing import List, Optional

from kb_fts import normalize_fts_query

_ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百千零〇\d]+条")
# 口语缺「第」：64条 / 六十四条（不与已匹配的「第…条」重叠）
_ARTICLE_BARE_AR_RE = re.compile(r"(?<![第\d])(\d{1,4})条")
_ARTICLE_BARE_CN_RE = re.compile(
    r"(?<![第零〇一二三四五六七八九十百千])([一二三四五六七八九十百千零〇]{1,12})条"
)
# 口语缺「条」：第64 / 第六十四（后不得再跟数字/中文数码，也不得跟 条/章/节…）
_ARTICLE_NO_TIAO_RE = re.compile(
    r"第(\d{1,4}|[一二三四五六七八九十百千零〇]{1,12})"
    r"(?![零〇一二三四五六七八九十百千\d])"
    r"(?![条章节款项编])"
)

_SEARCH_VERB_TOKENS = (
    "找一下",
    "查一下",
    "帮忙",
    "检索",
    "查找",
    "搜索",
    "查询",
    "帮我",
    "请",
)

_SEARCH_VERBS_RE = re.compile(
    r"^(" + "|".join(re.escape(v) for v in _SEARCH_VERB_TOKENS) + r")\s*"
)

_LAW_SUFFIX_RE = re.compile(r"(法|条例|规定|办法)")

_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def extract_articles(query: str) -> List[str]:
    """Return canonical article labels, e.g. ['第64条'] (covers 64条 / 六十四条 / 第64)."""
    text = query or ""
    nums: List[int] = []
    seen_n = set()

    def _add_num(n: Optional[int]) -> None:
        if n is None or n <= 0 or n in seen_n:
            return
        # Guardrail: statute articles in practice are rarely > 9999
        if n > 9999:
            return
        seen_n.add(n)
        nums.append(n)

    for m in _ARTICLE_RE.finditer(text):
        inner = m.group(0)[1:-1]
        if inner.isdigit():
            _add_num(int(inner))
        else:
            _add_num(_cn_to_int(inner))

    for m in _ARTICLE_BARE_AR_RE.finditer(text):
        _add_num(int(m.group(1)))

    for m in _ARTICLE_BARE_CN_RE.finditer(text):
        _add_num(_cn_to_int(m.group(1)))

    for m in _ARTICLE_NO_TIAO_RE.finditer(text):
        inner = m.group(1)
        if inner.isdigit():
            _add_num(int(inner))
        else:
            _add_num(_cn_to_int(inner))

    out: List[str] = []
    for n in nums:
        # Prefer Arabic canonical; normalize_article_forms expands Chinese twin.
        out.append(f"第{n}条")
    return out


def _strip_article_spans(text: str) -> str:
    """Remove article-like spans so they do not pollute law-name hints / FTS tokens."""
    t = text or ""
    t = _ARTICLE_RE.sub(" ", t)
    t = _ARTICLE_BARE_AR_RE.sub(" ", t)
    t = _ARTICLE_BARE_CN_RE.sub(" ", t)
    t = _ARTICLE_NO_TIAO_RE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def _cn_to_int(s: str) -> Optional[int]:
    """Convert Chinese numeral (up to 9999) to int; None if unparseable."""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s == "百":
        return 100
    total = 0
    num = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
            i += 1
            continue
        if ch == "十":
            total += (num if num else 1) * 10
            num = 0
            i += 1
            continue
        if ch == "百":
            total += (num if num else 1) * 100
            num = 0
            i += 1
            continue
        if ch == "千":
            total += (num if num else 1) * 1000
            num = 0
            i += 1
            continue
        return None
    total += num
    return total if total > 0 or s in ("零", "〇") else None


def _int_to_cn(n: int) -> str:
    """Convert positive int (1–9999) to legal-style Chinese numerals (第X条)."""
    if n <= 0:
        return str(n)
    digits = "零一二三四五六七八九"
    if n < 10:
        return digits[n]
    if n == 10:
        return "十"
    if n < 20:
        # Standalone teens: 十一…十九 (omit leading 一)
        return "十" + digits[n % 10]
    if n < 100:
        tens, ones = divmod(n, 10)
        return digits[tens] + "十" + (digits[ones] if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = digits[hundreds] + "百"
        if rest == 0:
            return head
        if rest < 10:
            return head + "零" + digits[rest]
        # After 百, teens must keep 一: 一百一十 / 一百一十一 (not 一百十)
        if rest < 20:
            ones = rest % 10
            return head + "一十" + (digits[ones] if ones else "")
        return head + _int_to_cn(rest)
    thousands, rest = divmod(n, 1000)
    head = digits[thousands] + "千"
    if rest == 0:
        return head
    if rest < 10:
        return head + "零" + digits[rest]
    if rest < 100:
        # 1010 → 一千零一十; 1011 → 一千零一十一
        if rest < 20:
            ones = rest % 10
            return head + "零一十" + (digits[ones] if ones else "")
        return head + "零" + _int_to_cn(rest)
    return head + _int_to_cn(rest)


def normalize_article_forms(article: str) -> List[str]:
    """Arabic/Chinese variants of the same article for matching/highlight."""
    raw = (article or "").strip()
    if not raw:
        return []
    m = _ARTICLE_RE.fullmatch(raw) or _ARTICLE_RE.search(raw)
    if not m:
        return [raw]
    core = m.group(0)
    inner = core[1:-1]  # strip 第 … 条
    forms: List[str] = []
    seen = set()

    def add(s: str) -> None:
        if s and s not in seen:
            seen.add(s)
            forms.append(s)

    add(core)
    n: Optional[int] = None
    if inner.isdigit():
        n = int(inner)
    else:
        n = _cn_to_int(inner)
    if n is not None and n > 0:
        add(f"第{n}条")
        add(f"第{_int_to_cn(n)}条")
    return forms


def doc_has_article(doc: str, article: str) -> bool:
    """True if document text contains any normalized form of the article."""
    text = doc or ""
    if not text or not (article or "").strip():
        return False
    return any(form in text for form in normalize_article_forms(article))


def resolve_hit_article(doc: str, query: str = "") -> Optional[str]:
    """Pick citation article from hit text; never stamp query article onto unrelated chunks.

    Prefer a query article only when a normalized form appears in the document;
    otherwise use the first surface 「第…条」 found in the document; otherwise None.
    """
    text = (doc or "").strip()
    query_articles = extract_articles(query or "")
    # Prefer labels as written in the chunk (第六十四条), not canonical 第64条.
    doc_surface = list(dict.fromkeys(_ARTICLE_RE.findall(text))) if text else []

    for qa in query_articles:
        qa_forms = set(normalize_article_forms(qa))
        if not qa_forms:
            continue
        if not any(f in text for f in qa_forms):
            continue
        for da in doc_surface:
            if set(normalize_article_forms(da)) & qa_forms:
                return da
        return qa

    if doc_surface:
        return doc_surface[0]
    return None


def extract_law_name_hint(query: str) -> Optional[str]:
    """Heuristic: strip search verbs, keep span containing 法|条例|规定|办法."""
    text = (query or "").strip()
    if not text:
        return None
    # Strip stacked leading verbs: 「帮我检索劳动合同法…」
    while True:
        nxt = _SEARCH_VERBS_RE.sub("", text).strip()
        if nxt == text:
            break
        text = nxt
    # Drop article spans so they don't pollute the law name
    text_wo = _strip_article_spans(text)
    if not text_wo:
        return None
    # Prefer continuous CJK run that ends with a law-like suffix
    candidates = re.findall(
        r"[\u4e00-\u9fff]{2,}(?:法|条例|规定|办法)", text_wo
    )
    if candidates:
        # Longest first (more specific)
        candidates.sort(key=len, reverse=True)
        hint = candidates[0]
    elif _LAW_SUFFIX_RE.search(text_wo):
        # Fallback: take CJK chars around the suffix token
        m = re.search(
            r"([\u4e00-\u9fff]{2,}(?:法|条例|规定|办法))", text_wo
        )
        if not m:
            return None
        hint = m.group(1)
    else:
        return None

    # If a verb was glued into the candidate (no whitespace), peel it off.
    changed = True
    while changed:
        changed = False
        for v in sorted(_SEARCH_VERB_TOKENS, key=len, reverse=True):
            if hint.startswith(v) and len(hint) > len(v) + 1:
                hint = hint[len(v) :]
                changed = True
                break
    return hint or None


def _quote_token(t: str) -> str:
    return '"' + t.replace('"', "") + '"'


def build_fts_match(query: str) -> str:
    """
    Build FTS5 MATCH string.

    When both law-name hint and article are present: MATCH **article forms only**.
    Law name is applied as a title filter in KbFtsIndex.search (title is UNINDEXED;
    unicode61 also keeps full titles as one token so AND-ing 「劳动合同法」 against
    body_idx often yields zero hits).
    Otherwise: fall back to OR via normalize_fts_query.
    """
    text = (query or "").strip()
    if not text:
        return ""
    articles = extract_articles(text)
    hint = extract_law_name_hint(text)
    if not (articles and hint):
        return normalize_fts_query(text)

    art_tokens: List[str] = []
    for a in articles:
        for form in normalize_article_forms(a):
            if form not in art_tokens:
                art_tokens.append(form)
    art_tokens = art_tokens[:4]
    if not art_tokens:
        return normalize_fts_query(text)
    return " OR ".join(_quote_token(t) for t in art_tokens)
