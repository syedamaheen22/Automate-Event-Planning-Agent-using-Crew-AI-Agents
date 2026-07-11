from crewai import Agent
from crewai_tools import ScrapeWebsiteTool, SerperDevTool
from langchain_community.chat_models import ChatOllama


llm = ChatOllama(model="llama3.1:8b")

# Initialize tools
search_tool = SerperDevTool()
scrape_tool = ScrapeWebsiteTool()

venue_coordinator = Agent(
    role="Venue Coordinator",
    goal=(
        "Identify and book an appropriate venue "
        "based on event requirements"
    ),
    tools=[search_tool, scrape_tool],
    llm=llm,
    verbose=True,
    allow_delegation=False,
    max_iter=3,
    backstory=(
        "With a keen sense of space and understanding of event logistics, "
        "you excel at finding and securing the perfect venue that fits the "
        "event's theme, size, and budget constraints."
    ),
)

logistics_manager = Agent(
    role="Logistics Manager",
    goal=(
        "Manage all logistics for the event "
        "including catering and equipment"
    ),
    tools=[search_tool, scrape_tool],
    llm=llm,
    verbose=True,
    allow_delegation=False,
    max_iter=3,
    backstory=(
        "Organized and detail-oriented, you ensure that every logistical "
        "aspect of the event from catering to equipment setup is flawlessly "
        "executed to create a seamless experience."
    ),
)

marketing_communications_agent = Agent(
    role="Marketing and Communications Agent",
    goal=(
        "Effectively market the event and communicate with participants"
    ),
    tools=[search_tool, scrape_tool],
    llm=llm,
    verbose=True,
    allow_delegation=False,
    max_iter=3,
    backstory=(
        "Creative and communicative, you craft compelling messages and "
        "engage with potential attendees to maximize event exposure and "
        "participation."
    ),
)
