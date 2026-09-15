# thebundl pipeline requirements

## Scope and operating rules

- Discover food-deal sources automatically with the Brave Search API.
- Cover a two-mile straight-line radius around both Baruch College's main campus
  and Columbia University's campus in New York City. Store verified campus
  coordinates in configuration.
- Run source discovery every 14 days and collection once per day. A run first
  performs discovery when it is due, then collects sources.
- Prefer aggregators and pages containing multiple local deals. Reuse known
  sources and deduplicate them before collection.
- Extract only HTML text, links, and embedded structured data. Do not download
  images, use OCR, videos, PDFs, browser rendering, a manual approval UI, deal
  hiding, or deletion.
- Groq is the default AI provider. Keep it behind a swappable adapter for a
  future provider selection.
- Insert candidates automatically into the separate test Supabase project only
  after evidence, location, and duplicate checks pass.
- Aim for 10 distinct new deals per week and report the actual count. Never
  invent deals or loosen validation to meet that target.
- Never print API keys and never commit `.env`.
