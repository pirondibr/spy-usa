# Spy USA

Marketing analysis for **US** companies: SEO, Brand, Meta Ads Library, Instagram, YouTube, TikTok, SimilarWeb.

HTML tables only (no chatbot). Adapted from [radar-agent-demo](https://github.com/pirondibr/radar-agent-demo) with market filters:

- Semrush DB `us`
- DataForSEO location `2840` / language `en`
- Meta Ads Library `country=US`
- ScrapingBee `country_code=us`
- SimilarWeb via RapidAPI (`SIMILARWEB_RAPIDAPI_KEY`)

## Local

```bash
cp .env.example .env   # or reuse keys from radar-agent-demo/.env
pip install -r requirements.txt
python server.py
```

Open http://127.0.0.1:8770 — first test: `semrush.com`

## Render

New Blueprint from this folder (`render.yaml`). Set the five API keys. Do **not** deploy inside the Meta Ads Next.js service.

## API

- `GET /api/hello` — readiness
- `POST /api/analyze` — `{ "url": "semrush.com", "force": false }`
- `GET /api/jobs/:id/stream` — SSE progress
- `GET /runs/:id/report.html` — tables report
