"""Parse KB search queries: law name hints, article numbers, FTS MATCH strings."""

from __future__ import annotations

import re
from typing import List, Optional

from kb_fts import normalize_fts_query

_ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百千零〇\d]+条")

_SEARCH_VERBS_RE = re.compile(
    r"^(检索|查找|搜索|查询|帮我|请|帮忙|找一下|查一下)\s*"
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
    """Return article strings found in query, e.g. ['第六十四条'] or ['第64条']."""
    text = query or ""
    seen = set()
    out: List[str] = []
    for m in _ARTICLE_RE.findall(text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


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


def extract_law_name_hint(query: str) -> Optional[str]:
    """Heuristic: strip search verbs, keep span containing 法|条例|规定|办法."""
    text = (query or "").strip()
    if not text:
        return None
    text = _SEARCH_VERBS_RE.sub("", text).strip()
    # Drop article spans so they don't pollute the law name
    text_wo = _ARTICLE_RE.sub(" ", text)
    text_wo = re.sub(r"\s+", " ", text_wo).strip()
    if not text_wo:
        return None
    # Prefer continuous CJK run that ends with a law-like suffix
    candidates = re.findall(
        r"[\u4e00-\u9fff]{2,}(?:法|条例|规定|办法)", text_wo
    )
    if candidates:
        # Longest first (more specific)
        candidates.sort(key=len, reverse=True)
        return candidates[0]
    if _LAW_SUFFIX_RE.search(text_wo):
        # Fallback: take CJK chars around the suffix token
        m = re.search(
            r"([\u4e00-\u9fff]{2,}(?:法|条例|规定|办法))", text_wo
        )
        if m:
            return m.group(1)
    return None


def _quote_token(t: str) -> str:
    return '"' + t.replace('"', "") + '"'


def build_fts_match(query: str) -> str:
    """
    If both law-name hint and article are present: AND law tokens with article.
    Otherwise: fall back to OR via normalize_fts_query.
    """
    text = (query or "").strip()
    if not text:
        return ""
    articles = extract_articles(text)
    hint = extract_law_name_hint(text)
    if not (articles and hint):
        return normalize_fts_query(text)

    # Law-side tokens: prefer the full hint as a phrase, plus 2+ char pieces
    law_tokens: List[str] = []
    if len(hint) >= 2:
        law_tokens.append(hint)
    for part in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9\-]+", hint):
        if part not in law_tokens:
            law_tokens.append(part)
    # Cap law tokens
    law_tokens = law_tokens[:6]

    # Article side: include original + normalized forms (unique)
    art_tokens: List[str] = []
    for a in articles:
        for form in normalize_article_forms(a):
            if form not in art_tokens:
                art_tokens.append(form)
    art_tokens = art_tokens[:4]

    if not law_tokens or not art_tokens:
        return normalize_fts_query(text)

    # Law group: OR among law tokens (any law phrase) AND article group
    # (OR among article forms so 第64条 / 第六十四条 both match)
    law_expr = " OR ".join(_quote_token(t) for t in law_tokens)
    art_expr = " OR ".join(_quote_token(t) for t in art_tokens)
    if len(law_tokens) == 1:
        law_part = law_expr
    else:
        law_part = f"({law_expr})"
    if len(art_tokens) == 1:
        art_part = art_expr
    else:
        art_part = f"({art_expr})"
    return f"{law_part} AND {art_part}"
