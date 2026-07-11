from pydantic import BaseModel
from crewai import Task

from automate_event_planning.agents import (
    logistics_manager,
    marketing_communications_agent,
    venue_coordinator,
)


class VenueDetails(BaseModel):
    name: str
    address: str
    capacity: str
    booking_status: str


venue_task = Task(
    description=(
        "Find a {venue_type} in {event_city} that meets criteria for {event_topic} "
        "and stays within a total venue budget of {budget}. "
        "Return ONLY a valid JSON object (no markdown, no backticks, no extra text) "
        "using exactly these keys: name, address, capacity, booking_status."
    ),
    expected_output=(
        '{{"name":"...","address":"...","capacity":"...","booking_status":"..."}}'
    ),
    human_input=False,
    output_json=VenueDetails,
    output_file="venue_details.json",
    agent=venue_coordinator,
)

logistics_task = Task(
    description=(
        "Coordinate catering and equipment for an event in {event_city} with "
        "{expected_participants} participants on {tentative_date} "
        "while keeping logistics aligned with the event budget of {budget}. "
        "Vendor preferences are: food type={food_type}, dietary requirements={dietary_requirements}, "
        "decor style={decor_style}, AV requirements={av_requirements}. "
        "Find local vendors and suppliers in {event_city} that match these preferences. "
        "If you use tools, call only these exact action names: "
        "'Search the internet' and 'Read website content'. "
        "Do not add markdown formatting, quotes, bullets, or extra characters to action names."
    ),
    expected_output=(
        "Confirmation of all logistics arrangements including catering "
        "and equipment setup."
    ),
    human_input=False,
    async_execution=False,
    agent=logistics_manager,
)

marketing_task = Task(
    description=(
        "Promote the {event_topic} in {event_city} aiming to engage at least "
        "{expected_participants} potential attendees. "
        "Research local marketing channels and communities in {event_city} to maximize reach. "
        "If you use tools, call only these exact action names: "
        "'Search the internet' and 'Read website content'. "
        "Do not add markdown formatting, quotes, bullets, or extra characters to action names."
    ),
    expected_output=(
        "Report on marketing activities and attendee engagement formatted "
        "as markdown."
    ),
    async_execution=False,
    agent=marketing_communications_agent,
)
