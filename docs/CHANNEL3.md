# Channel3: facts and the decision

Researched on 9 November 2026 from Channel3's public documentation and terms. Nothing was signed up for and no key was requested or entered anywhere.

## Decision: use it as a market price reference, nothing else

Sri signed up for a key. The first reading of this research said to skip Channel3, because a retailer product cannot be bought through the sandbox order. That still holds for a shopping flow. It does not hold for a price reference, which needs no purchase from Channel3: before the buyer agent buys, `clearwake/market.py` asks Channel3 for the typical retail price of the item, and the mandate refuses or flags an order whose price is far above it (owner rule `max_over_market_percent`, wired in by the buyer module). That changes a real outcome: an order is refused or flagged. Nothing else uses Channel3. No product links are shown, and the catalog is not browsed.

Interface (agent B wires it into the mandate check):

`price_check(query, our_price_minor, currency="USD", tolerance_percent=None, transport=None, usage_path=None) -> MarketCheck`

The result has `reference_minor` (median of up to 5 products' offers in that currency, or None), `source_domain`, `title`, `brand`, `within_tolerance` (True, False, or None when there is no reference or no tolerance; None means flag, not refuse), `credits_used`, `note`, `ts_ms`. `to_receipt_params()` returns only these compact fields.

## Usage rules (enforced in code and tests)

- The key lives only in the environment variable `CHANNEL3_API_KEY` (from the ignored `.env`). It is never printed, logged, cached, or put in a receipt or error.
- `CHANNEL3_MAX_CALLS` is a hard cap on live calls per calendar month (UTC). It defaults to 0: every live call is refused until Sri raises it in `.env`. The free tier is 1000 credits a month; one search is one credit.
- `data/channel3-usage.json` records every live call with its timestamp, before it is sent. It also holds the 24 hour cache of compact results (price, domain, title, brand per query), so one query never costs twice. No catalog is stored.
- No retries. A 401, 402, 429, 5xx, timeout or bad reply ends the check with a note, and the credit is counted as spent.
- Dry run first: `python scripts/market_check.py --plan` prints the live queries and the credit cost and makes no call. `--live` runs them and refuses unless the cap allows it. Planned run: the six catalog products, 6 credits.
- Tests use a local transport only. No test and no agent makes a live call; Sri decides.

## Terms that apply

- Do not publish Channel3 benchmark or evaluation results without written consent. Public run summaries say only: price reference used: yes, N calls. No reference prices, no comparisons, no accuracy claims.
- Where a Channel3 product link is shown in any UI, put this exact text next to it: "Channel3 may earn a commission on purchases made through links shown here." (`market.DISCLOSURE`). The current design shows no link, so no UI needs it yet.
- Do not share the key, do not cache or store a significant part of the output, do not train on it.
- On the Devpost form, Channel3 may be ticked only if Sri has run the live check and the mandate step is part of the recorded video.

## Facts

| Question | Answer | Source |
| --- | --- | --- |
| Is a free developer key available? | Yes. The pricing page says 1000 free credits every month, then USD 0.007 per credit. Search costs one credit. The key goes in the `x-api-key` header. Getting a key needs an account at channel3.ai (a login step for Sri). | https://channel3.ai/docs/pricing.md |
| Can a hackathon use it? | Nothing in the terms excludes it, and nothing mentions hackathons. The licence to build and operate applications is described as revocable. | https://channel3.ai/terms |
| Does the catalog work for a video? | Yes, search works across the US, UK, Canada, Australia and much of Europe. Results are real retailer products with a merchant product page URL, a price and a currency. | https://channel3.ai/docs/api-reference/v1/search.md |
| Search call | `POST https://api.trychannel3.com/v1/search` with `query`, optional `limit` (1 to 30) and `filters`. Response: `products[]` with `id`, `title`, `offers[]` (`url`, `domain`, `price.price`, `price.currency`, `availability`). | same |
| Rate limits | None stated on the pricing page. The terms require following the documentation and any limits, and allow throttling or revoking access. | pricing page, terms |
| Restrictions that matter | Do not cache or store a significant portion of the catalog or of the output. Do not publish benchmark or evaluation results without written consent. Show a commission disclosure near product links. Do not share the key. Do not use output to train models. | terms, sections 6 to 9 |
| How Channel3 earns | A commission on sales made through its buy links (FAQ: a default take rate of 50 percent that falls as referred sales grow). | https://docs.trychannel3.com/faq |
| Agent payments | The pricing page mentions that agents can pay through MPP without a key. Not examined further. | pricing page |
