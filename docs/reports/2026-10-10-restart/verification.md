# Report and concept verification

Verified October 10, 2026 against the final generated HTML through localhost. These checks concern the decision kit and synthetic design concepts, not a deployed client or native app.

## Artifacts

- `index.html`: standalone report with all ten previews embedded through `srcdoc`, no runtime network dependency
- `01-quiet.html` through `10-memo.html`: ten individual full-view interactive concepts
- `concepts-contact-sheet.jpg`: compressed visual comparison of the ten concepts
- `completion.html`, `providers.html`: source fragments embedded by the builder
- `build_report.py`: Python standard-library generator; regenerate with `python3 docs/reports/2026-10-10-restart/build_report.py`
- `sources.md`: official research links and limits

## Automated browser checks

Temporary Python Playwright environment outside the repository, using a separate headless Chromium and the approved localhost report server. No dependency was added to the project.

- PASS: report at 390, 768 and 1440px; document scroll width did not exceed viewport width
- PASS: all ten full-view concepts at 390, 768 and 1440px; no horizontal overflow in all 30 layout checks
- PASS: each concept begins with hidden demo results; reveal removes the hidden attribute; hide restores it
- PASS: source/freshness disclosure opens in each visible layout
- PASS: each concept's empty, loading, error, retry and clear-state preview controls
- PASS: entity tabs across all three entities, including Arsenal unavailable
- PASS: focus deck advances through four items and back; first/last controls disable at their bounds
- PASS: reading-desk item buttons change the visible reading pane
- PASS: inbox disclosures open the remaining rows
- PASS: selected style, a changed decision and notes survive report reload
- PASS: Markdown and JSON downloads contain the chosen style, decision and notes
- PASS: restoring defaults selects Quiet briefing, resets decisions and clears notes
- PASS: when localStorage is disabled, a warning appears and style selection plus JSON export still work
- PASS: no JavaScript page errors observed in the above report/prototype checks
- PASS: keyboard Enter saves choices, Enter opens evidence, Space toggles spoilers; focused control has a visible outline
- PASS: final report contains ten actual iframe previews; an embedded Arsenal tab was exercised successfully
- PASS: computed foreground/background contrast for initially visible text in the report and all ten concepts had zero candidates below the applicable WCAG AA threshold. This is a computed-style check, not a full accessibility audit
- PASS: print media keeps report content present and hides navigation/save controls. Paper output itself was not printed
- PASS: local relative links and HTML anchors resolve to existing files/IDs, including repository evidence links. Localhost serving only this report folder does not expose the parent repository documents
- PASS: generator compiles; `git diff --check` passed

## Visual browser evidence

The worker inspected the generated 1600×800 contact sheet and the 390px report screenshot. All ten concepts use distinct composition and visual direction, including light system UI, serif newspaper, strong priority sheet, navy entity workspace, paper agenda, compact comparison, dark focus deck, cool reading desk, utilitarian inbox and warm memo.

The root independently inspected the final report in the user's Chrome:

- report at 390px: scroll width 375px within 390px viewport
- desktop report: scroll width 1705px within 1720px viewport
- ten concepts and ten iframe previews present; no research/completion placeholders
- quiet concept at 390px, editorial concept on desktop with result reveal, and dark focus concept at 390px visually checked
- Chrome error and warning logs were empty during these checks

## Product and evidence boundaries

- Arsenal remains unavailable because public display/caching permission is unresolved
- Texans and Scottie each have two independently authored synthetic items; snapshot is fixed at October 10, 2026, 12:00 UTC
- The revealed Scottie result is additional fictional design-only text, labelled synthetic
- No API fetch, provider ingestion, model call, email, purchase, hosted deployment or external write occurs
- Decisions are stored under one report-specific localStorage key. Exports are browser downloads; they do not authorize provider or deployment actions
- Direct `file://` browser compatibility was not verified. The browser automation URL policy blocked that navigation; this does not establish whether a user can open the file directly in Chrome. Localhost behavior was verified; storage fallback was separately exercised
- Native SwiftUI, real users, real data freshness, network latency, full assistive-technology coverage and printed output were not evaluated

The fresh engineering outcomes in the report were supplied and independently accepted by the root; their detailed evidence is in [the restart engineering record](../../restart-engineering-2026-10-10.md). The report's browser checks do not close M3, M5, M6 or real-model acceptance.
