# Channel3: facts and the decision

Researched on 9 November 2026 from Channel3's public documentation and terms. Nothing was signed up for and no key was requested or entered anywhere.

## Decision: skip

Channel3 would sit in front of the buyer agent's mandate check. In Clearwake the purchase that follows the mandate check is a PayPal sandbox order against the one sandbox merchant this app owns. Channel3 returns real products from real retailers (100 million items across many stores), each with the retailer's own product page as the buy link. A product from Channel3 therefore cannot be bought through our sandbox order: the order would name an item from a catalog that the sandbox merchant does not sell. Putting the search in front of the check would change what is shown, not what happens. It would not change a single outcome in the dispute path, which is what the product is about.

Using it anyway would also mean a shopping flow that sends the buyer to a retailer's page, outside PayPal's sandbox. The hackathon rules ask for a working PayPal build that judges can run, and a flow that leaves the sandbox cannot be run or checked by them.

So: no integration, no Channel3 prize entry. On the Devpost form, Channel3 is not ticked.

## Facts

| Question | Answer | Source |
| --- | --- | --- |
| Is a free developer key available? | Yes. The pricing page says 1000 free credits every month, then USD 0.007 per credit. Search costs one credit. The key goes in the `x-api-key` header. Getting a key needs an account at channel3.ai (a login step for Sri). | https://channel3.ai/docs/pricing.md |
| Can a hackathon use it? | Nothing in the terms excludes it, and nothing mentions hackathons. The licence to build and operate applications is described as revocable. | https://channel3.ai/terms |
| Does the catalog work for a demo? | Yes, search works across the US, UK, Canada, Australia and much of Europe. Results are real retailer products with a merchant product page URL, a price and a currency. | https://channel3.ai/docs/api-reference/v1/search.md |
| Search call | `POST https://api.trychannel3.com/v1/search` with `query`, optional `limit` (1 to 30) and `filters`. Response: `products[]` with `id`, `title`, `offers[]` (`url`, `domain`, `price.price`, `price.currency`, `availability`). | same |
| Rate limits | None stated on the pricing page. The terms require following the documentation and any limits, and allow throttling or revoking access. | pricing page, terms |
| Restrictions that matter | Do not cache or store a significant portion of the catalog or of the output. Do not publish benchmark or evaluation results without written consent. Show a commission disclosure near product links. Do not share the key. Do not use output to train models. | terms, sections 6 to 9 |
| How Channel3 earns | A commission on sales made through its buy links (FAQ: a default take rate of 50 percent that falls as referred sales grow). | https://docs.trychannel3.com/faq |
| Agent payments | The pricing page mentions that agents can pay through MPP without a key. Not examined further. | pricing page |

## Why not "integrate anyway for the prize"

The sponsor rule in this project is that every tool has a real step. A Channel3 step here would be a search box whose result nobody can buy in the sandbox. The terms would also add work for no outcome: a commission disclosure next to every product link, and a ban on publishing evaluation results without written consent, while Clearwake publishes the numbers of its runs.

## If this changes

If a later version of the buyer agent buys from real retailers through PayPal, the integration is one function: search Channel3, pass the chosen offer to the existing mandate check, which already compares the price with the per item cap, the budget and the allowed categories. The cost then is one credit per search. Until then it stays out.
