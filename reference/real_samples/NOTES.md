# Real-sample grounding notes (GHCC judgment listing)

Source: `https://nl.const-court.be/judgments?year=2026&month=7`, captured
2026-08-16 via browser "View Source". Raw excerpt saved as
[listing_2026-07_nl.html](listing_2026-07_nl.html) (decorative markup
trimmed; see the comment at the top of that file for exactly what was
removed and why).

## What this confirmed

`src/ingestion/discover.py`'s `parse_listing_html` was re-derived from this
kind of real markup (Vuetify `judgment-card` divs on the server-rendered
Nuxt 3 listing page) rather than from the legacy `/a/{number}/{year}`
info-card route. Running it against the real capture
(`tests/ingestion/test_discover.py::test_parse_real_sample_*`) confirms it
handles, deterministically and without any special-casing:

- Guillemet-quoted law titles (`« ... »`) in the controlled norm.
- Dash-joined multiple role numbers (`"8411 - 8412"` → `"8411, 8412"`).
- `<br>`-separated bulleted outcome text (arr-89-2026 has four `- ...`
  bullets in one `text-emphasis` div) — `get_text(separator=" ")` joins
  them into one readable string without needing `<br>`-specific handling.
- A "Persbericht" (press release) link sitting between the keywords div and
  the ECLI-toggle button (arr-91-2026, arr-89-2026) does not get picked up
  by, or corrupt, any of the field lookups, since each field is found by
  its own specific class/label rather than by position.

## Known gaps (not yet modeled)

- **Press release links** (`<a href="/public/{lang}/{year}/{slug}-info.pdf">Persbericht</a>`)
  are present on some cards and are not captured by `DiscoveredRuling` or
  `CaseMetadata`. Not required by anything downstream today; flagged here
  so a future "link to press release" feature doesn't need to re-discover
  this markup shape.
- **ECLI** never appears in the listing page HTML — only a toggle button
  labelled "ECLI" with no value (its actual value is presumably fetched
  client-side after hydration). This matches the existing pipeline design:
  ECLI is extracted from the downloaded PDF's footer instead
  (`extract.extract_ecli`), not from the listing.
- The 88/2026 card in the source capture was cut off mid-attribute by a
  50k-character paste limit before its role number/keywords/outcome divs
  were visible, so it was left out of the saved sample entirely rather than
  reconstructed from a partial capture.

## `tests/ingestion/fixtures/info_card_sample.html` is NOT grounded

That fixture (and `discover.parse_info_card` / `_find_labeled_value`, which
it exercises) models a `<dl class="arrest-metadata">` definition-list
structure that was never confirmed against a real page — it predates this
grounding pass. `discover.py`'s own module docstring already flags
`parse_info_card` as "kept for historical reference; the pipeline now uses
`parse_listing_html` instead" (`src/ingestion/pipeline.py`'s
`run_pipeline` never calls it). It is likely dead code describing a page
shape (a static server-rendered info card) that this Nuxt 3 SPA site does
not actually serve. If it isn't needed going forward, consider removing
`parse_info_card`, `_find_labeled_value`, `fetch_info_card_html`, and their
tests rather than maintaining an unverified parsing path.
