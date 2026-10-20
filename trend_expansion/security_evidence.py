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


class CoverPage(HTMLParser):
    """Read inline XBRL facts, preserving class context and nested HTML text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.facts = []
        self.active = None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if self.active is not None:
            self.depth += 1
            return
        attrs = dict(attrs)
        name = attrs.get("name", "").lower()
        if tag in {"ix:nonnumeric", "ix:nonfraction"} and name.startswith("dei:"):
            # Continued/transformed facts require more evidence.
            if attrs.get("continuedat") or attrs.get("format"):
                return
            self.active = [name.split(":")[-1], attrs.get("contextref", ""), []]
            self.depth = 1

    def handle_endtag(self, tag):
        if self.active is not None:
            self.depth -= 1
            if self.depth == 0:
                name, context, text = self.active
                self.facts.append((name, context, " ".join("".join(text).split())))
                self.active = None

    def handle_data(self, data):
        if self.active is not None:
            self.active[2].append(data)


def classify_cover(payload: bytes, symbol: str) -> tuple[str, dict]:
    """Require matched class context, common title and explicit non-shell fact."""
    parser = CoverPage()
    parser.feed(payload.decode("utf-8"))
    shells = [text.lower() for name, _, text in parser.facts if name == "entityshellcompanyboolean"]
    if "true" in shells or "yes" in shells:
        return "not_common", {"classification": "shell_company"}
    if not shells or any(value not in {"false", "no"} for value in shells):
        return "unknown", {"classification": "shell_status_unknown"}
    contexts = {context for name, context, text in parser.facts
                if name == "tradingsymbol" and text.upper().replace(".", "-") == symbol.replace(".", "-")}
    titles = [text for name, context, text in parser.facts
              if name == "security12btitle" and context and context in contexts]
    if not titles:
        return "unknown", {"classification": "class_context_unmatched"}
    if any(_NONCOMMON.search(title) for title in titles):
        return "not_common", {"classification": "non_common_class", "class_titles": sorted(titles)}
    if not all(_COMMON.search(title) for title in titles):
        return "unknown", {"classification": "class_type_unknown", "class_titles": sorted(titles)}
    return "verified", {"classification": "operating_common_equity", "class_titles": sorted(titles)}


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
            matches = {int(row["cik_str"]) for row in self.mapping.values()
                       if row["ticker"].upper().replace(".", "-") == symbol.replace(".", "-")}
            if len(matches) != 1:
                return {**evidence, "reason": "sec_cik_unknown"}
            cik = matches.pop()
            if not 0 < cik < 10_000_000_000:
                raise ResearchDataError("sec_cik_invalid")
            url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
            raw = self.cache.get_asof(url, self.asof_date)
            evidence["sources"].append({"url": url, "sha256": sha256(raw)})
            submission = json.loads(raw)
            if int(submission["cik"]) != cik:
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
