# Restart report source notes

Checked October 10, 2026 by the root's read-only provider researcher. These are research leads and published terms, not purchased entitlements or project-specific written permission. The report preserves separate public display, local storage, retention, attribution and model-processing gates.

## Repository evidence

- [README](../../../README.md): public-safe output, entity status, ranking and product purpose
- [Canonical tracker](../../agents/issue-tracker.md): milestone acceptance and external blockers
- [M7 record](../../milestone-7.md): offline synthesis, disclosure hardening and semantic limits
- [Fresh engineering evidence](../../restart-engineering-2026-10-10.md): frozen source `1b535a1`, 212 offline tests, independent review and loopback API checks
- [Deployment runbook](../../../deploy/README.md): one VM, systemd, Caddy and local SQLite, prepared but not deployed
- [Unsent requests](../../provider-permission-requests.md): provider questions prepared for user review

## Football

- football-data.org: [pricing](https://www.football-data.org/pricing), [coverage](https://www.football-data.org/coverage), [registration terms](https://www.football-data.org/client/register)
- Sportmonks: [coverage](https://www.sportmonks.com/football-api/coverage/), [pricing](https://www.sportmonks.com/football-api/plans-pricing/), [terms](https://www.sportmonks.com/terms-of-service/)
- API-Football: [pricing](https://www.api-football.com/pricing/), [terms](https://www.api-football.com/terms)

## NFL and golf

- SportsDataIO: [NFL](https://sportsdata.io/developers/api-documentation/nfl), [golf](https://sportsdata.io/developers/api-documentation/golf), [licensing questions](https://sportsdata.io/help/data-rights-and-licensing-questions)
- Sportradar: [NFL v7](https://developer.sportradar.com/football/reference/nfl-overview), [golf](https://developer.sportradar.com/golf/reference/golf-overview)
- BALLDONTLIE: [NFL endpoints and subscription tiers](https://nfl.balldontlie.io/), [terms](https://www.balldontlie.io/terms.html). Third-party IP responsibility and cadence remain unresolved for this project
- Data Golf: [API](https://datagolf.com/api-access), [subscription](https://datagolf.com/subscribe), [terms](https://datagolf.com/terms-and-conditions). Assessed but excluded from public redistribution

## News

- SportsDataIO / RotoBaller: [NFL news endpoints](https://sportsdata.io/developers/api-documentation/nfl), [licensing](https://sportsdata.io/help/data-rights-and-licensing-questions)
- AP Media API: [guide](https://api.ap.org/media/v/docs/Getting_Started_API.htm), [pricing model](https://api.ap.org/media/v/docs/Pricing.htm). Entity coverage and commercial display/processing rights require a quote and contract
- Guardian: [access tiers](https://open-platform.theguardian.com/access/), [terms](https://www.theguardian.com/open-platform/terms-and-conditions). Assessed and excluded from the planned automated/AI use

## Hosting

- DigitalOcean: [Droplet pricing](https://www.digitalocean.com/pricing/droplets), [region availability](https://docs.digitalocean.com/products/droplets/details/availability/), [backup pricing](https://docs.digitalocean.com/products/backups/details/pricing/)
- Hetzner: [price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/), [server overview](https://docs.hetzner.com/cloud/servers/overview/), [billing](https://docs.hetzner.com/cloud/billing/faq/). EU CX23 and Singapore CPX12 are different plans; do not transfer the EU price to Singapore
- Render: [pricing](https://render.com/pricing), [persistent disks](https://render.com/docs/disks), [cron jobs](https://render.com/docs/cronjobs). Separate cron services cannot mount the web service disk

Singapore's geographical fit for Korea is an inference. No latency benchmark was performed. Current checkout totals, tax and selected configuration must be verified before purchase.

## Optional AI vendors

- OpenAI: [`gpt-6-luna`](https://developers.openai.com/api/docs/models/gpt-6-luna), [data controls](https://developers.openai.com/api/docs/guides/your-data)
- Anthropic: [Haiku](https://www.anthropic.com/claude/haiku), [retention](https://privacy.anthropic.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)
- Google: [pricing](https://ai.google.dev/gemini-api/docs/pricing), [zero-retention terms](https://ai.google.dev/gemini-api/docs/zdr)

Research correction incorporated: use `gpt-6-luna` at $0.10/$0.50 per million standard short-context input/output tokens, not the earlier GPT-5.6 Luna reference. Google Gemini 3.7 Flash prices change January 1, 2027. Vendor comparison remains an optional synthetic-evidence experiment; no real model is integrated and no source facts are transmitted.

## Design evidence and synthetic data

The four preview items mirror the public CLI response generated with `SPORTS_BRIEFING_PUBLIC_MODE=true .venv/bin/python -m sports_briefing timeline --as-of 2026-10-10T12:00:00Z`: Texans availability change, Scottie recent result, Scottie future tee time and Texans future game. They retain ranking order and two items per entity. Arsenal is unavailable.

The revealed Scottie result in the HTML previews is separately invented design-only content, visibly labelled synthetic. It is not a captured provider result. Dates are frozen. The HTML does not fetch the API, run inference or write to an external service.
