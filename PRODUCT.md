# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React + Vite for the new dealer-facing page, deployed to the same Oracle VM as the current demo. The page talks to the existing Python backend (`zonegen/serve.py`, which already answers `GET /zone?run=&q=`). The Streamlit app (`app.py`) stays as the internal tool until the new page covers everything it does.

## Users

**Primary: a dealership service advisor on a phone call.** A customer calls to book a mobile service visit. While the customer waits on the line, the advisor types the address and needs an answer at once: can we serve it, and which zone is it in. They are not map experts and are not GIS users.

**Secondary: internal staff (admin).** They create zones for a new dealership location and tune the zone settings. They are a small trusted group, so this work lives behind a password-protected admin panel, not in the advisor's view.

## Product Purpose

RoadZone turns a dealership's location into mobile-service zones based on real road miles, not straight-line radius, and then classifies any address into one of those zones. The dealer page exists so an advisor can answer "do we come to you, and where do you fall?" in seconds, without guessing.

Success: the advisor gets a correct, confident answer before the customer finishes saying their address, and knows when *not* to trust it.

## Positioning

The zones follow the actual road network: I, US and CA highway corridors, with outbound and return trips both checked. Two houses the same straight-line distance apart can land in different zones because one sits across a ridge or a bay. RoadZone also says out loud when its answer is shaky, instead of silently guessing.

## Operating Context

- Used mid-call, often on a phone or a small laptop screen, one-handed, under time pressure.
- Input is a street address or a `lat, lon` pair. Geocoding uses public Nominatim, which allows at most 1 request per second, so lookups take about a second.
- Each dealership location is a "run" (for example Stevens Creek, Toyota Sunnyvale). The advisor works with one location at a time.
- Zone codes are read aloud and used by drivers ("John is on the Z corridor today"), so they must be short and speakable.

## Capabilities and Constraints

- **Address check (primary).** The answer must show:
  - the zone code (for example `2AB`), with the corridor and the branch it is reached through
  - road miles from the dealer
  - a plain in or out of service area verdict
  - a needs-review flag when routing is unreliable (track or unnamed-road access, far snaps)
- **Zone map (secondary).** The selected location's zones, coloured green near the dealership and red far out.
- **Zone settings.** Merge small zones into a neighbour, colour strength, and focus on one zone.
- **Zone builder (admin only, password protected).** Create zones for a new location: pick a base point, choose the highway types (I / US / CA; at least one must be ticked, with none preselected), and set distance bands.
- **Dropped from the dealer page:** comparing locations side by side.
- **Bands (v1):** road miles, 50 mi limit, 5-mile Hub, 10-mile bands. Travel-time views are optional, free-flow and optimistic, and must never silently change a published plan.
- **Map data** currently covers California only.
- **Not in this version:** van location and live traffic.
- **Security:** the lookup server has no auth today and listens only on the same machine. It needs real auth before it is opened to dealers.

## Brand Commitments

- Product name: **RoadZone**.
- The user explicitly asked for a feel that is **minimal, easy-going and Apple-like**, following the system light or dark setting. This is a binding direction for future visual work, not yet a defined visual system.
- Zone colours: green near the dealership, red far out (from the CEO's review).

## Evidence on Hand

- Real zone runs under `runs/` (cells.geojson, run_meta.json) and configs under `configs/` (for example `configs/stevens_creek.yaml`).
- M1 validation results in `README.md` and `docs/m1-failure-report.md`: 88–94% road-mile agreement with OSRM, and 29/31 tricky scenarios pass. These use a provisional base point, not the confirmed van entrance.
- Decisions log in `docs/decisions.md`.
- There are no customer testimonials, dealer logos, or pricing, and none should be invented.

## Product Principles

1. **Answer first.** The address verdict is the page. Everything else is supporting context.
2. **Honest about doubt.** A needs-review answer is shown as clearly as a confident one. Never hide uncertainty to look cleaner.
3. **Speakable output.** Codes, names and verdicts must work when read aloud on a call.
4. **Dealers see answers, admins see controls.** Pipeline and tuning stay out of the advisor's way.
5. **Road truth over radius.** Never fall back to straight-line distance without saying so.

## Accessibility & Inclusion

The page must be usable on a phone during a call: large touch targets, readable at arm's length, and keyboard-friendly on desktop (type, Enter, read). The zone verdict must not rely on colour alone, because green/red is the zone scale.
