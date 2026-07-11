# Event Planning Agent: Component Breakdown and Design Decisions

---

## Table of Contents
1. Event Planning UI (event_planning_ui.py)
2. Validators (event_planning/validators.py)
3. Recommendations Engine (event_planning/recommendations.py)
4. Intelligence Engine (event_planning/intelligence.py)
5. Crew & Agents (automate_event_planning/)
6. Data Persistence (venue_details.json, output/)

---

## 1. Event Planning UI (event_planning_ui.py)

### How It Works
The UI is a **single-file Python HTTP server** that:
- Listens on localhost:8788
- Renders HTML forms and step-by-step wizard UI
- Handles form submissions via POST requests
- Maintains state through form hidden fields and URL parameters
- Displays step indicators (stepper) to guide users through the flow

### Key Components

#### BaseHTTPRequestHandler
```
Purpose: Accept HTTP requests and route to appropriate handler
Why chosen: Minimal dependency footprint; no external web framework needed
Trade-off: Single-threaded, not suitable for high concurrency
```

#### render_page()
```
Purpose: Generate full HTML response based on current workflow state
Why chosen: 
  - Keeps all UI logic in one place
  - Current step (1-4) determines which panel is shown
  - Reusable across different flow states
  
Design decision: Determine current_step from:
  - If result exists → step 4 (Final Plan)
  - Elif selection_error exists → step 3 (Venue Selection)
  - Elif venue_recommendations exist → step 2 (Intelligence)
  - Else → step 1 (Event Details)
  
Why this logic:
  - State is implicit in what data is populated
  - No separate state variable to sync
  - Prevents invalid state transitions
```

#### Form Actions (recommend vs final)
```
Purpose: Route Step 1 form and Step 3 form to different handlers
  
Step 1 form submission:
  - action = "recommend"
  - Routes to: venue recommendation + intelligence generation
  - Returns: User sees steps 2 and 3 tabs
  
Step 3 form submission:
  - action = "final"
  - Routes to: generate_event_plan()
  - Returns: Step 4 with final markdown output
  
Why this design:
  - Cleaner than having one form do everything
  - Allows independent Step 1 → Step 2 resubmission if user changes details
  - Hidden fields carry forward context without user seeing it
```

#### Stepper Navigation Logic
```
Purpose: Keep top progress bar (1. Event Details, 2. Intelligence, etc.) in sync with active panel

Implementation:
  - Each step div has id="stepper1", "stepper2", "stepper3", "stepper4"
  - JavaScript function setActiveStep(n) adds/removes .active class
  - Triggered when:
    - Page loads (class computed from current_step)
    - User clicks "Continue to Venue Selection" button
    - User clicks "Back" button

Why this design:
  - CSS class-based styling is fast
  - setActiveStep() is called after panel change, not before
  - Prevents visual desync between top indicator and active panel
```

#### Error Handling and Fallbacks
```
Purpose: Show user-friendly error messages without crashing

When validation fails:
  - Field errors displayed inline below each input
  - Form is resubmitted with field_errors dict
  - render_page() stays on Step 1, shows red error messages
  
When venue selection fails:
  - selection_error set instead of error
  - User sees Step 3 with error banner + original recommendations
  - Can retry venue choice or go back to change details
  
When final generation fails:
  - Exception caught in try/except
  - Form context preserved (all previous inputs kept)
  - Step 3 rerendered with selection_error describing failure
  
Why this approach:
  - User doesn't lose context on error
  - Can retry without restarting from beginning
  - Specific error location shown (not generic "failed")
```

---

## 2. Validators (event_planning/validators.py)

### How It Works
Validation functions run **before** any expensive operations (search, crew kickoff).

### Each Validator

#### is_safe_event_topic()
```
Purpose: Block unsafe, politically divisive, or violent event topics

How it works:
  - Maintains a blocklist of unsafe keywords
  - Checks if user-entered topic contains any blocklisted words
  - Returns True (safe) or False (unsafe)

Why chosen:
  - Prevents misuse of the agent for harmful planning
  - Reduces downstream crew complexity (no need to second-guess input)
  - Clear boundary enforcement

Trade-offs:
  - Blocklist approach can be bypassable with synonyms
  - Alternative (classifier-based) would be slower
```

#### validate_positive_integer()
```
Purpose: Ensure participants and budget are positive numbers

How it works:
  - Try to convert to int
  - Check if > 0
  - Return error message or None (valid)

Why chosen:
  - Simple, fast, deterministic
  - Prevents nonsense inputs like "-5 participants" or "abc budget"
  - Matches HTML5 input type="number" but adds server-side safety
```

#### validate_future_date()
```
Purpose: Ensure event date is in the future, not past

How it works:
  - Parse YYYY-MM-DD format
  - Compare against today
  - Return error if date <= today

Why chosen:
  - Prevents planning for past events
  - No timezone issues (uses local date comparison)
  - Catches user typos like "2024" instead of "2026"
```

#### validate_city_or_venue()
```
Purpose: Sanitize location/venue type text input

How it works:
  - Check length (non-empty)
  - Remove excess whitespace
  - Return error if invalid

Why chosen:
  - Prevents empty or malformed search queries
  - Simplifies downstream string operations
  - Catches accidental form resets
```

#### get_time_based_greeting()
```
Purpose: Personalize UI with time-appropriate greeting

How it works:
  - Get current hour
  - Return "Good morning", "Good afternoon", or "Good evening"

Why chosen:
  - Small UX touch that improves friendliness
  - No external API call needed
```

---

## 3. Recommendations Engine (event_planning/recommendations.py)

### How It Works
Uses **live Google search** to discover real venue types, addresses, and contact info.

### Key Functions

#### run_google_search()
```
Purpose: Call Serper API for fresh web search results

Implementation:
  - Takes query string and limit (default 10 results)
  - Sends JSON request to google.serper.dev/search
  - Requires SERPER_API_KEY environment variable
  - Returns list of {title, snippet} dicts
  
Why chosen:
  - Freshness: Real current data, not stale database
  - Cost: Serper is cheaper than Google Places API
  - Flexibility: Query can be any venue/city combo
  
Trade-offs:
  - Requires external API key and internet
  - Search quality depends on Serper's indexing
  - No structured venue fields (must parse from text)
```

#### extract_venue_types_from_google_results()
```
Purpose: Parse search snippets to extract venue-type keywords

How it works:
  - Uses REGEX to find venue-related keywords
  - Patterns: "hall", "center", "auditorium", "venue", "lawn", etc.
  - Counts frequency across search results
  - Returns sorted list (most common first)

Why chosen:
  - Avoids hardcoded venue list (which goes stale)
  - Extracts what users actually search for
  - Ranking by frequency is reasonable heuristic
  
Example:
  - Search: "best event venues in Denver"
  - Results mention: "Denver Convention Center", "Platte River Lofts", "Confluence Park"
  - Extracted types: ["Convention Center", "Loft", "Park"]
```

#### search_live_venue_address()
```
Purpose: Get approximate street address for venue type + city

How it works:
  - Searches: "{venue_type} address in {city}"
  - Checks Serper's knowledge graph first (if available)
  - Falls back to first search snippet
  - Returns address string or "City Center (approximate)"

Why chosen:
  - Knowledge graph = canonical answer (better quality)
  - Search snippet = fallback (always has something)
  - Doesn't require explicit API calls per address
```

#### search_live_contact_phone()
```
Purpose: Extract real contact phone from search results (not dummy +1-555-0100)

How it works:
  - Searches: "{venue_type} {city} contact phone"
  - Extracts phone patterns from title + snippet
  - Returns first valid phone found
  - Falls back to "Not available"

Phone extraction:
  - Regex pattern: matches +1-555-1234, (555) 123-4567, etc.
  - Validates: 10-15 digits (rejects too short/long)
  - Cleans: removes formatting, returns raw digits

Why chosen:
  - Replaces hardcoded dummy "+1-555-0100"
  - Real contact info makes output more credible
  - Extraction is heuristic but practical
  
Trade-offs:
  - May not find phone if not in snippet
  - Phone may be for venue group, not specific location
  - Alternative: Google Places API has canonical phone (but adds cost/complexity)
```

#### budget_to_tier()
```
Purpose: Map raw budget to decision tier (1-4)

How it works:
  - Tier 1: ≤ $5k (tight budget)
  - Tier 2: $5k-$20k (moderate)
  - Tier 3: $20k-$60k (substantial)
  - Tier 4: > $60k (premium)

Why chosen:
  - Simplifies downstream logic (no need to check exact amounts)
  - Tiers drive pros/cons generation
  - Each tier gets appropriate venue suggestions
```

#### build_venue_pros_cons()
```
Purpose: Generate explainable trade-offs for each venue type

How it works:
  - Base pros: "Popular option", "Suitable for event hosting"
  - Base cons: "Pricing may vary", "Quality depends on provider"
  - Add venue-specific pros/cons:
    - Conference hall → "Strong for large gatherings"
    - Rooftop → "Great ambience" but "Weather can affect"
    - Gallery → "Visual appeal" but "Stricter rules"
  - Add budget-tier warnings

Why chosen:
  - Helps users make informed choices
  - Shows reasoning (transparent)
  - Customized per venue type (not generic)
  
Why not LLM-based:
  - LLM could hallucinate "free catering included"
  - This deterministic approach ensures accuracy
```

#### get_venue_recommendations()
```
Purpose: Orchestrate full venue discovery pipeline

Flow:
  1. Parse user inputs (topic, city, budget, preferred venue type)
  2. Build multiple search queries:
     - "best event venue types in {city}"
     - "popular event venues in {city} for {topic}"
     - "top halls conference centers in {city}"
     - "{preferred_venue_type} venues in {city}" (if provided)
  3. Run all searches → merge results
  4. Extract unique venue types → rank by frequency
  5. For each venue type:
     - Look up address
     - Generate pros/cons
     - Calculate quality score (higher = ranked earlier)
  6. Return top 10 recommendations with full metadata

Why this pipeline:
  - Multiple queries improve coverage (no single query perfect)
  - Ranking by frequency = user-validated popularity
  - Deduplication prevents duplicate suggestions
  - Pros/cons make each option comparable
```

---

## 4. Intelligence Engine (event_planning/intelligence.py)

### How It Works
Generates **modular, reusable insights** displayed in tabbed UI before final commitment.

### Why Modular Design?
Instead of one big prompt:
```
❌ Single monolithic call:
   "Give me everything about planning an event in Denver for 500 people"
   → Risk: Hallucination, inconsistency, hard to debug

✅ Multiple focused functions:
   - build_availability_snapshot() → venue availability
   - estimate_budget_breakdown() → spending allocation
   - build_weather_summary() → climate readiness
   - etc.
   → Each function owns one insight domain
   → Easy to test, debug, upgrade independently
```

### Each Intelligence Function

#### build_availability_snapshot()
```
Purpose: Estimate venue availability for selected date

How it works:
  - For each venue recommendation, searches:
    "{venue_name} {city} availability {date}"
  - Parses snippet for keywords: "sold out", "booked", "available", "reserve"
  - Classifies as: Likely Available, Likely Unavailable, Needs Confirmation
  - Returns list with source snippet

Why chosen:
  - Real availability check (not guessed)
  - Transparent source (user can verify)
  - Helps user prioritize venue followup calls
```

#### estimate_budget_breakdown()
```
Purpose: Convert total budget into category allocations

How it works:
  - Predefined allocation percentages:
    - Venue: 35%
    - Catering: 25%
    - AV: 12%
    - Marketing: 10%
    - Decor: 8%
    - Staffing: 6%
    - Contingency: 4%
  - Calculate: category_amount = total_budget * percentage
  - Return list of {category, percent, amount}

Why chosen:
  - Industry-standard allocation (tested by event planners)
  - Deterministic (no variance between runs)
  - Helps user understand where money goes
  
Why not LLM:
  - LLM might suggest 70% catering (nonsense)
  - This fixed allocation is proven safe
```

#### build_vendor_recommendations()
```
Purpose: Shortlist service providers (caterers, photographers, AV, decor)

How it works:
  - For each category (Catering, Photography, Decor, AV):
    - Search: "best {category} services in {city}"
    - Extract top 3 results
    - Parse star rating from snippet (e.g., "4.5/5")
  - Return {category: [{name, review_score, snippet}]}

Why chosen:
  - Vendors are critical to event success
  - Search results include user ratings (credible)
  - Top 3 prevents overwhelming user
  
Why not Places API:
  - Search is faster to integrate
  - Doesn't require Places setup
```

#### build_timeline_checklist()
```
Purpose: Create time-relative milestones (T-8 weeks, T-6 weeks, etc.)

How it works:
  - Fixed milestone template:
    - T-8 weeks: Confirm venue and contracts
    - T-6 weeks: Finalize vendors
    - T-4 weeks: Launch attendee reminders
    - T-2 weeks: Confirm logistics
    - T-3 days: Final vendor confirmations
    - Event day: Onsite operations
  - Return list of milestone strings

Why chosen:
  - Standard event planning timeline
  - Relative (works for any event date)
  - Actionable and sequenced
```

#### build_weather_summary()
```
Purpose: Provide approximate weather conditions for event month/city

How it works:
  1. Parse tentative_date → extract month
  2. Run multiple searches:
     - "{city} weather forecast {date}"
     - "average weather in {city} in {month}"
     - "{city} climate {month} average high low"
  3. Collect results, filter out placeholder snippets (e.g., "° to °")
  4. Extract temperature values using regex
  5. Aggregate: min/max temps, condition keywords
  6. Return summary like:
     "Naples around October: ~72°F to ~86°F with humid air and rain chances"

Why this approach:
  - Multiple queries improve hit rate
  - Temperature extraction is numerical (verifiable)
  - Condition keywords parsed from snippets
  - Month-relative (works 6+ months out, not just short-term forecast)
  
Why not weather API:
  - Extra API cost
  - Search snippets work for planning purposes
  - Simpler integration
```

#### build_accommodation_suggestions()
```
Purpose: List nearby hotel options for attendees

How it works:
  - Search: "top hotels near event venues in {city}"
  - Extract top 3 titles (hotel names)
  - Return list

Why chosen:
  - Helps attendees with travel planning
  - Extracted from real search results
  - User can verify and book directly
```

#### build_transport_plan()
```
Purpose: Outline transit + parking guidance

How it works:
  - Search: "public transport to conference venues in {city}"
  - Search: "parking near event centers in {city}"
  - Combine snippets → user guidance

Why chosen:
  - Logistics is critical to event success
  - Public search results = real infrastructure info
  - Snippets provide concrete guidance
```

#### build_accessibility_details()
```
Purpose: Define inclusion requirements and support capacity

How it works:
  - Wheelchair access checklist
  - Dietary accommodation options (vegan, halal, gluten-free, allergy-safe)
  - Support desk recommendation
  - Staffing needs: 1 desk per 250 participants

Why deterministic:
  - Accessibility is non-negotiable (no guessing)
  - Guidance is evidence-based
  - Same standard applied to all events
```

#### build_multi_venue_comparison()
```
Purpose: Compare top 3 venues side-by-side

How it works:
  - For each venue:
    - Capacity fit: "Strong" (matches participants), "Moderate"
    - Budget fit: "Premium-friendly" or "Budget-sensitive"
    - Score: inherited from recommendation ranking
  - Return table format

Why chosen:
  - Easy to compare 3 options
  - Objective criteria (fit, budget, score)
  - Table layout familiar to users
```

#### build_email_confirmation_draft()
```
Purpose: Auto-generate stakeholder notification template

How it works:
  - Structured email format:
    - Subject line with event topic and city
    - Event details recap (date, participants, budget, venue type)
    - Next steps (confirm venue, finalize vendors, share logistics)
    - Professional closing
  - Fill in blanks from form data

Why chosen:
  - Users can copy and send immediately
  - Ensures stakeholders have same understanding
  - Reduces miscommunication
  - Alternative (LLM composition): Could hallucinate details
```

---

## 5. Crew & Agents (automate_event_planning/)

### How It Works
The **Crew is the agentic reasoning layer** that generates the final event plan.

### Architecture

#### Agent (Role-Based Worker)
```
What is it?
  A specialized persona that reasons about one aspect of planning

Example agents in event_planning_ui.py:
  1. Venue Scout Agent
     - Role: "Expert venue researcher"
     - Goal: Find optimal venue match
     - Expertise: venue selection, negotiation
  
  2. Logistics Coordinator Agent
     - Role: "Operations expert"
     - Goal: Ensure smooth execution
     - Expertise: scheduling, staffing, contingency
  
  3. Budget Analyst Agent
     - Role: "Finance specialist"
     - Goal: Optimize spending
     - Expertise: allocation, cost control

Why agent-based approach:
  - Each agent has clear responsibility
  - Easier to debug (which agent made which decision?)
  - Reusable across events
  - More explainable than monolithic LLM
```

#### Task (Unit of Work)
```
What is it?
  A concrete assignment with:
  - Description (what to do)
  - Expected output (format and content)
  - Agent assignment (who does it)
  - Constraints (e.g., 500 words max, action items only)

Example tasks:
  Task 1: "Venue Finalization"
    - Agent: Venue Scout
    - Description: "Select the best venue from recommendations"
    - Output: "Selected venue with rationale"
    - Constraints: "Must address fit, budget, and logistics"
  
  Task 2: "Logistics Planning"
    - Agent: Logistics Coordinator
    - Description: "Create operational runbook"
    - Output: "Day-of timeline, staffing plan, contingencies"
    - Constraints: "Must be actionable by non-planners"

Why task-based structure:
  - Clear deliverable for each agent
  - Prevents scope creep
  - Easy to track completion
  - Quality is measurable (output matches expectation)
```

#### Crew (Orchestrator)
```
What is it?
  Orchestration layer that:
  - Coordinates agents
  - Passes context between them
  - Manages execution order
  - Collects and formats final output

Crew workflow:
  1. User submits form
  2. generate_event_plan() calls crew.kickoff()
  3. Crew instantiates agents with their roles
  4. Crew assigns tasks to agents in order
  5. Each task:
     - Agent reads context from previous task
     - Agent reasons and generates output
     - Output fed to next task
  6. Final agent outputs assembled
  7. Result returned as markdown

Why orchestrated approach:
  - Agents don't work in isolation
  - Sequential dependencies ensure quality
  - Context carries forward (agent 2 builds on agent 1)
  - More reliable than parallel reasoning
```

### Implementation Flow

```python
# crew.py
class EventManagementCrew:
    agents = [
        venue_scout_agent,
        logistics_coordinator_agent,
        budget_analyst_agent,
        marketing_lead_agent
    ]
    
    tasks = [
        venue_selection_task,
        logistics_planning_task,
        budget_optimization_task,
        marketing_plan_task
    ]

# event_planning_ui.py
result = event_management_crew.kickoff(inputs={
    "event_topic": "Tech Conference",
    "event_city": "San Francisco",
    "expected_participants": "500",
    "tentative_date": "2026-10-15",
    "budget": "50000",
    "venue_type": "Convention Center"
})
```

### Why CrewAI and Not Raw LLM?

```
❌ Raw LLM call:
   prompt = "Plan a tech conference for 500 in SF with $50k budget"
   response = llm(prompt)
   Issues:
   - No clear task structure
   - Prone to hallucination
   - Hard to debug intermediate steps
   - No role clarity

✅ Crew-based:
   - Each agent has defined role + expertise
   - Each task has clear deliverable
   - Context flows sequentially
   - Output is more structured
   - Easier to troubleshoot failures
```

---

## 6. Data Persistence

### venue_details.json
```
Purpose: Store selected venue's contact details

Structure:
  {
    "name": "Denver Convention Center",
    "address": "700 14th Street, Denver, CO",
    "capacity": "500",
    "booking_status": "Finalized",
    "contact_phone": "+1-720-865-4900",
    "contact_email": "bookings.center@denvenuvenues.com"
  }

How it's managed:
  - Created fresh when generate_event_plan() runs
  - Attempts live phone extraction from search
  - Falls back to "Not available" if search fails
  - Validates on load; regenerates if invalid/missing
  
Why a separate file:
  - Decoupled from final markdown (can update independently)
  - Venue info referenced in multiple places
  - Enables future integrations (booking systems, etc.)
```

### output/event_<topic>.md
```
Purpose: Final event plan artifact

Structure:
  # Event Plan Report
  ## Event Details
  - Topic, City, Date, Participants, Budget, Venue Type
  
  ## Finalized Venue Details
  - Name, Address, Capacity, Booking Status, Contact Phone, Email
  
  ## Logistics Checklist
  - Vendor shortlisting
  - AV setup
  - Staffing
  - Contingency allocation
  
  ## Marketing Plan
  - Launch announcement
  - Content cadence
  - Registration reminder
  
  ## Cost Estimation
  - Category breakdown (venue, catering, AV, etc.)
  
  ## Timeline
  - T-8 weeks through Event day milestones
  
  ## Weather Forecast
  - Approximate conditions for planning readiness
  
  ## Email Confirmation Draft
  - Stakeholder notification template

Why output file:
  - Auditability (event plans are records)
  - Shareable (email to team, attach to project)
  - Persistence (not lost if browser closes)
  - Future reference (what was planned vs. what happened)
  
Why markdown:
  - Human-readable plaintext
  - Can convert to PDF/Word easily
  - Git-friendly (version control)
  - Renders well in most tools
```

---

## Summary of Key Design Decisions

| Decision | Choice | Why Not Alternative |
|----------|--------|-------------------|
| UI Framework | Python HTTPServer + HTML | Streamlit/Flask adds complexity; this is minimal and fast |
| Venue Data | Live Google Search | Static dataset goes stale; Places API adds cost/setup |
| Phone Extraction | Regex pattern matching | Places API is more reliable but slower/paid |
| Intelligence | Modular functions | Monolithic LLM harder to debug, prone to hallucination |
| Final Plan | Crew-based agents | Raw LLM less structured, harder to troubleshoot |
| Output Format | Markdown file | HTML would be harder to version; JSON less readable |
| Validation | Early, before expensive ops | Late validation wastes search/crew budget |
| Fallbacks | Graceful degradation | Hard failures break UX |

---

## Future Improvement Opportunities

1. **Canonical Data Sources**
   - Replace search-based phone with Google Places API
   - Add ratings/reviews from canonical sources

2. **Confidence Scores**
   - Each intelligence module reports confidence (0-1)
   - Final output shows which insights are high/low confidence

3. **Source Citations**
   - Track where each fact came from
   - Add "Source: [URL]" to final report

4. **Interactive Refinement**
   - Let user adjust venue recommendations
   - Re-run intelligence for modified parameters
   - A/B compare different venue scenarios

5. **Testing & Observability**
   - Unit tests for parsing logic (phone extraction, venue type classification)
   - Telemetry on step drop-off and failure rates
   - Crew execution traces for debugging

6. **Performance**
   - Parallelize intelligence generation (run all searches concurrently)
   - Cache venue/vendor search results by city
   - Pre-warm recommendations on Step 1 form load

