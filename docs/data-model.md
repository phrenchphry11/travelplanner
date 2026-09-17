# Data Model (draft, 2026-09-16)

Derived from the TDF static planner's `trip-data/schema.md`, generalized for
a multi-user, multi-trip app. No race-specific fields in the core.

## Core principle

Two kinds of records live side by side:

- **Plan records**: what the trip *is*. Days, lodging, transit, activities, places.
- **Candidate records**: what the agent *proposes*. A candidate is a suggestion
  for a plan record, with sources, pros/cons, and confidence. Accepting a
  candidate creates or fills a plan record. Rejecting keeps it with a reason.

This keeps "agent proposes, user picks" as a database shape, not just a UI idea.

## Entities

### User
Comes from Clerk. We store only `id` (Clerk user id), `email`, `display_name`.

### Trip
| field | notes |
|---|---|
| id | uuid |
| owner_id | User |
| title | "Portugal, May 2027" |
| start_date, end_date | days are generated from this range |
| home_base_note | optional free text, "flying from SFO" |
| status | `dreaming`, `planning`, `booked`, `done` |
| created_at, updated_at | |

Collaborators: `trip_members (trip_id, user_id, role: owner|editor|viewer)`.

### Day
One row per calendar date in the trip.
| field | notes |
|---|---|
| id, trip_id | |
| date | unique per trip |
| title | "Lisbon to Porto" |
| summary | short text |
| notes | longer markdown |
| base_place_id | optional Place, where you sleep / are based that day |

### Place
Anything with a location. Shared vocabulary for lodging, activities, transit endpoints, and map pins.
| field | notes |
|---|---|
| id, trip_id | |
| name | |
| kind | `lodging`, `food`, `coffee`, `sight`, `shop`, `station`, `airport`, `neighborhood`, `other` |
| lat, lng | nullable, precision flag `exact|approximate|unknown` |
| address | |
| google_maps_url, website_url | |
| summary, notes | |
| tags | text[] |

### Lodging (a stay)
| field | notes |
|---|---|
| id, trip_id, place_id | |
| check_in, check_out | dates; links to Days by range, no join table |
| booking_url, confirmation_code | |
| cost, currency | nullable |
| status | `idea`, `shortlisted`, `planned`, `booked` (`planned` = chosen in the app, not yet booked) |
| notes | price range text for chosen options |

### Transit (a leg)
| field | notes |
|---|---|
| id, trip_id, day_id | |
| name | "Lisbon to Porto" |
| method | `train`, `flight`, `drive`, `bus`, `ferry`, `walk`, `taxi`, `other` |
| from_place_id, to_place_id | nullable Places |
| depart_at, arrive_at | timestamps, nullable |
| booking_url, confirmation_code | |
| status | `idea`, `shortlisted`, `booked` |
| notes | |

### Activity
Anything you do on a day that isn't sleeping or moving.
| field | notes |
|---|---|
| id, trip_id, day_id | |
| name | |
| kind | `meal`, `sight`, `tour`, `outdoors`, `shopping`, `rest`, `other` |
| place_id | nullable |
| start_time, end_time | nullable, local |
| time_of_day | `morning`, `afternoon`, `evening`, or empty for any time |
| booking_url | |
| status | `idea`, `shortlisted`, `planned`, `booked` |
| notes | |
| sort_order | order within the day's time-of-day group |

### Gap
An open question the app or user identified. The thing the agent works on.
| field | notes |
|---|---|
| id, trip_id, day_id | day nullable for trip-wide gaps |
| kind | `lodging`, `transit`, `activity`, `food`, `question` |
| prompt | "Where do we sleep in Porto on May 4?" |
| origin | `starter` (made with the trip) or `request` (the traveler's *Find ideas*) |
| time_of_day | requests only: `morning`, `afternoon`, `evening`, or empty |
| status | `open`, `researching`, `answered`, `dismissed` |
| resolved_by_id | the plan record that closed it, nullable |

### Candidate
An agent (or user) suggestion for a gap.
| field | notes |
|---|---|
| id, trip_id, gap_id | |
| target_kind | `lodging`, `transit`, `activity`, `place` |
| payload | jsonb draft of the target record |
| place_id | nullable, if the candidate is location-bearing |
| summary | one line |
| pros, cons | text[] |
| confidence | `low`, `medium`, `high` |
| status | `proposed`, `accepted`, `rejected`, `needs_more` |
| rejection_reason | |
| created_by | `agent` or user id |

### Source
Citations attached to any record. Polymorphic `(subject_kind, subject_id)`.
| field | notes |
|---|---|
| title, url, note | |
| fetched_at | |

### ResearchJob
One agent run. Lets the UI show progress and lets the worker be idempotent.
| field | notes |
|---|---|
| id, trip_id, gap_id | |
| status | `queued`, `running`, `done`, `failed` |
| started_at, finished_at, error | |

## Deliberately left out of v1
- Event anchors (races, festivals). Add later as `Event` attached to Trip or Day.
- Budgeting beyond a nullable cost on lodging/transit.
- Media uploads. Store image URLs only.
- Version history. Postgres updated_at is enough for now.

## Open decisions for this doc
1. Should Lodging link to Days by date range (proposed) or explicit join table?
2. Is `Gap` worth its own table, or is a Candidate with no parent enough?
3. Do Places belong to a Trip (proposed, simple) or are they global and shared?
