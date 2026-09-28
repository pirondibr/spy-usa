# -*- coding: utf-8 -*-
"""Mercado Spy USA — constantes de geo/idioma (Semrush, DataForSEO, Meta, ScrapingBee)."""

from __future__ import annotations

import os

MARKET = (os.environ.get("SPY_MARKET") or "us").strip().lower()
if MARKET not in ("us", "usa", "united_states"):
    MARKET = "us"

# Semrush Organic Research database
SEMRUSH_DB = "us"

# DataForSEO location / language
LOCATION_CODE = 2840  # United States
LANGUAGE_CODE = "en"

# ScrapingBee proxy country
SCRAPINGBEE_COUNTRY = "us"

# Meta Ads Library
META_COUNTRY = "US"

# HTTP Accept-Language
ACCEPT_LANGUAGE = "en-US,en;q=0.9"

# Report / UI
MARKET_LABEL = "United States (us)"
HTML_LANG = "en-US"
CURRENCY_PREFIX = "$"
DEFAULT_TLD = ".com"

# Estimated spend per active Meta ad (USD) for ranking tables
META_ADS_COST_PER_AD = 80
ADS_COST_PER_AD = 200

# Aliases used by legacy BR code
LOCATION_BRAZIL = LOCATION_CODE  # noqa: N816 — kept so imports do not break
LOCATION_US = LOCATION_CODE
