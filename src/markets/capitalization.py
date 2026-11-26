"""Market caps are keyed by exchange contract identity, never by a guessed ticker."""

import logging
import os
from contextlib import closing
from datetime import datetime
from urllib.parse import urlencode
from urllib.error import HTTPError

from . import providers as api
from .metrics import number

HOUR = 3600000
EXCHANGE = {"binance": "binance_futures", "hyperliquid": "hyperliquid"}
# Verified US-listed company instruments; index, ETF, leveraged and commodity
# underlyings are not company caps. Profiles must also match ticker AND currency.
EQUITIES = dict(
    nvidia="NVDA",
    apple="AAPL",
    tesla="TSLA",
    microsoft="MSFT",
    amazon="AMZN",
    amd="AMD",
    intel="INTC",
    coinbase="COIN",
    broadcom="AVGO",
    oracle="ORCL",
    costco="COST",
    adobe="ADBE",
    abbvie="ABBV",
    accenture="ACN",
    amgen="AMGN",
    caterpillar="CAT",
    corning="GLW",
    ciena="CIEN",
    coherent="COHR",
    dell="DELL",
    disney="DIS",
    draftkings="DKNG",
    gamestop="GME",
    gopro="GPRO",
    gitlab="GTLB",
    ibm="IBM",
    ionq="IONQ",
    lumentum="LITE",
    mongodb="MDB",
    moderna="MRNA",
    cloudflare="NET",
    salesforce="CRM",
    crowdstrike="CRWD",
    coreweave="CRWV",
    **{
        "alphabet-class-a": "GOOGL",
        "meta-platforms": "META",
        "micron-technology": "MU",
        "palantir": "PLTR",
        "palantir-technologies": "PLTR",
        "applied-materials": "AMAT",
        "bank-of-america": "BAC",
        "goldman-sachs": "GS",
        "robinhood-markets": "HOOD",
        "cisco-systems": "CSCO",
        "interactive-brokers-group": "IBKR",
        "jpmorgan-chase": "JPM",
        "eli-lilly": "LLY",
        "johnson-johnson": "JNJ",
        "coca-cola": "KO",
        "home-depot": "HD",
        "lam-research": "LRCX",
        "ge-vernova": "GEV",
        "marvell-technology": "MRVL",
    },
)


def contract_ids(venue, tickers):
    found = {}
    bad = set()
    for r in tickers:
        if r.get("contract_type") != "perpetual":
            continue
        symbol = r.get("symbol") if venue == "binance" else r.get("base")
        if not isinstance(symbol, str):
            continue
        symbol = symbol.upper()
        info = None
        if r.get("coin_id"):
            info = ("CoinGecko", r["coin_id"])
        elif r.get("rwa_id") in EQUITIES:
            info = ("Finnhub", EQUITIES[r["rwa_id"]])
        if symbol in found and found[symbol] != info:
            bad.add(symbol)
        found[symbol] = info
    return {s: x for s, x in found.items() if x and s not in bad}


class MarketCaps:
    def __init__(self, db, stop):
        self.db, self.stop = db, stop
        self.enabled = os.getenv("SCREENIT_MARKET_CAP", "1") != "0"
        with closing(db()) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS market_caps(venue TEXT,symbol TEXT,usd REAL,ts INTEGER,source TEXT,sourceId TEXT,PRIMARY KEY(venue,symbol)) WITHOUT ROWID"
            )
            if "sourceId" not in {
                r[1] for r in c.execute("PRAGMA table_info(market_caps)")
            }:
                c.execute("ALTER TABLE market_caps ADD COLUMN sourceId TEXT")
            rows = (
                list(
                    c.execute(
                        "SELECT venue,symbol,usd,ts,source,sourceId FROM market_caps WHERE ts>? AND sourceId IS NOT NULL",
                        (api.now() - 2 * HOUR,),
                    )
                )
                if self.enabled
                else []
            )
            self.values = {(v, s): (usd, t, src) for v, s, usd, t, src, _ in rows}
            self.identities = {(v, s): (src, i) for v, s, _, _, src, i in rows}

    def update(self):
        ids = {}
        failed = set()
        key = os.getenv("SCREENIT_COINGECKO_KEY", "")
        headers = {"x-cg-demo-api-key": key} if key else {}

        def cg(path):
            return api.request(
                "https://api.coingecko.com/api/v3/" + path, headers=headers
            )

        for v, exchange in EXCHANGE.items():
            if self.stop.is_set():
                return
            try:
                ids[v] = contract_ids(
                    v,
                    cg("derivatives/exchanges/" + exchange + "?include_tickers=all")[
                        "tickers"
                    ],
                )
            except (OSError, ValueError, KeyError, TypeError):
                failed.add(v)
        wanted = set(pair for x in ids.values() for pair in x.values())
        values = {}
        unavailable = set()
        coins = sorted(i for source, i in wanted if source == "CoinGecko")
        for i in range(0, len(coins), 200):
            if self.stop.is_set():
                return
            group = coins[i : i + 200]
            try:
                result = cg(
                    "coins/markets?"
                    + urlencode(
                        dict(
                            vs_currency="usd", ids=",".join(group), per_page=250, page=1
                        )
                    )
                )
                for r in result:
                    val = number(r.get("market_cap"))
                    ts = r.get("last_updated")
                    if r.get("id") in group and val and val > 0 and ts:
                        values["CoinGecko", r["id"]] = (
                            val,
                            int(
                                datetime.fromisoformat(
                                    ts.replace("Z", "+00:00")
                                ).timestamp()
                                * 1000
                            ),
                        )
            except (OSError, ValueError, KeyError, TypeError):
                unavailable.update(("CoinGecko", coin) for coin in group)
            if self.stop.wait(2.1):
                return
        token = os.getenv("SCREENIT_FINNHUB_KEY", "")
        if token:
            for source, symbol in sorted(wanted):
                if source != "Finnhub":
                    continue
                if self.stop.is_set():
                    return
                try:
                    r = api.request(
                        "https://finnhub.io/api/v1/stock/profile2?"
                        + urlencode({"symbol": symbol}),
                        headers={"X-Finnhub-Token": token},
                    )
                    val = number(r.get("marketCapitalization"))
                    if (
                        r.get("ticker") == symbol
                        and r.get("currency") == "USD"
                        and val
                        and val > 0
                    ):
                        values[source, symbol] = (val * 1e6, api.now())
                except HTTPError as e:
                    unavailable.add((source, symbol))
                    if e.code in (401, 403, 429):
                        unavailable.update(
                            pair for pair in wanted if pair[0] == "Finnhub"
                        )
                        break
                except (OSError, ValueError, TypeError):
                    unavailable.add((source, symbol))
                if self.stop.wait(1.2):
                    return
        # Publish one immutable generation. Retain recent good values on transport failure.
        old = self.values
        new = {(v, s): p for (v, s), p in old.items() if v in failed}
        identities = {k: self.identities[k] for k in new}
        for v, mapping in ids.items():
            for s, pair in mapping.items():
                if pair in values:
                    new[v, s] = (*values[pair], pair[0])
                elif pair in unavailable and self.identities.get((v, s)) == pair:
                    new[v, s] = old[v, s]
                identities[v, s] = pair
        new = {k: p for k, p in new.items() if -30000 <= api.now() - p[1] <= 2 * HOUR}
        with closing(self.db()) as c, c:
            c.execute("DELETE FROM market_caps")
            c.executemany(
                "INSERT INTO market_caps VALUES(?,?,?,?,?,?)",
                [(*k, *p, identities[k][1]) for k, p in new.items()],
            )
        self.identities = {k: identities[k] for k in new}
        self.values = new

    def run(self):
        while self.enabled and not self.stop.is_set():
            try:
                self.update()
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "Market cap refresh: %s", type(e).__name__
                )
            self.stop.wait(3600 if self.values else 300)
