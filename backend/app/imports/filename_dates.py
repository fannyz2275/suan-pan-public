"""Heuristic statement-date detector for uploaded filenames.

Used as a fallback when the Gemini parser can't extract a `statement_date`
from the file's contents. We deliberately keep the patterns conservative —
a wrong date here lets a stale upload silently overwrite a newer balance,
which is exactly what the snapshot guard is meant to prevent.

Patterns recognized (US-centric):
  - YYYY-MM-DD  e.g. "statement-2024-03-15.pdf"
  - YYYY-MM     e.g. "chase_2024_03.pdf"  -> end of month
  - MM-DD-YYYY  e.g. "stmt-03-15-2024.pdf"
  - MMDDYYYY    e.g. "eStmt_03152024.pdf"
  - MonYYYY     e.g. "Mar2024.pdf"        -> end of month
  - QnYYYY      e.g. "2024_Q1_brokerage.csv" -> last day of quarter

All matches return the *closing* day of the period (end-of-month or
end-of-quarter for partial dates), since statements close at period end.
Returns None if nothing matches; callers must treat that as "no signal".
"""

from __future__ import annotations

import calendar
import re
from datetime import date

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Order matters: longer/more-specific patterns first so we don't match a
# YYYY-MM prefix of a YYYY-MM-DD string.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ymd", re.compile(r"(?<!\d)(20\d{2})[-_./]?(0[1-9]|1[0-2])[-_./]?(0[1-9]|[12]\d|3[01])(?!\d)")),
    ("mdy", re.compile(r"(?<!\d)(0[1-9]|1[0-2])[-_./](0[1-9]|[12]\d|3[01])[-_./](20\d{2})(?!\d)")),
    ("mdy_compact", re.compile(r"(?<!\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(20\d{2})(?!\d)")),
    ("ym", re.compile(r"(?<!\d)(20\d{2})[-_./](0[1-9]|1[0-2])(?!\d)")),
    ("monname", re.compile(r"(?<![a-z])(jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*[-_. ]*?(20\d{2})(?!\d)", re.I)),
    ("quarter", re.compile(r"(?<!\d)(20\d{2})[-_. ]?Q([1-4])(?!\d)", re.I)),
    ("quarter_alt", re.compile(r"(?<![a-z])Q([1-4])[-_. ]?(20\d{2})(?!\d)", re.I)),
]


def _eom(year: int, month: int) -> date:
    """End-of-month date for (year, month)."""
    return date(year, month, calendar.monthrange(year, month)[1])


def _eoq(year: int, quarter: int) -> date:
    """End-of-quarter date for (year, q in 1..4)."""
    end_month = quarter * 3
    return _eom(year, end_month)


def parse_statement_date_from_filename(filename: str | None) -> date | None:
    if not filename:
        return None
    # Strip path and extension; the date is almost always in the basename.
    base = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    for kind, pat in _PATTERNS:
        m = pat.search(base)
        if not m:
            continue
        try:
            if kind == "ymd":
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if kind in ("mdy", "mdy_compact"):
                return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            if kind == "ym":
                return _eom(int(m.group(1)), int(m.group(2)))
            if kind == "monname":
                month = _MONTHS.get(m.group(1).lower()[:4]) or _MONTHS[m.group(1).lower()[:3]]
                return _eom(int(m.group(2)), month)
            if kind == "quarter":
                return _eoq(int(m.group(1)), int(m.group(2)))
            if kind == "quarter_alt":
                return _eoq(int(m.group(2)), int(m.group(1)))
        except (ValueError, KeyError):
            # Bad match (e.g. Feb 30) — keep looking.
            continue
    return None
