# Automate-Event-Planning-Agent-using-Crew-AI-Agents

# Workflow, Tools, and Design Decisions

## Slide 1 - Title
Event Planning Agent
From user input to final event plan

---

## Slide 2 - Agenda
- Problem we are solving
- End-to-end workflow
- Step-by-step tools used
- Alternatives considered at each step
- Why final choices were made
- Risks, trade-offs, and roadmap

---

## Slide 3 - Problem Statement
Users need a guided event planning flow that can:
- Collect event requirements quickly
- Generate realistic venue recommendations
- Provide operational intelligence (budget, weather, vendors, logistics)
- Let the user choose a venue option
- Produce a final, exportable event plan

Success criteria:
- Clear multi-step UX
- Useful real-world context from search
- Reliable final plan generation
- Safe fallbacks if external data is unavailable

---

## Slide 4 - System Overview
Core components:
- UI Orchestrator: event_planning_ui.py
- Recommendation Engine: event_planning/recommendations.py
- Intelligence Engine: event_planning/intelligence.py
- Validation Layer: event_planning/validators.py
- Planning Crew Runtime: automate_event_planning/crew.py
- Output artifacts:
  - venue_details.json
  - output/event_<topic>.md

Primary external capability:
- Google search via Serper API (through run_google_search)

---

## Slide 5 - Agent, Crew, and Task (Core Concepts)
Agent (who does the work):
- An Agent is a role-specialized worker (for example, venue scout, logistics planner, budget analyst) that focuses on one planning perspective.

Crew (how agents collaborate):
- A Crew is the orchestration layer that coordinates multiple agents, passes context between them, and combines their outputs.

Task (what must be delivered):
- A Task is a concrete assignment with expected output format, constraints, and quality bar (for example, "produce a venue shortlist with pros/cons").

Why this design is used:
- Better separation of responsibilities
- Easier debugging per role
- More controllable multi-step output quality

---

## Slide 6 - Step 1: Collect Event Details
Goal:
Capture required user input (topic, city, date, participants, budget, venue preference).

Tool used:
- Python HTTPServer + HTML form in event_planning_ui.py [purpose: capture user requirements and trigger workflow actions]

Why this was chosen:
- Lightweight, no extra frontend framework dependency
- Fast iteration in a single Python service
- Good fit for local demo and internal prototyping

Other options considered:
- Streamlit UI
- Flask/FastAPI + templating
- React frontend + API backend

Why not chosen (for this phase):
- More setup and architecture overhead
- Slower iteration for rapid agent workflow changes

---

## Slide 7 - Step 2: Input Validation and Guardrails
Goal:
Ensure safe and valid input before expensive operations run.

Tools used:
- validate_positive_integer [purpose: enforce numeric integrity for participants and budget]
- validate_future_date [purpose: prevent planning with past/invalid dates]
- validate_city_or_venue [purpose: sanitize and validate location/venue text input]
- is_safe_event_topic [purpose: block unsafe or disallowed planning topics]

Why this was chosen:
- Prevents invalid requests and downstream failures early
- Keeps generated outputs safer and more relevant
- Improves user trust through clear, field-level feedback

Other options considered:
- Validate only in frontend
- Validate only after crew kickoff

Why not chosen:
- Frontend-only validation is easy to bypass
- Late validation wastes runtime and search calls

---

## Slide 8 - Step 3: Venue Recommendation Discovery
Goal:
Build a ranked list of candidate venue types and metadata.

Tools used:
- run_google_search (Serper-backed) [purpose: fetch fresh public web signals for venues]
- extract_venue_types_from_google_results [purpose: parse and rank venue-type candidates from search text]
- search_live_venue_address [purpose: pull approximate address details for selected venue type]
- search_live_contact_phone [purpose: extract non-dummy contact phone from live results]
- budget_to_tier [purpose: map raw budget to decision tier]
- build_venue_pros_cons [purpose: generate explainable trade-offs for each venue option]

Why this was chosen:
- Real-world freshness from search results
- No heavy geodata integration required initially
- Produces explainable recommendations with pros/cons

Other options considered:
- Static venue dataset only
- Google Places API directly
- Paid proprietary venue databases

Why not chosen:
- Static data gets stale quickly
- Places API needs more schema handling, quotas, and billing setup
- Proprietary sources increase lock-in and cost

---

## Slide 9 - Step 4: Operations Intelligence Generation
Goal:
Provide actionable planning insights before final confirmation.

Tools used (in intelligence.py):
- build_availability_snapshot [purpose: estimate likely venue availability from search evidence]
- estimate_budget_breakdown [purpose: convert budget into category-level allocation]
- build_vendor_recommendations [purpose: shortlist service providers with quick quality cues]
- build_timeline_checklist [purpose: create date-relative execution milestones]
- build_weather_summary [purpose: summarize approximate weather conditions for planning readiness]
- build_accommodation_suggestions [purpose: suggest nearby stay options for attendees]
- build_transport_plan [purpose: outline transit and parking/logistics guidance]
- build_accessibility_details [purpose: define inclusion and support requirements]
- build_multi_venue_comparison [purpose: compare top options on fit, budget, and score]
- build_email_confirmation_draft [purpose: auto-generate stakeholder confirmation template]

Why this was chosen:
- Modular functions keep logic readable and testable
- Each insight is independently upgradable
- Easy to display in tabs and reuse in final report

Other options considered:
- One monolithic prompt for all insights
- A single LLM call for everything

Why not chosen:
- Harder to debug and verify source quality
- Less deterministic structure for UI tabs
- Higher risk of hallucinated or inconsistent sections

---

## Slide 10 - Step 5: Guided Multi-Step UX
Goal:
Lead users through Event Details -> Intelligence -> Venue Selection -> Final Plan.

Tools used:
- Stepper state logic in render_page [purpose: keep top progress indicator synchronized with active stage]
- Client-side panel switching JavaScript [purpose: enable fast step transitions without full page reload]
- Explicit form action control (recommend vs final) [purpose: route each submit to the correct backend path]

Why this was chosen:
- Keeps user context and avoids cognitive overload
- Supports progressive disclosure of information
- Reduces accidental finalization without review

Other options considered:
- Single long page with all sections
- Wizard handled entirely server-side reloads

Why not chosen:
- Single page can overwhelm users
- Full server-side wizard feels slower and less interactive

---

## Slide 11 - Step 6: Final Plan Generation
Goal:
Create the final event plan artifact after venue selection.

Tools used:
- event_management_crew.kickoff [purpose: run coordinated agent reasoning for planning output]
- generate_event_plan [purpose: orchestrate final-plan pipeline and persistence]
- ensure_venue_details_json [purpose: validate/regenerate venue metadata file before report build]
- build_structured_final_markdown [purpose: enforce deterministic final report structure]
- File output to output/event_<topic>.md [purpose: produce reusable, auditable artifact]

Why this was chosen:
- Crew kickoff allows agentic planning behavior
- Structured markdown guarantees deterministic report sections
- Output file enables auditability and sharing

Other options considered:
- Return only on-screen text, no file output
- Fully free-form final response from LLM only

Why not chosen:
- No file means weak traceability
- Free-form only can reduce consistency across runs

---

## Slide 12 - Reliability and Fallback Strategy
Fallbacks implemented:
- If search is unavailable, return sensible defaults
- If venue details file is missing/invalid, regenerate from fallback data
- If crew output hits iteration/time limits, produce fallback plan template
- If final generation fails, preserve user context and show step-level error

Why this was chosen:
- Keeps flow resilient instead of failing hard
- Improves UX under external dependency issues

Other options considered:
- Strict fail-fast behavior

Why not chosen:
- Bad UX for user-facing planning workflow

---

## Slide 13 - Key Decisions We Corrected During Iteration
Issues found and fixed:
- Stepper highlight mismatch during step transitions
- Missing Back path in Intelligence view
- Duplicate action parameter causing final submit to route incorrectly
- Dummy phone number replaced by live search extraction
- Weather summary upgraded from fragile single-snippet output to multi-source approximation

Impact:
- Improved navigation trust
- Correct final-plan generation behavior
- Better data realism in output

---

## Slide 14 - Trade-offs and Limitations
Current trade-offs:
- Search-based extraction is heuristic, not guaranteed canonical
- Contact email can still be synthetic when source data is absent
- Quality depends on external search availability and snippet quality

Mitigations:
- Strong fallback messaging
- Deterministic output structure
- Validation before and after major steps

---

## Slide 15 - Future Enhancements
Recommended next upgrades:
- Integrate Google Places or Maps for canonical phone/address
- Add confidence scores per insight section
- Add source citations in final report for each major claim
- Add unit tests for parsing and step-routing logic
- Add telemetry for step drop-off and failure reasons

---

