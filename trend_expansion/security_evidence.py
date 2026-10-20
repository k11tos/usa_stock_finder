"""Bounded finalist-only SEC verification; listing names cannot certify equity."""

from __future__ import annotations

import json
import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import quote

from trend_expansion.research_cache import ResearchCache, ResearchDataError, sha256

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_COMMON = re.compile(r"\b(?:common (?:stock|shares?)|ordinary shares?)\b", re.I)
_NONCOMMON = re.compile(r"\b(?:preferred|preference|warrant|units?|rights?|notes?|closed.end|fund|etf|etn)\b", re.I)
_XBRL_TRANSFORM = "http://www.xbrl.org/inlineXBRL/transformation/"
_SEC_TRANSFORM = "http://www.sec.gov/inlineXBRL/transformation/2015-08-31"
_FIXED_BOOLEANS = {
    (_XBRL_TRANSFORM + "2015-02-26", "booleantrue"): True,
    (_XBRL_TRANSFORM + "2015-02-26", "booleanfalse"): False,
    **{(_XBRL_TRANSFORM + version, name): value
       for version in ("2020-02-12", "2022-02-16")
       for name, value in (("fixed-true", True), ("fixed-false", False))},
}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
              "source", "track", "wbr"}


def _shell_value(fact: dict) -> tuple[bool | None, str]:
    """Decode only XML booleans and the SEC-listed boolean transformations."""
    if fact["malformed"] or not fact["context_ref"] or fact["nil"]:
        return None, "ambiguous"
    if fact["continued"] or fact["tag"] != "ix:nonnumeric":
        return None, "unsupported"
    if fact["format"] is None:
        values = {"true": True, "1": True, "false": False, "0": False}
        value = values.get(fact["text"])
    else:
        transform = (fact["format_namespace"], fact["format"].split(":")[-1])
        if transform in _FIXED_BOOLEANS:
            value = _FIXED_BOOLEANS[transform]
        elif transform == (_SEC_TRANSFORM, "boolballotbox"):
            value = {"☐": False, "☑": True, "☒": True}.get(fact["text"])
        else:
            return None, "unsupported"
    return value, "ambiguous" if value is None else "explicit_true" if value else "explicit_false"


class CoverPage(HTMLParser):
    """Read inline XBRL facts, preserving class context and nested HTML text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.facts = []
        self.shell_facts = []
        self.active = None
        self.fact_tags = []
        self.namespaces = {}
        self.scopes = []
        self.malformed = False

    def handle_starttag(self, tag, attrs):
        duplicate_attrs = len(attrs) != len(dict(attrs))
        attrs = dict(attrs)
        previous = self.namespaces
        declared = {key[6:]: value for key, value in attrs.items() if key.startswith("xmlns:")}
        self.namespaces = {**previous, **declared} if declared else previous
        if tag not in _VOID_TAGS:
            self.scopes.append((tag, previous))
        if self.active is not None:
            if tag.startswith("ix:"):
                self.active["malformed"] = True  # No nested facts or ix:exclude inference.
            if tag not in _VOID_TAGS:
                self.fact_tags.append(tag)
            return
        name = attrs.get("name", "").lower()
        if tag in {"ix:nonnumeric", "ix:nonfraction"} and name.startswith("dei:"):
            shell = name == "dei:entityshellcompany"
            # Only shell booleans have a narrowly supported transformation path.
            if not shell and ("continuedat" in attrs or "format" in attrs):
                return
            fmt = (attrs.get("format") or "") if "format" in attrs else None
            self.active = {"name": name.split(":")[-1], "context_ref": attrs.get("contextref", ""),
                           "text": [], "format": fmt,
                           "format_namespace": self.namespaces.get(fmt.split(":")[0])
                           if fmt and fmt.count(":") == 1 else None,
                           "continued": "continuedat" in attrs,
                           "nil": any(key.endswith(":nil") and value not in {"false", "0"}
                                      for key, value in attrs.items()),
                           "malformed": duplicate_attrs, "tag": tag}
            self.fact_tags = [tag]

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.active is not None:
            if self.fact_tags[-1] == tag:
                self.fact_tags.pop()
            else:
                self.active["malformed"] = True
                if tag in self.fact_tags:
                    while self.fact_tags.pop() != tag:
                        pass
            if not self.fact_tags:
                self._finish_fact()
        while self.scopes:
            opened, self.namespaces = self.scopes.pop()
            if opened == tag:
                break

    def handle_data(self, data):
        if self.active is not None:
            self.active["text"].append(data)

    def _finish_fact(self):
        fact = self.active
        self.malformed = self.malformed or fact["malformed"]
        fact["text"] = " ".join("".join(fact["text"]).split())
        name = fact.pop("name")
        if name == "entityshellcompany":
            fact["value"], fact["status"] = _shell_value(fact)
            self.shell_facts.append(fact)
        elif not fact["malformed"]:
            self.facts.append((name, fact["context_ref"], fact["text"]))
        self.active = None

    def close(self):
        super().close()
        if self.active is not None:
            self.active["malformed"] = True
            self._finish_fact()


def classify_cover(payload: bytes, symbol: str) -> tuple[str, dict]:
    """Require matched class context, common title and explicit non-shell fact."""
    parser = CoverPage()
    parser.feed(payload.decode("utf-8"))
    parser.close()
    shells = {fact["status"] for fact in parser.shell_facts}
    if parser.malformed:
        shells.add("ambiguous")  # A malformed outer fact may have swallowed a shell fact.
    shell_status = ("contradictory" if {"explicit_true", "explicit_false"} <= shells
                    else "explicit_true" if "explicit_true" in shells
                    else "ambiguous" if "ambiguous" in shells
                    else "unsupported" if "unsupported" in shells
                    else "explicit_false" if shells else "missing")
    evidence = {"shell_status": shell_status, "shell_facts": parser.shell_facts,
                "cover_structure_ambiguous": parser.malformed}
    if shell_status in {"explicit_true", "contradictory"}:
        return "not_common", {**evidence, "classification": "shell_company"}
    if shell_status != "explicit_false":
        return "unknown", {**evidence, "classification": "shell_status_unknown"}
    contexts = {context for name, context, text in parser.facts
                if name == "tradingsymbol" and text.upper().replace(".", "-") == symbol.replace(".", "-")}
    titles = [text for name, context, text in parser.facts
              if name == "security12btitle" and context and context in contexts]
    if not titles:
        return "unknown", {**evidence, "classification": "class_context_unmatched"}
    if any(_NONCOMMON.search(title) for title in titles):
        return "not_common", {**evidence, "classification": "non_common_class", "class_titles": sorted(titles)}
    if not all(_COMMON.search(title) for title in titles):
        return "unknown", {**evidence, "classification": "class_type_unknown", "class_titles": sorted(titles)}
    return "verified", {**evidence, "classification": "operating_common_equity", "class_titles": sorted(titles)}


def _validated_cik(value: object) -> int:
    """Accept integer CIKs or ASCII decimal digits (including SEC zero padding)."""
    if isinstance(value, int) and not isinstance(value, bool):
        cik = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        if len(value) > 10:
            raise ResearchDataError("sec_cik_invalid")
        cik = int(value)
    else:
        raise ValueError("malformed CIK representation")
    if not 0 < cik < 10_000_000_000:
        raise ResearchDataError("sec_cik_invalid")
    return cik


class SecVerifier:
    """One cached CIK map plus at most two requests per considered finalist.

    No historical submissions pagination, companyfacts or issuer crawl. Current
    submissions are a coverage aid, not a point-in-time security master. Exact
    class evidence must be an annual filing filed by asof_date. Unavailable or
    ambiguous evidence is unknown and the next ranked name may be considered.
    """

    def __init__(self, cache: ResearchCache, asof_date: str):
        self.cache = cache
        self.asof_date = asof_date
        self.mapping = None
        self.mapping_error = None

    def verify(self, symbol: str) -> dict:
        evidence = {"status": "unknown", "authority": "SEC EDGAR", "sources": []}
        try:
            if self.mapping_error:
                raise ResearchDataError(self.mapping_error)
            if self.mapping is None:
                try:
                    raw = self.cache.get_asof(TICKERS_URL, self.asof_date)
                    self.mapping = json.loads(raw)
                    if not isinstance(self.mapping, dict) or len(self.mapping) > 20000:
                        raise ResearchDataError("sec_mapping_invalid")
                except (ResearchDataError, ValueError) as exc:
                    self.mapping_error = exc.reason if isinstance(exc, ResearchDataError) else "sec_mapping_invalid"
                    raise ResearchDataError(self.mapping_error) from exc
            evidence["sources"].append({"url": TICKERS_URL,
                                        "sha256": self.cache.used[sha256(TICKERS_URL.encode())]["sha256"]})
            # Do not infer identity or uniqueness from a partially malformed map.
            if any(not isinstance(row, dict) or not isinstance(row.get("ticker"), str)
                   for row in self.mapping.values()):
                raise ResearchDataError("sec_mapping_invalid")
            matches = {_validated_cik(row["cik_str"]) for row in self.mapping.values()
                       if row["ticker"].upper().replace(".", "-") == symbol.replace(".", "-")}
            if len(matches) != 1:
                return {**evidence, "reason": "sec_cik_unknown"}
            cik = matches.pop()
            url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
            raw = self.cache.get_asof(url, self.asof_date)
            evidence["sources"].append({"url": url, "sha256": sha256(raw)})
            submission = json.loads(raw)
            if _validated_cik(submission["cik"]) != cik:
                raise ResearchDataError("sec_cik_mismatch")
            evidence.update(cik=cik, entity_type=submission.get("entityType"), sic=str(submission.get("sic", "")))
            if submission.get("entityType") == "investment" or str(submission.get("sic")) in {"6722", "6726", "6770"}:
                return {**evidence, "status": "not_common", "reason": "investment_company_or_shell"}
            if submission.get("entityType") != "operating" or not str(submission.get("sic", "")).isdigit():
                return {**evidence, "reason": "operating_status_unknown"}
            recent = submission["filings"]["recent"]
            if len(recent["form"]) > 2000:
                raise ResearchDataError("sec_recent_too_large")
            filings = [(recent["filingDate"][i], recent["accessionNumber"][i], recent["primaryDocument"][i])
                       for i, form in enumerate(recent["form"])
                       if form in {"10-K", "20-F"} and recent["filingDate"][i] <= self.asof_date]
            if not filings:
                return {**evidence, "reason": "annual_filing_unavailable_asof"}
            filed, accession, document = max(filings)
            filed_day = date.fromisoformat(filed)
            if filed_day.isoformat() != filed or (date.fromisoformat(self.asof_date) - filed_day).days > 550:
                return {**evidence, "reason": "annual_filing_stale_or_invalid"}
            if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not re.fullmatch(r"[\w.-]+", document):
                raise ResearchDataError("sec_document_invalid")
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{quote(document)}"
            raw = self.cache.get_asof(url, self.asof_date, not_before=filed)
            evidence["sources"].append({"url": url, "sha256": sha256(raw)})
            status, classification = classify_cover(raw, symbol)
            return {**evidence, **classification, "status": status, "filing_date": filed,
                    "accession": accession, "reason": classification["classification"]}
        except ResearchDataError as exc:
            return {**evidence, "reason": exc.reason}
        except (ValueError, KeyError, TypeError, IndexError, UnicodeError) as exc:
            return {**evidence, "reason": "sec_evidence_malformed", "error_type": type(exc).__name__}
