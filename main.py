from datetime import datetime
import json
from pathlib import Path
import re
import warnings

from event_planning.safety_engine import evaluate_venue_profile


warnings.filterwarnings(
	"ignore",
	message="Mixing V1 models and V2 models.*CrewAgentExecutor.*",
	category=UserWarning,
)


def slugify(value: str) -> str:
	cleaned_value = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
	return cleaned_value.strip("_") or "topic"


def prompt_non_empty(prompt_text: str, field_name: str) -> str:
	while True:
		value = input(prompt_text).strip()
		if not value:
			print(f"{field_name} cannot be empty. Please enter it again.")
			continue
		return value


def prompt_menu_choice() -> str:
	while True:
		choice_value = input("Enter 1, 2, 3, 4, or 5: ").strip()
		if choice_value in {"1", "2", "3", "4", "5"}:
			return choice_value
		print("Invalid choice. Please enter 1, 2, 3, 4, or 5.")


def prompt_future_date(prompt_text: str) -> str:
	while True:
		date_value = prompt_non_empty(prompt_text, "Date")
		try:
			parsed_date = datetime.strptime(date_value, "%Y-%m-%d").date()
		except ValueError:
			print("Invalid date format. Use YYYY-MM-DD.")
			continue

		if parsed_date <= datetime.now().date():
			print("Invalid date: past date/month/year is not allowed. Please re-enter a future date.")
			continue

		return date_value


def prompt_positive_integer(prompt_text: str, field_name: str) -> str:
	while True:
		value = prompt_non_empty(prompt_text, field_name)

		if any(char in value for char in [".", ",", "/"]):
			print(f"Invalid {field_name}: decimals or fractions are not allowed.")
			continue

		if not value.isdigit():
			print(f"Invalid {field_name}: enter a non-negative whole number only.")
			continue

		if int(value) <= 0:
			print(f"Invalid {field_name}: value must be greater than 0.")
			continue

		return value


def prompt_safe_event_topic(prompt_text: str, max_attempts: int = 3) -> str | None:
	blocked_patterns = [
		# Violence-related
		r"\bkill\b", r"\bmurder\b", r"\battack\b", r"\bterror(?:ist|ism)?\b", r"\bbomb\b", r"\bblast\b",
		r"\bgun\b", r"\bshoot\b", r"\briot\b", r"\bwar\b", r"\bviolence\b", r"\bassault\b", r"\brape\b",
		r"\babuse(?:d|r|s)?\b", r"\btorture\b", r"\bpoison\b", r"\bknife\b", r"\bstab\b", r"\bslaughter\b",
		r"\bexecute\b", r"\bexecution\b", r"\bmassacre\b", r"\bgenocide\b", r"\barrmed\b", r"\bweapon\b",
		r"\bthreat\b", r"\bhate\b", r"\bextremis(?:m|t)\b", r"\bassassinat(?:e|ion)\b",
		
		# Crime-related
		r"\bcrime\b", r"\bcriminal\b", r"\btheft\b", r"\brobbery\b", r"\bburglary\b", r"\barson\b",
		r"\bfraud\b", r"\bhack(?:ing|er)?\b", r"\bcybercrime\b", r"\btraffick(?:ing|er)?\b", 
		r"\bsmuggl(?:ing|er)?\b", r"\bcartel\b", r"\bdrug\b",
		
		# Political/Controversial
		r"\belection\b", r"\bpolitic(?:al|s)?\b", r"\bparty\b", r"\bpropaganda\b", r"\bscandal\b",
		r"\bcontroversy\b", r"\bcontroversial\b", r"\bbias(?:ed)?\b", r"\bdiscriminat(?:ion|e|or)?\b",
		r"\bracist\b", r"\bracism\b", r"\bsexis(?:m|t)?\b", r"\bcoup\b", r"\brevolution\b", 
		r"\binsurrection\b",
		
		# Exploitation/Abuse
		r"\bexploitation\b", r"\bslavery\b", r"\bslave\b",
		
		# Danger/Hazard
		r"\bdanger(?:ous)?\b", r"\bhazard\b", r"\bnuke\b", r"\bnuclear\b", r"\bradioactive\b", 
		r"\bexplosive\b", r"\btoxic\b",
		
		# Death/Fatal
		r"\bsuicide\b", r"\bdeath\b", r"\bfatal\b",
		
		# Disease/Epidemic
		r"\bplague\b", r"\bepidemic\b", r"\bpandemic\b",
	]

	attempt = 0
	while attempt < max_attempts:
		topic = prompt_non_empty(prompt_text, "Event topic")
		normalized = topic.lower()

		is_blocked = any(re.search(pattern, normalized) for pattern in blocked_patterns)
		if is_blocked:
			attempt += 1
			if attempt < max_attempts:
				print(
					"Please enter a safe, neutral, non-political event topic. "
					"I cannot accept topics related to violence, threats, or controversy."
				)
				continue

			print(
				"I’m sorry, but I can’t proceed with this topic. "
				"Please restart and provide a safe, neutral event topic."
			)
			return None

		return topic

	return None


def ensure_venue_details_json(file_path: Path, fallback_data: dict) -> None:
	# Crew output can time out and leave this file empty/invalid; guarantee usable JSON.
	if not file_path.exists() or file_path.stat().st_size == 0:
		with open(file_path, "w", encoding="utf-8") as file:
			json.dump(fallback_data, file, indent=2)
		return

	try:
		with open(file_path, "r", encoding="utf-8") as file:
			loaded = json.load(file)
		if not isinstance(loaded, dict) or not loaded:
			raise ValueError("invalid venue details shape")
	except Exception:
		with open(file_path, "w", encoding="utf-8") as file:
			json.dump(fallback_data, file, indent=2)


def build_event_markdown_with_venue(base_result: str, file_path: Path) -> str:
	try:
		with open(file_path, "r", encoding="utf-8") as file:
			venue = json.load(file)
	except Exception:
		venue = {}

	venue_name = venue.get("name", "Not available")
	venue_address = venue.get("address", "Not available")
	venue_capacity = venue.get("capacity", "Not available")
	booking_status = venue.get("booking_status", "Not available")

	venue_section = (
		"\n\n## Finalized Venue Details\n"
		f"- Name: {venue_name}\n"
		f"- Address: {venue_address}\n"
		f"- Capacity: {venue_capacity}\n"
		f"- Booking Status: {booking_status}\n"
	)

	return f"{base_result}{venue_section}"


def build_fallback_event_plan(
	event_topic: str,
	event_city: str,
	expected_participants: str,
	tentative_date: str,
	budget: str,
	venue_type: str,
	venue: dict,
) -> str:
	return (
		"# Event Plan Summary\n\n"
		f"- Topic: {event_topic}\n"
		f"- City: {event_city}\n"
		f"- Date: {tentative_date}\n"
		f"- Expected Participants: {expected_participants}\n"
		f"- Budget: {budget}\n"
		f"- Preferred Venue Type: {venue_type}\n\n"
		"## Finalized Venue Details\n"
		f"- Name: {venue.get('name', 'Not available')}\n"
		f"- Address: {venue.get('address', 'Not available')}\n"
		f"- Capacity: {venue.get('capacity', 'Not available')}\n"
		f"- Booking Status: {venue.get('booking_status', 'Not available')}\n\n"
		"## Logistics Checklist\n"
		"- Catering vendor shortlisting completed\n"
		"- AV setup plan prepared (mics, speakers, projection, backup power)\n"
		"- Onsite staffing plan drafted\n"
		"- Contingency allocation reserved\n\n"
		"## Marketing Plan\n"
		"- Launch announcement across social and email\n"
		"- Weekly content cadence with speaker/event highlights\n"
		"- Registration reminder campaign\n"
	)


def apply_safety_to_venue_details(
	file_path: Path,
	event_city: str,
	expected_participants: str,
	venue_type: str,
) -> tuple[dict, str]:
	try:
		with open(file_path, "r", encoding="utf-8") as file:
			venue_data = json.load(file)
	except Exception:
		venue_data = {}

	candidate_profile = {
		"name": str(venue_data.get("name", "")).strip() or f"{event_city} Central {venue_type}",
		"address": str(venue_data.get("address", "")).strip() or f"100 Market St, {event_city}",
		"capacity": str(venue_data.get("capacity", "")).strip() or expected_participants,
		"booking_status": str(venue_data.get("booking_status", "")).strip() or "Finalized",
		"contact_phone": str(venue_data.get("contact_phone", "")).strip() or "Not available",
		"contact_email": str(venue_data.get("contact_email", "")).strip() or "Not available",
		"website": str(venue_data.get("website", "")).strip() or "https://maps.google.com",
		"source": str(venue_data.get("source", "")).strip() or "places",
	}

	safety = evaluate_venue_profile(candidate_profile, event_city)
	if safety.allowed:
		with open(file_path, "w", encoding="utf-8") as file:
			json.dump(safety.profile, file, indent=2)
		return safety.profile, ""

	safe_fallback = {
		"name": f"{event_city} Central {venue_type}",
		"address": f"100 Market St, {event_city}",
		"capacity": expected_participants,
		"booking_status": "Finalized",
		"contact_phone": "Not available",
		"contact_email": "Not available",
		"website": "https://maps.google.com",
		"source": "places",
	}

	fallback_safety = evaluate_venue_profile(safe_fallback, event_city)
	final_profile = fallback_safety.profile if fallback_safety.allowed else safe_fallback
	with open(file_path, "w", encoding="utf-8") as file:
		json.dump(final_profile, file, indent=2)

	return final_profile, safety.reason


output_dir = Path("output")
output_dir.mkdir(exist_ok=True)

print("\nWhich crew do you want to run?")
print("  1 - Blog Crew")
print("  2 - Customer Support Crew")
print("  3 - Customer Outreach Campaign")
print("  4 - Automate Event Planning")
print("  5 - Financial Analysis")
choice = prompt_menu_choice()

if choice == "1":
	from blog_crew.crew import crew
	topic = prompt_non_empty("Enter blog topic: ", "Blog topic")
	output_file = output_dir / f"{slugify(topic)}.md"
	result = crew.kickoff(inputs={"topic": topic})

elif choice == "2":
	from customer_support.crew import support_crew
	customer = prompt_non_empty("Enter customer name: ", "Customer name")
	issue = prompt_non_empty("Describe the issue: ", "Issue")
	output_file = output_dir / f"support_{slugify(customer)}.md"
	result = support_crew.kickoff(inputs={"customer": customer, "issue": issue})

elif choice == "3":
	from customer_outreach_campaign.crew import customer_outreach_crew
	lead_name = prompt_non_empty("Enter lead/company name: ", "Lead/company name")
	industry = prompt_non_empty("Enter industry: ", "Industry")
	key_decision_maker = prompt_non_empty("Enter key decision maker: ", "Key decision maker")
	position = prompt_non_empty("Enter decision maker position: ", "Decision maker position")
	milestone = prompt_non_empty("Enter recent milestone: ", "Recent milestone")
	output_file = output_dir / f"outreach_{slugify(lead_name)}.md"
	result = customer_outreach_crew.kickoff(
		inputs={
			"lead_name": lead_name,
			"industry": industry,
			"key_decision_maker": key_decision_maker,
			"position": position,
			"milestone": milestone,
		}
	)

elif choice == "4":
	from automate_event_planning.crew import event_management_crew
	event_topic = prompt_safe_event_topic("Enter event topic: ")
	if event_topic is None:
		exit(1)
	event_city = prompt_non_empty("Enter event city: ", "Event city")
	expected_participants = prompt_positive_integer(
		"Enter expected participants: ",
		"expected participants",
	)
	tentative_date = prompt_future_date(
		"Enter tentative date (YYYY-MM-DD): ",
	)
	budget = prompt_positive_integer(
		"Enter event budget: ",
		"budget",
	)
	venue_type = prompt_non_empty("Enter preferred venue type: ", "Preferred venue type")
	output_file = output_dir / f"event_{slugify(event_topic)}.md"
	result = event_management_crew.kickoff(
		inputs={
			"event_topic": event_topic,
			"event_city": event_city,
			"expected_participants": expected_participants,
			"tentative_date": tentative_date,
			"budget": budget,
			"venue_type": venue_type,
		}
	)
	ensure_venue_details_json(
		Path("venue_details.json"),
		{
			"name": f"{event_city} Central {venue_type}",
			"address": f"100 Market St, {event_city}",
			"capacity": expected_participants,
			"booking_status": "Finalized",
			"contact_phone": "Not available",
			"contact_email": "Not available",
			"website": "https://maps.google.com",
			"source": "places",
		},
	)
	venue_path = Path("venue_details.json")
	safe_venue_data, safety_warning = apply_safety_to_venue_details(
		venue_path,
		event_city,
		expected_participants,
		venue_type,
	)
	if safety_warning:
		print(f"Safety filter replaced selected venue: {safety_warning}")
	result_text = str(result)
	if "Agent stopped due to iteration limit or time limit" in result_text:
		result = build_fallback_event_plan(
			event_topic,
			event_city,
			expected_participants,
			tentative_date,
			budget,
			venue_type,
			safe_venue_data,
		)
	else:
		result = build_event_markdown_with_venue(result_text, venue_path)
		if safety_warning:
			result = (
				"\n\n## Safety Note\n"
				f"- Original venue output was replaced by safety guardrails: {safety_warning}\n"
			) + str(result)

elif choice == "5":
	from financial_analysis.crew import financial_trading_crew
	stock_selection = prompt_non_empty("Enter stock ticker (e.g. AAPL): ", "Stock ticker")
	initial_capital = prompt_positive_integer("Enter initial capital (USD): ", "Initial capital")
	risk_tolerance = prompt_non_empty("Enter risk tolerance (Low / Medium / High): ", "Risk tolerance")
	trading_strategy_preference = prompt_non_empty(
		"Enter trading strategy preference (e.g. Day Trading, Swing Trading): ",
		"Trading strategy preference",
	)
	news_impact = prompt_non_empty("Consider news impact? (True / False): ", "News impact consideration")
	output_file = output_dir / f"financial_{slugify(stock_selection)}.md"
	result = financial_trading_crew.kickoff(
		inputs={
			"stock_selection": stock_selection,
			"initial_capital": initial_capital,
			"risk_tolerance": risk_tolerance,
			"trading_strategy_preference": trading_strategy_preference,
			"news_impact_consideration": news_impact,
		}
	)

with open(output_file, "w", encoding="utf-8") as file:
	file.write(str(result))

print(f"\nSaved output to {output_file}")
print(result)
