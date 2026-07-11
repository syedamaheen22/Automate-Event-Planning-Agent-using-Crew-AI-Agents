# Run Steps

## Prerequisites

1. Make sure Ollama is installed on your machine.
2. Pull the model used by the agents:

```bash
ollama pull llama3.1:8b
```

3. Set Serper API key for live Google validation used by city and venue checks in the UI:

```bash
export SERPER_API_KEY="your_serper_api_key"
```

## How To Run The Code

Activate the Python 3.13 virtual environment:

```bash
source /Users/maheen-syed-mba/GenAi/.venv313/bin/activate
```

Then run the script:

```bash
python main.py
```

## Run Automate Event Planning UI

If you want a front-end form for event planning, run:

```bash
python event_planning_ui.py
```

Then open:

- http://127.0.0.1:8788

The UI will ask for:

- Event topic
- Event city
- Expected participants
- Tentative date
- Budget
- Preferred venue type

After submission, it generates the final response and saves output to `output/event_<topic>.md`.

## Where To See The Output

You can see the generated output in two places:

1. In the VS Code terminal after the script finishes.
2. In the `/Users/maheen-syed-mba/GenAi/crewAIAgents/output` folder.

Each run creates a Markdown file based on the selected input (topic/customer/lead/event/stock).