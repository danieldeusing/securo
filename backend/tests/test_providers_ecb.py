"""Tests for the ECB euro reference-rate provider.

The feed is never fetched here. Every trap this provider can fall into is in
the arithmetic and in the shape of the document, and both are exercised against
literal XML — so these run offline, deterministically, and still fail for the
reasons that matter.

What is worth testing is what would produce a plausible WRONG number rather
than an error: a rebase inverted, the home currency missing, a weekend priced
with a rate that did not exist yet, or rates attributed to the wrong day of a
multi-day document. None of those raise. They just quietly misstate what the
household is worth.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.providers.ecb import EcbProvider, _rebase_to_usd, _scan


# 1 EUR = 1.1605 USD = 6.0394 BRL, the ECB's own figures for 2026-08-19.
DAILY = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01">
  <Cube>
    <Cube time='2026-08-19'>
      <Cube currency='USD' rate='1.1605'/>
      <Cube currency='BRL' rate='6.0394'/>
      <Cube currency='GBP' rate='0.8621'/>
    </Cube>
  </Cube>
</gesmes:Envelope>"""

# Newest first, as the ECB publishes it. Friday then Thursday — the weekend in
# between has no rate of its own, which is the point of the gap.
HISTORY = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01">
  <Cube>
    <Cube time="2026-08-17">
      <Cube currency="USD" rate="1.1700"/>
      <Cube currency="BRL" rate="6.1000"/>
    </Cube>
    <Cube time="2026-08-14">
      <Cube currency="USD" rate="1.1500"/>
      <Cube currency="BRL" rate="6.0000"/>
    </Cube>
  </Cube>
</gesmes:Envelope>"""


def test_rates_are_rebased_from_euro_onto_the_dollar():
    """The table stores "how many X per 1 USD"; the ECB publishes per EUR.

    Inverting this is the mistake that matters: it produces a full set of
    rates, every conversion succeeds, and every figure is wrong by the square
    of the dollar rate.
    """
    rates = _rebase_to_usd(_scan(DAILY)["2026-08-19"])
    # 6.0394 BRL per EUR / 1.1605 USD per EUR = 5.20413... BRL per USD
    assert rates["BRL"] == Decimal("5.2041361482")
    assert rates["USD"] == Decimal("1")


def test_the_euro_gets_a_rate_even_though_the_feed_omits_it():
    """EUR is the feed's base, so it never appears as a Cube.

    Without this the household's home currency is the single currency with no
    rate — every euro figure silently stops converting.
    """
    rates = _rebase_to_usd(_scan(DAILY)["2026-08-19"])
    assert rates["EUR"] == Decimal("0.8616975442")     # 1 / 1.1605


def test_a_feed_without_the_dollar_leg_is_refused():
    """Every rate is rebased through USD, so its absence is not recoverable.

    Skipping it would emit rates rebased on nothing, which is worse than
    failing: the sync would report success and store garbage.
    """
    with pytest.raises(ValueError, match="no USD rate"):
        _rebase_to_usd({"BRL": Decimal("6.0394")})


def test_each_day_keeps_its_own_rates_in_a_multi_day_feed():
    """The 90-day feed carries 60-odd dates in one document.

    Collapsing them — the obvious way, and the one a dict of all matches
    produces — attributes one day's rates to every other day.
    """
    by_date = _scan(HISTORY)
    assert set(by_date) == {"2026-08-17", "2026-08-14"}
    assert by_date["2026-08-17"]["BRL"] == Decimal("6.1000")
    assert by_date["2026-08-14"]["BRL"] == Decimal("6.0000")


def test_both_attribute_quote_styles_are_read():
    """Quoting is the publisher's choice, not part of the contract."""
    assert _scan(DAILY)["2026-08-19"]["USD"] == Decimal("1.1605")   # single quotes
    assert _scan(HISTORY)["2026-08-17"]["USD"] == Decimal("1.1700")  # double


class _OfflineEcb(EcbProvider):
    """The provider with the network removed, so the date logic can be tested."""

    def __init__(self, document):
        self._document = document

    async def _get(self, url):
        return self._document


@pytest.mark.asyncio
async def test_latest_reads_the_feeds_own_date_not_todays():
    """The ECB publishes on working days and repeats over a weekend.

    "The newest thing published" is the only honest reading; assuming today
    would claim a rate for a day the ECB never priced.
    """
    rates = await _OfflineEcb(DAILY).fetch_latest()
    assert rates["BRL"] == Decimal("5.2041361482")


@pytest.mark.asyncio
async def test_a_weekend_falls_back_to_the_last_published_rate():
    """Saturday has no rate. The rate in force is Friday's — the one a bank
    would have settled with. Falling FORWARD would price a transaction with a
    rate that did not exist when it happened."""
    saturday = await _OfflineEcb(HISTORY).fetch_historical(date(2026, 8, 15))
    friday = await _OfflineEcb(HISTORY).fetch_historical(date(2026, 8, 14))
    assert saturday == friday
    assert saturday["BRL"] == (Decimal("6.0000") / Decimal("1.1500")).quantize(
        Decimal("0.0000000001"))


@pytest.mark.asyncio
async def test_a_date_older_than_the_window_is_refused_not_guessed():
    """The 90-day feed reaches back 90 days. Older than that, the honest answer
    is that this provider cannot say — not the oldest rate it happens to hold."""
    with pytest.raises(ValueError, match="no rate on or before"):
        await _OfflineEcb(HISTORY).fetch_historical(date(2026, 1, 1))


class _TwoFeedEcb(EcbProvider):
    """Serves the 90-day feed and the full series separately, counting fetches."""

    def __init__(self, ninety, full):
        self._ninety, self._full, self.fetched = ninety, full, []

    async def _get(self, url):
        self.fetched.append(url)
        from app.providers.ecb import HISTORY_FULL_URL
        return self._full if url == HISTORY_FULL_URL else self._ninety


OLD = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01">
  <Cube>
    <Cube time="2026-08-17"><Cube currency="USD" rate="1.1700"/><Cube currency="BRL" rate="6.1000"/></Cube>
    <Cube time="2026-05-04"><Cube currency="USD" rate="1.1000"/><Cube currency="BRL" rate="5.5000"/></Cube>
  </Cube>
</gesmes:Envelope>"""


@pytest.mark.asyncio
async def test_a_date_older_than_the_window_falls_back_to_the_full_series():
    """This household's ledger opens three weeks before the 90-day feed starts.

    Failing there is not academic: the caller's fallback for "no rate" is a 1:1
    conversion, so a balance in reais is reported as the same number of euros.
    """
    provider = _TwoFeedEcb(HISTORY, OLD)
    rates = await provider.fetch_historical(date(2026, 5, 6))
    # 2026-05-04's rate, the last published on or before the 6th.
    assert rates["BRL"] == (Decimal("5.5000") / Decimal("1.1000")).quantize(
        Decimal("0.0000000001"))
    assert len(provider.fetched) == 2      # short feed first, then the full one


@pytest.mark.asyncio
async def test_the_full_series_is_not_fetched_when_the_short_feed_suffices():
    """7.8 MB against 69 KB. The common question is about last Tuesday."""
    provider = _TwoFeedEcb(HISTORY, OLD)
    await provider.fetch_historical(date(2026, 8, 17))
    assert len(provider.fetched) == 1
