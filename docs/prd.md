# Trip Planner — Product Requirements

Draft 1, 2026-09-16. Companion to [data-model.md](./data-model.md).

## 1. Summary

A web app that takes a rough trip idea, turns it into a day-by-day skeleton,
finds the missing pieces (where to sleep, what to do), and produces a polished,
shareable itinerary with a map. An AI research agent does the legwork; the user
makes every decision.

It generalizes the static Tour de France planner Holly and Scott built
(brenstuhl.com/tdf) into a product for other people: multiple trips, multiple
users, edited in the app instead of in files, and not tied to any one kind of
trip.

## 2. Goals and non-goals

**Goals (v1)**
- A non-technical user gets from "I'm thinking about Portugal in May" to a
  shareable itinerary link without help and without touching a file.
- The agent proposes; the user picks. Nothing is added to the plan without an
  explicit accept.
- Every agent suggestion carries sources so the user can check it.
- Per-trip agent cost is tracked so a future paid tier can be priced.

**Non-goals (v1)**
- Booking or payments. We link out; we never take money.
- Transit research (v1.1). Transit legs can be added manually.
- Collaborators / invited editors (v1.1).
- Event anchors (races, festivals, weddings). Later.
- Budgets, expense tracking, media uploads, version history.
- Real-time availability or pricing from booking APIs.

## 3. Users

| Persona | Who | Device | v1? |
|---|---|---|---|
| Planner | Organizes the trip. Comfortable with a browser, not with spreadsheets or files. | Desktop / laptop | Yes |
| Traveler | Goes on the trip. Opens the shared link on the road. | Phone | Yes (read-only) |
| Co-planner | Invited to edit the same trip. | Desktop | v1.1 |

## 4. User journey

Worked example throughout: **"Portugal, 10 days in May, two of us, we like food,
wine, and walking. Fly into Lisbon."**

1. **Sign in.** Clerk with Google sign-in. Lands on the trip list (empty on first
   visit) with one button: *Start a trip*.
2. **Intake.** One text box: *"Tell me about the trip you're thinking about."*
   The user types the example above. The agent extracts destination(s),
   dates or duration, traveler count, and interests. If something essential is
   missing (dates, for example) it asks at most two follow-up questions in the
   same conversational panel. It never asks for anything it can default.
3. **Skeleton.** The app shows a proposed day list: 10 rows, each with a date,
   a base city, and a one-line title ("Arrive Lisbon", "Lisbon", "Day trip to
   Sintra", "Train to Porto", ...). The user can rename, reorder base cities,
   add or delete days, or say "make it 12 days" in the intake box. *Confirm*
   creates the Trip and Days.
4. **Planning board.** Map on the left with a pin per base city. Day selector
   and the selected day's timeline on the right. Tabs: Overview, Day, Lodging,
   Activities (Transit tab appears in v1.1). Every day has slots. Empty slots
   are gaps and say what is missing: *"No lodging in Porto yet"*,
   *"Nothing planned for the afternoon"*.
5. **Fill a gap.** Click a gap → *Find options*. A research job is queued; the
   slot shows *"Looking..."* with progress. Within a couple of minutes, 3–5
   candidate cards arrive.
6. **Review candidates.** Cards sit side by side: name, one-line summary,
   price range if known, pros, cons, confidence, map pin, and source links.
   Actions per card: *Choose*, *Not this one* (optional reason), and a
   panel-level *Find more like...* with a free-text nudge ("closer to the
   river", "cheaper"). Choosing turns the candidate into a plan item: it
   appears on the timeline and on the map.
7. **Repeat** until the Overview tab shows no open gaps. The user can also add
   items manually at any time, and edit anything the agent produced.
8. **Share.** *Publish* creates a read-only link. The Traveler opens it on a
   phone and sees the itinerary: day-by-day, map, where we're sleeping, what's
   planned, with links out to maps and bookings.

## 5. Screens

### 5.1 Trip list
Cards for each trip with title, dates, status (dreaming / planning / booked /
done), and open-gap count. *Start a trip* button. Empty state explains what
the app does in two sentences.

### 5.2 Intake conversation
Single-column chat panel. First message is the prompt. Agent replies are
short. When it has enough, it says so and shows the skeleton beneath the
conversation rather than in a new page, so the user can keep talking to
adjust it. States: typing, agent thinking, follow-up question, skeleton ready.

### 5.3 Skeleton confirmation
Editable table of days: date, base city, title. Inline edit, reorder,
add/remove day. *Confirm* button. Cancel returns to intake with context kept.

Implemented 2026-09-16:
- The editor sits under the chat on the same page. Chatting again sends the
  edited draft back so hand edits are kept.
- A first day is required to confirm. The agent leaves it blank when the
  traveler only gave a month; day dates follow from it.
- Confirm creates the Trip (status *planning*), one Day per row, one city
  Place per distinct base city, and starter gaps: one lodging gap per
  consecutive stay (last day treated as departure, no night) and one
  activity gap per day.

### 5.4 Planning board
Layout mirrors the TDF planner: map column, sidebar with day jump and layer
toggles, detail band with tabs.

- **Overview tab**: whole-trip map, all lodging and activities, and a *What's
  still missing* list of open gaps linking into their days.
- **Day tab**: timeline for the selected day. Slots in order: morning,
  afternoon, evening, lodging. Filled slots show the plan item; empty ones
  show the gap with a *Find options* button and an *Add manually* link.
- **Lodging tab**: one row per stay across the trip with dates, status, link.
- **Activities tab**: table of all activities with day, kind, status.
- Map layers: lodging, food, sights, other; toggle per layer.

Implemented 2026-09-16 (first cut):
- Map shows a pin per base city and a dashed route line in visit order.
  Clicking a pin opens that city's first day. OpenStreetMap tiles.
- City coordinates come from OpenStreetMap Nominatim, looked up server-side
  after confirm and cached. Policy: https://operations.osmfoundation.org/policies/nominatim/
  (max 1 request/second, identifying User-Agent, results cached, no
  autocomplete or bulk use). Commercial use requires a self-hosted instance
  or a paid provider; the base URL is configurable.
- Day tab has two slots, *Plans for the day* and *Where you're sleeping*,
  instead of morning/afternoon/evening. Layer toggles and the edit drawer
  are deferred until there are hotels and activities to show.
- Editing: click any item to open a side drawer with its fields.

### 5.5 Gap detail and candidate comparison (the inbox)
Opens as a drawer over the board so the map stays visible. Header restates
the gap in plain words. Body is a horizontal row of candidate cards (see
journey step 6). Hovering a card highlights its pin. Rejected cards collapse
into a *Rejected (2)* footer that can be expanded. If no job has run, the
drawer shows the *Find options* button and an *Add manually* form. If a job
failed, it says so and offers retry. Users never see JSON, ids, or model
names.

Implemented 2026-09-16:
- The drawer replaces the board panel's tabs while open (map stays visible),
  opened from a gap's *Find options* / *Compare N options* button or the
  Overview's missing list, with `?gap=` in the URL.
- *Choose* creates a Lodging for exactly the stay's nights, or an Activity
  on the day, with status `planned`, the option's link, price notes, and
  place. The gap becomes `answered`; other options stay for a later change.
- *Not this one* hides an option with an optional reason; *Hidden (n)*
  lists them with *Bring back*. Reasons feed the next research run.
- *Change* on a chosen stay or plan removes that item and reopens the gap
  with its options.
- Options get map pins when research returns coordinates or the worker can
  find their address on OpenStreetMap within 40 km of the day's city.
  Hovering a card highlights its pin; clicking a pin scrolls to its card.
- Research only starts from a button labeled *Find options* or *Find more*,
  never from simply opening the drawer, because each run costs money.
- *Add manually* is still deferred to the manual add/edit epic.

### 5.6 Shared itinerary (public)
Mobile-first. Vertical day list; tapping a day expands its timeline. Sticky
map at the top that recenters on the expanded day. Each item links out
(Google Maps, booking site). No editing, no sign-in required, no agent
controls.

Privacy model (decided 2026-09-16): an unguessable random slug is the only
protection in v1; no passcode. Guardrails:
- Publishing is an explicit toggle, off by default. Nothing is reachable
  until the planner clicks *Publish*.
- *Unpublish* and *Regenerate link* are one click each; the old link dies.
- The public payload is stripped: no confirmation codes, prices, rejected
  candidates, gaps, or agent internals. Only where, when, and links out.
- Responses carry `noindex` headers so search engines never list them.
Passcodes or traveler sign-in are deferred until genuinely sensitive data
(confirmation numbers, flight details) is added to the shared view.

## 6. Agent behavior

**Intake agent** (synchronous, in the API): parses free text into a structured
trip draft (destinations, dates, travelers, interests) and a day skeleton.
Asks at most two clarifying questions. Deterministic defaults where possible
(e.g. missing dates → "10 days starting on a placeholder date, editable").

**Research agent** (asynchronous, in the worker): given a Gap and trip context,
runs a bounded loop of web searches, reads results, and writes 3–5 Candidate
rows.

Search provider (decided 2026-09-16): Anthropic's built-in web search tool
(`web_search_20260318`) via the Anthropic SDK. Citations are always on and
map directly to Source rows. Per job: `max_uses` cap, `user_location` set to
the destination city, and a `blocked_domains` list for low-quality
aggregators. Cost is $10 per 1,000 searches plus tokens for results. The
search call is one pluggable step in the worker so a later swap to a
third-party search API is cheap.

Implemented 2026-09-16:
- Claude Opus 5 with `web_search_20260318` and a strict `submit_candidates`
  tool; up to 4 turns, `pause_turn` resumed automatically.
- Sources are kept only if their URL appeared in the search results Claude
  received. Options left with no confirmed source are shown as *Unverified*.
- `user_location` is not set yet (it needs an ISO country code the trip
  doesn't store). Blocked domains: pinterest.com, quora.com.
- Cost, measured on a Lisbon lodging gap: 8 searches at medium effort was
  ~$0.85 and ~100s; 5 searches at low effort was ~$0.33 and ~47s with
  comparable quality. Shipped with 5 searches, low effort (env-overridable).
  Roughly $4–5 to research every gap in a 10-day trip.

Inputs: trip summary, day context (date, base city, neighbouring days),
gap kind and prompt, user interests, any *Find more* nudge, list of already
rejected candidates and their reasons, and (later) the user's loyalty
programs and credit cards so perks can be flagged.

Outputs: Candidate rows with summary, pros, cons, confidence, a Place with
coordinates (marked approximate if geocoded from an address by the model),
price range if found, and one or more Sources per candidate.

Guardrails:
- Every factual claim on a card must have a source; unsourced facts are
  labelled *unverified*.
- Never auto-accept. Never modify plan items.
- Hard cap on searches and tokens per job. Cost recorded on ResearchJob.
- Don't repeat rejected candidates for the same gap.
- Timeout with partial results rather than nothing.

## 7. Data model

See [data-model.md](./data-model.md). One-line summary of entities:

| Entity | Role |
|---|---|
| Trip, Day | The plan's spine |
| Place | Anything with a location; shared by all pins |
| Lodging, Activity, Transit | Plan items (Transit manual-only in v1) |
| Gap | An open question; the unit of agent work |
| Candidate | An agent proposal for a gap |
| Source | Citation on any record |
| ResearchJob | One agent run, with status and cost |

## 8. Architecture

Render, one `render.yaml` blueprint:

| Service | Type | Notes |
|---|---|---|
| web | Static site | React + Vite + TypeScript, React Router, Leaflet |
| api | Web service | FastAPI + uvicorn. Auth via Clerk JWT. Serves the public share link too |
| worker | Background worker | Python. Polls a `research_jobs` table (Postgres-backed queue, no Redis in v1). Runs the research agent with the Anthropic SDK |
| db | Postgres | SQLModel / SQLAlchemy + Alembic migrations |

Share links: a 128-bit random slug on the Trip, null until published.
`GET /share/{slug}` returns the stripped public payload with `noindex`
headers; the web app renders it without sign-in. Regenerating replaces the
slug; unpublishing nulls it.

Starter tier on api and worker so nothing sleeps.

## 9. Non-functional requirements

- Planning board works on desktop and tablet. Shared itinerary is mobile-first.
- *Find options* gives visible feedback within 2 seconds and results within
  ~2 minutes; jobs can run longer without blocking the UI.
- Per-trip and per-job agent cost stored and visible on an internal admin view.
- No raw JSON, ids, or model internals in user-facing UI.
- Keyboard-navigable forms, sufficient contrast, alt text on map controls.
- Data isolation: a user only ever reads trips they own (v1) or are a member
  of (v1.1). Share links expose only published trips.

## 10. Scope

| Capability | v1 | v1.1 | Later |
|---|---|---|---|
| Sign in, trip list | ✓ | | |
| Conversational intake + skeleton | ✓ | | |
| Planning board with map and day timeline | ✓ | | |
| Gaps and agent research for lodging | ✓ | | |
| Gaps and agent research for activities | ✓ | | |
| Candidate comparison drawer | ✓ | | |
| Manual add/edit of lodging, activities, places | ✓ | | |
| Public share link, mobile-first | ✓ | | |
| Cost tracking per job | ✓ | | |
| Transit legs (manual) | ✓ | | |
| Transit research | | ✓ | |
| Invite editors | | ✓ | |
| User-pasted links → candidates | | ✓ | |
| Event anchors (races, festivals) | | | ✓ |
| Structured place data (Google Places) | | | ✓ |
| Calendar export, PDF | | | ✓ |
| Paid tier / credits | | | ✓ |
| Loyalty and card perks context (e.g. Chase Sapphire Reserve credits, transfer partners) | | | ✓ |

## 11. Success criteria

- One invited, non-technical user completes a real upcoming trip from intake
  to a shared link with no help from Holly.
- They accept at least one agent candidate for lodging and one for an activity.
- Agent cost per trip is known and under a target to be set after the first
  three trips.

## 11a. Later: loyalty and card perks

Users list the cards and loyalty programs they hold by name only (never
account access). The research agent searches current, public benefit
details and badges candidates where a perk may apply: hotel bookable through
the card's travel portal, dining credits, airline transfer partners.
Every perk badge carries a dated source and says "may apply"; the app never
promises a credit will work and never redeems on the user's behalf.
Benefits change often, so the agent must search, not recall.

## 12. Open questions

1. Should intake allow zero follow-up questions and always produce a skeleton
   with editable placeholders instead?
2. Should accepted candidates keep a link back to their Candidate row (for
   "why did we pick this?") — proposed yes via `Gap.resolved_by_id`.
3. How many candidates per job: fixed 3–5, or user-adjustable?

Resolved: web search provider (section 6) and share-link privacy (section
5.6), both 2026-09-16.
