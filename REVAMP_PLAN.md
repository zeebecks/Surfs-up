# Lake Surf revamp

Reviewed September 20, 2026 on `revamp`. This is the original audit and implementation plan. The approved implementation now exists; see README.md for delivered behavior, validation, and remaining limitations. The findings below describe the pre-revamp app.

## Product direction

Build a Lake Michigan surf dashboard that helps someone answer three questions quickly: Where is worth checking? What is the lake actually doing? What will change over the next few hours?

Keep the six existing Wisconsin spots, cameras, Windy, local knowledge, and optional crew coordination. Make observed conditions and forecasts the main experience. The portfolio value should come from useful product decisions, trustworthy data handling, and a polished mobile experience.

Confirmed scope: retain the existing Wisconsin spots and nearby waters. Northern (45002) and southern (45007) Lake Michigan buoys are essential regional context. Wind speed and direction are the priority; missing wave sensors do not make a station unusable. Wind-only estimates remain useful when clearly distinguished from surf estimates.

## What exists

- FastAPI, Jinja templates, SQLite/SQLAlchemy, vanilla JavaScript, and Leaflet. This is a manageable stack for the project; retain it initially.
- Six spots: Two Rivers North Pier, Manitowoc South Pier, Sheboygan Elbow, Sheboygan Blue Harbor, Port Washington, and Kewaunee.
- NWS wind lookups for every spot, selecting one period for Now, +3h, or +6h.
- A wind-based score, ranked cards, and colored map markers.
- Two Windfinder embeds in this branch: Elbow and Two Rivers. The user recalls three; the template currently contains two.
- YouTube cameras and three server-proxied MJPEG camera routes.
- Password-protected note editing and device-token check-in deletion.
- No tracked automated tests, CI configuration, or hosting configuration found.

## Findings

| Priority | Finding and evidence | Proposed action |
| --- | --- | --- |
| First | `forecast.py` returns deterministic synthetic weather after any provider error. The route drops `source`, so synthetic conditions look real. Reproduced with an injected connection failure and an isolated home-page request. | Explicit fresh, stale, unavailable, and demo states. Demo data only through an intentional setting with visible labeling. Never rank unavailable data as real conditions. |
| First | `scoring.py` gives Elbow 98.1/100, “epic,” for 15 kt east wind with **zero waves**; the same result occurs with missing wave data. Calm east wind with zero waves scores 65.5, “good.” | Require credible wave evidence for a surf-quality score. Separate wave potential, surface quality, and data confidence. |
| First | `seed_spots_if_empty()` performs `INSERT OR REPLACE` on every startup. An isolated database reproduction confirmed it overwrites edited notes and clears editor metadata. | Insert missing spots without overwriting user data. Separate stable spot descriptions from dated condition reports. Provide deliberate handling of future metadata updates. |
| First | Each home-page request makes six sequential forecast calls, normally two HTTP requests each. There is no cache; time changes repeat the process. | Cache point-to-grid mappings and full forecast series; share connections, bound concurrent fetches, and serve the page without waiting on every provider. |
| First | Missing gusts become wind +4 kt, missing direction becomes north, and missing speed becomes zero. The forecast selector can use the nearest period even outside its coverage. | Preserve missing fields and valid intervals. Read structured values/units where available; never present assumptions as measurements. |
| Before sharing | “Friends” check-ins appear in the unauthenticated crew page. Verified in an isolated database. Visibility is stored but never enforced. | Keep coordination lightweight and accurately describe its visibility. Remove the misleading privacy choice unless actual access control is introduced. |
| Before sharing | Map popups interpolate editable notes and editor names into HTML strings. Template JSON escaping does not protect this later HTML insertion. | Build popup content using DOM nodes and text content. Add a regression check for saved HTML being displayed as text. |
| Before sharing | Check-in deletion uses GET, tokens remain in redirect URLs, and input checks are minimal. | Use POST for deletion, remove tokens from the visible URL after capture, validate spot/time/length inputs, and handle expired device state. |
| Polish | Camera proxies open two upstream connections per response, use unlimited timeouts, and have no deliberate offline presentation. | Use one bounded connection, close on disconnect, and provide on-demand playback and a source link when unavailable. |
| Polish | A large rotating banner, full check-in forms, and forecast columns dominate the page. `.spot-middle` has a 380px minimum even when empty, creating a mobile overflow risk. | Compact header, consistent comparison cards, responsive detail pages, and secondary crew actions. Verify at phone/tablet/desktop sizes. |
| Polish | The rotating images include files around 3.4, 7.5, and 5.6 MB; the favicon uses a roughly 1.3 MB image. | Optimize responsive images and create an appropriately sized favicon. Load heavy embeds only when needed. |
| Maintenance | Most interaction logic sits in one inline script; Leaflet failure can prevent unrelated initialization. Notes editing has duplicate listeners. | Split small JavaScript modules by responsibility and make external-widget failure independent of core controls. |

Layout findings above come from template/CSS inspection. The Browser runtime reported no available browser, so this audit does not claim visual or interactive browser verification. Camera uptime was not tested.

## Data-source direction

### Forecasts for every spot

Build native hourly panels with wind speed, gusts when available, direction, and wave height/period/direction where coverage is verified. Start with a 24–48 hour view, consistent units, local timestamps, and clear source labels.

Retain NWS as a wind forecast source. Cache its location lookup separately from forecast values. Its documentation describes hourly forecasts, raw grid data, and periodic revalidation of cached grid mappings: [NWS API documentation](https://www.weather.gov/documentation/services-web-api).

Open-Meteo Marine is a candidate for wave forecasts. A direct request at Elbow returned HTTP 200, 24 non-null hourly values for height/period/direction, and a model cell at 43.708336, -87.62499. That proves a usable response exists at one location, not that it predicts the local break accurately. Validate all six locations, model-cell positions, freshness, and plausibility before integrating. Neighboring spots may share a cell; do not manufacture differences. Model wave heights must be labeled as such, not as measured breaking-wave heights. [Marine API documentation](https://open-meteo.com/en/docs/marine-weather-api).

Windfinder's documented limit is **three widgets per page**, not three spots for the whole project. Prefer native forecast panels for consistency, with Windfinder links or an optional widget on individual spot pages. [Windfinder widget rules](https://www.windfinder.com/help/other/widgets).

NOAA's Great Lakes WaveWatch III products are a further wave-source candidate if the simpler provider fails coverage or quality checks. Start with a source link; adding GRIB/netCDF ingestion is a separate decision after evaluating its benefit. [GLERL wave products](https://www.glerl.noaa.gov/emf/waves/WW3/lhww3.html).

### Observations and buoys

Create a dedicated Buoys view plus relevant observation summaries within spot details. Use NOAA NDBC first and add GLOS stations where they provide useful local coverage. GLOS documents ERDDAP/API access: [GLOS data FAQ](https://glos.org/data/faq/). NDBC documents downloadable recent observations: [NDBC data access](https://www.ndbc.noaa.gov/faq/rt_data_access.shtml).

Direct feed checks during this audit:

- NDBC 45002 returned live data. Its newest row, 16:30 UTC on September 20, had wind and water temperature but no wave values. The 16:20 row included 1.0 m wave height, 5 s dominant period, and wave direction. This makes per-measurement timestamps essential.
- NDBC 45007's recent-data text URL returned HTTP 404. Do not assume a known station is currently reporting, or label it seasonally removed based only on this response.
- GLOS search returned a Sheboygan Panther Buoy archive. This establishes a discovery path; its current dataset, reporting status, and available sensors still need validation.

Choose stations by actual sensor availability, location, exposure, and local relevance. The nearest buoy is not automatically representative of a beach. Distinguish offshore buoys from coastal wind stations and explain each spot's station association.

Store source, station, observation time, retrieval time, units, quality status, and nullable values. Select the latest valid reading independently for each field within a bounded age. Show how old that reading is; do not silently combine old waves with current wind under one timestamp. Preserve coherent wave height/period/direction groups when using them for scoring.

Display measured wave height, period, direction, wind/gusts, and water temperature where the station supports them, alongside recent trends. Missing values remain missing. Fetch failure, old measurements, and confirmed seasonal removal are different states. Do not use today's observation as a +6h forecast.

## Surf score v2

Treat the score as an explainable estimate, with a separate confidence indicator. Keep it experimental until compared with real sessions.

1. **Wave availability:** use suitable observed or modeled height, period, direction, and trend. Flat conditions cannot score well just because the wind direction is favorable. Missing waves mean insufficient evidence for a full surf rating.
2. **Surface quality:** evaluate local wind relative to the break and shelter. The current formula rewards onshore wind as quality; the replacement must distinguish wave-building wind from wind that cleans up an existing wave field.
3. **Spot suitability:** move from mostly identical shoreline settings and fixed score offsets to documented wave-direction windows, exposure, and local cleanup preferences. Confirm assumptions with local surfers.
4. **Time context:** add wind history/duration and wave trend as the data supports them. Avoid inferring a developed wave field from one favorable hour.
5. **Confidence:** report measurement age, station relevance, model-only inputs, and missing components. Do not bury confidence inside a lower score that looks like poor surf.

An explanation might read “Easterly waves reaching the spot; wind easing; based on model data.” Only display claims supported by the actual inputs. Avoid fixed coefficients advertised as scientific accuracy. Version the scoring configuration and calibrate against a small collection of dated good, mediocre, and flat sessions. Ship honest observations and forecasts before promoting a “best spot” recommendation.

## Interface direction

Aim for a restrained Great Lakes identity: deep blue/charcoal surfaces, warm white type, one cyan accent, clear numeric typography, and selective local photography. Prioritize readable data, deliberate spacing, and mobile use.

- **Overview:** a compact header, selected forecast time, brief condition summary, and six easy-to-compare spot cards. Expose wave height/period, wind, freshness, camera availability, and an explained score when supported. Support favorites and geographic/rating sorting.
- **Map:** connect markers to spot details and add a separate buoy layer with a legend. Distinguish unavailable scores visually. Keep Windy one tap away, and explain that its own forecast controls are independent unless time synchronization is explicitly implemented.
- **Spot detail:** camera, native hourly forecast, relevant buoy observations, persistent local guide, dated notes, and links to original resources. Use a real URL so friends can share a specific spot.
- **Buoys:** station status cards, measurement timestamps, short trends, and a map. Explain which readings inform which spots.
- **Crew:** retain it as a secondary page or small “Who's going?” action, with accurate visibility wording.

Use accessible labels, keyboard focus, non-color status cues, reduced-motion support, and useful empty/error states. Loading a broken camera or map must not prevent access to conditions or notes.

## Implementation sequence and completion checks

### 1. Repair data integrity and establish provider handling

Fix seeding, remove silent synthetic fallbacks and invented fields, introduce structured forecast/observation records, and add caching with bounded timeouts/concurrency. Keep the existing app working throughout. Resolve the verified privacy wording and popup HTML issue in this foundation pass.

Done when restart preserves notes, provider outages show honest states, fresh cache hits avoid duplicate requests, unavailable readings remain null, and tests run against temporary databases without external network access.

### 2. Deliver useful data across all spots

Validate candidate wave coverage, add full hourly wind forecasts, integrate a small verified buoy set, and implement per-field freshness and recent observation history. Store shared station readings once even when multiple spots use them.

Done when all six spots have forecast panels or explicit unavailable states; every measurement has units/source/time; missing and old buoy values are handled correctly; and selecting a future forecast does not relabel observations as predictions.

### 3. Rebuild the main browsing experience

Implement the overview, spot details, buoy view, map linking, on-demand cameras, smaller assets, and secondary Crew navigation. Retain Python/Jinja and introduce only the JavaScript needed for interaction.

Done when the main flow works at approximately 375, 768, and 1440px widths without horizontal page overflow; it can be operated by keyboard; third-party failures leave core content usable; and screenshots plus actual interactions have been reviewed in a connected browser.

### 4. Introduce and calibrate scoring v2

Implement the explainable wave/surface/suitability model with a separate confidence result, a versioned spot configuration, and representative session fixtures.

Done when flat-water, missing-wave, strong-onshore, cleanup-wind, stale-buoy, wrong-direction, and model-only cases behave sensibly. Identify “best available estimate” separately from confirmed good surf. Local calibration remains an ongoing product task.

### 5. Make the project easy to evaluate

Update setup instructions, configuration examples, architecture/data-source notes, and the score explanation. Add focused CI checks, optimized assets, and a clearly labeled offline demo mode for reproducible portfolio demonstrations. Review dependency compatibility as part of implementation.

Done when someone can run the app from the README, understand the forecast/observation distinction, follow the scoring explanation, and see passing checks. Include screenshots after visual QA. Publishing is a separate step after the implementation is reviewable.

## Inputs that improve the result

Zach's usual buoy names/numbers/links will guide the station shortlist. Confirm whether the existing Wisconsin corridor is still the primary audience. Later, a few dated examples of great, average, and poor sessions at known spots will be more valuable for scoring than additional arbitrary weights.

## Audit verification

Read all application Python files, templates, CSS, spot configuration, requirements, and README. Confirmed `revamp` and an initially clean tracked working tree. Inspected the local database schema read-only. Ran isolated checks for seeding, route rendering, forecast fallback, check-in visibility, and scoring edge cases using a temporary database and injected forecast responses. Verified selected external feeds with read-only HTTP requests. No application or existing database changes were made during this audit.
