# -*- coding: utf-8 -*-
"""Mercado Spy — constantes de geo/idioma (Semrush, DataForSEO, Meta, ScrapingBee).

SPY_MARKET=us|br (default us). Lido no import — subprocessos do pipeline
devem setar SPY_MARKET no env antes de iniciar o script.
"""

from __future__ import annotations

import os


def _normalize_market(raw: str) -> str:
    m = (raw or "us").strip().lower()
    if m in ("br", "brazil", "brasil", "bra"):
        return "br"
    if m in ("us", "usa", "united_states", "united-states", "estados_unidos"):
        return "us"
    return "us"


MARKET = _normalize_market(os.environ.get("SPY_MARKET") or "us")

if MARKET == "br":
    SEMRUSH_DB = "br"
    LOCATION_CODE = 2076  # Brazil (DataForSEO)
    LANGUAGE_CODE = "pt"
    SCRAPINGBEE_COUNTRY = "br"
    META_COUNTRY = "BR"
    ACCEPT_LANGUAGE = "pt-BR,pt;q=0.9,en;q=0.8"
    MARKET_LABEL = "Brazil (br)"
    MARKET_SHORT = "BR"
    HTML_LANG = "pt-BR"
    CURRENCY_PREFIX = "R$"
    DEFAULT_TLD = ".com.br"
    GOOGLE_ADS_REGION = "BR"
else:
    SEMRUSH_DB = "us"
    LOCATION_CODE = 2840  # United States
    LANGUAGE_CODE = "en"
    SCRAPINGBEE_COUNTRY = "us"
    META_COUNTRY = "US"
    ACCEPT_LANGUAGE = "en-US,en;q=0.9"
    MARKET_LABEL = "United States (us)"
    MARKET_SHORT = "US"
    HTML_LANG = "en-US"
    CURRENCY_PREFIX = "$"
    DEFAULT_TLD = ".com"
    GOOGLE_ADS_REGION = "US"

# Estimated spend per active ad (local currency) for ranking tables
META_ADS_COST_PER_AD = 80 if MARKET == "us" else 250
ADS_COST_PER_AD = 200 if MARKET == "us" else 600

# Aliases used by legacy code (name kept; value follows active market)
LOCATION_BRAZIL = LOCATION_CODE  # noqa: N816
LOCATION_US = LOCATION_CODE


def market_config(market: str | None = None) -> dict:
    """Snapshot of constants for a market (without reloading the module)."""
    m = _normalize_market(market or MARKET)
    if m == "br":
        return {
            "market": "br",
            "semrush_db": "br",
            "location_code": 2076,
            "language_code": "pt",
            "scrapingbee_country": "br",
            "meta_country": "BR",
            "market_label": "Brazil (br)",
            "market_short": "BR",
            "currency_prefix": "R$",
            "google_ads_region": "BR",
        }
    return {
        "market": "us",
        "semrush_db": "us",
        "location_code": 2840,
        "language_code": "en",
        "scrapingbee_country": "us",
        "meta_country": "US",
        "market_label": "United States (us)",
        "market_short": "US",
        "currency_prefix": "$",
        "google_ads_region": "US",
    }
