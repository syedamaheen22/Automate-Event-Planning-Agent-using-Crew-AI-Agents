import json
from pprint import pprint

from crewai import Crew

from automate_event_planning.agents import (
    logistics_manager,
    marketing_communications_agent,
    venue_coordinator,
)
from automate_event_planning.tasks import logistics_task, marketing_task, venue_task


event_management_crew = Crew(
    agents=[
        venue_coordinator,
        logistics_manager,
        marketing_communications_agent,
    ],
    tasks=[venue_task, logistics_task, marketing_task],
    verbose=True,
)


if __name__ == "__main__":
    event_details = {
        "event_topic": "AI in Education",
        "event_city": "San Francisco",
        "expected_participants": "250",
        "tentative_date": "2026-07-15",
        "budget": "20000",
        "venue_type": "Conference Hall",
    }

    result = event_management_crew.kickoff(inputs=event_details)
    print(result)

    with open("venue_details.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    pprint(data)
