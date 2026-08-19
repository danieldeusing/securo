"""FX rates from the European Central Bank's euro reference feed.

WHY THIS EXISTS ALONGSIDE OPENEXCHANGERATES
-------------------------------------------
It needs no account, no API key and no third party beyond the ECB itself, so
there is no credential to provision, rotate or leak — and nothing that stops
working when a free tier changes. For a household banking in euros the ECB
reference rate is also the one worth reconciling against: it is what European
banks and tax authorities quote, published once per working day around 16:00
CET.

THE REBASE, WHICH IS THE ONLY ARITHMETIC HERE
---------------------------------------------
`FxRateProvider` is defined as returning rates against USD — "how many of this
currency per 1 USD" — because that is what the fx_rates table stores. The ECB
publishes against EUR. So every rate goes through the USD leg:

    ecb[X]   = X per EUR          (what the feed says)
    ecb[USD] = USD per EUR        (the leg every conversion pivots on)

    X per USD = ecb[X] / ecb[USD]

EUR is not in the feed — it is the base, implicitly 1.0 — so it is added by
hand as 1 / ecb[USD]. Forgetting that leaves the household's home currency the
one currency with no rate, which fails silently: every EUR figure simply stops
converting.

A missing or zero USD leg is fatal rather than skipped. Dividing by it is the
whole method, and a feed without it would otherwise produce either an exception
halfway through a dict comprehension or, worse, a set of rates quietly rebased
on nothing.

WHY THE FEED IS SCANNED RATHER THAN PARSED
------------------------------------------
Python's stdlib XML parsers expand internal entities, which makes a hostile
document a denial of service (the "billion laughs" expansion); the fixes are a
third-party dependency or a hand-hardened parser, both of which cost more than
this feed is worth. The document is two element shapes deep, with no nesting to
track and no text content at all, so a scan cannot be confused by structure it
does not model. Both quote styles are accepted because attribute quoting is the
publisher's choice, not part of the contract.

This mirrors the approach the household ledger already used against the same
feed, deliberately: two readers of one source that disagree about how to read it
is a bug waiting for a day the publisher changes its quoting.
"""

import logging
import re
from datetime import date
from decimal import Decimal

import httpx

from app.providers.base import FxRateProvider

logger = logging.getLogger(__name__)

DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
# Ninety days of history in one document. The ECB's only other archive is a zip
# of the entire series back to 1999, which is a much larger download to answer a
# question about last Tuesday.
HISTORY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"

CUBE_DATE = re.compile(r"""<Cube\s+time=['"](\d{4}-\d{2}-\d{2})['"]""")
CUBE_RATE = re.compile(r"""<Cube\s+currency=['"]([A-Z]{3})['"]\s+rate=['"]([0-9.]+)['"]""")

# Enough to carry a currency worth a fraction of a cent against the dollar
# without the rate itself becoming the rounding error. The column holds 10.
QUANTUM = Decimal("0.0000000001")


def _rebase_to_usd(per_eur: dict[str, Decimal]) -> dict[str, Decimal]:
    """ECB's per-EUR rates -> per-USD, the unit fx_rates stores. -> dict"""
    usd_per_eur = per_eur.get("USD")
    if not usd_per_eur:
        raise ValueError(
            "ECB feed carried no USD rate — every rate here is rebased through "
            "it, so there is nothing to compute and nothing safe to assume"
        )
    rates = {
        code: (rate / usd_per_eur).quantize(QUANTUM)
        for code, rate in per_eur.items()
    }
    # EUR is the feed's base and therefore absent from it. Without this the home
    # currency is the one that never converts.
    rates["EUR"] = (Decimal(1) / usd_per_eur).quantize(QUANTUM)
    return rates


def _scan(document: str) -> dict[str, dict[str, Decimal]]:
    """-> {date: {currency: rate per EUR}} for every dated Cube in the feed.

    The daily feed carries one date and the 90-day feed carries many, so both
    are read the same way and the caller picks. Rates are attributed to the
    dated Cube they follow, which is the document's only structure.
    """
    by_date: dict[str, dict[str, Decimal]] = {}
    positions = [(m.start(), m.group(1)) for m in CUBE_DATE.finditer(document)]
    for index, (start, day) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(document)
        by_date[day] = {
            code: Decimal(rate) for code, rate in CUBE_RATE.findall(document[start:end])
        }
    return by_date


class EcbProvider(FxRateProvider):
    """Euro foreign-exchange reference rates, published by the ECB."""

    @property
    def name(self) -> str:
        return "ecb"

    async def _get(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    async def fetch_latest(self) -> dict[str, Decimal]:
        by_date = _scan(await self._get(DAILY_URL))
        if not by_date:
            raise ValueError("ECB daily feed carried no dated rates")
        # Its own date, not today's. The feed is published on working days and
        # repeats the last one over a weekend, so "the newest thing published"
        # is the only honest reading.
        newest = max(by_date)
        return _rebase_to_usd(by_date[newest])

    async def fetch_historical(self, target_date: date) -> dict[str, Decimal]:
        by_date = _scan(await self._get(HISTORY_URL))
        wanted = target_date.isoformat()
        # The ECB publishes on working days only. A Saturday, a Sunday or a
        # holiday has no rate of its own, and the rate in force on that day is
        # the last one published before it — which is what a bank would have
        # used to settle. Falling forward instead would price a transaction
        # with a rate that did not yet exist when it happened.
        available = [day for day in by_date if day <= wanted]
        if not available:
            raise ValueError(
                f"ECB 90-day feed has no rate on or before {wanted} — it reaches "
                f"back only to {min(by_date) if by_date else 'nothing'}"
            )
        return _rebase_to_usd(by_date[max(available)])
