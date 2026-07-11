import html
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
  from dotenv import find_dotenv, load_dotenv
except Exception:
  find_dotenv = None
  load_dotenv = None

if load_dotenv and find_dotenv:
  # Load env vars from the nearest .env file when server starts.
  load_dotenv(find_dotenv(usecwd=True), override=False)

from event_planning.guardrails import review_form_guardrails, validate_city_and_venue_with_llm
from event_planning.intelligence import build_email_confirmation_draft, build_operations_insights
from event_planning.recommendations import (
  get_venue_recommendations,
  resolve_contact_details_for_selected_venue,
)
from event_planning.safety_engine import evaluate_venue_profile
from event_planning.validators import (
    estimate_venue_capacity,
    get_country_code_for_city,
    get_date_bandwidth_warning,
    get_time_based_greeting,
    validate_event_city,
    validate_future_date,
    validate_positive_integer,
    validate_preference_text,
    validate_venue_capacity,
    validate_venue_type_input,
)


HOST = "127.0.0.1"
PORT = 8788


# ISO 3166-1 alpha-2 country code → currency symbol/code (ISO 4217 standard data).
# Covers every sovereign state; unknown codes fall back to "$".
_COUNTRY_CURRENCY: dict[str, str] = {
    # Americas
    "us": "$",    "ca": "CA$",  "mx": "MX$",  "br": "R$",   "ar": "$",
    "cl": "$",    "co": "$",    "pe": "S/",    "uy": "$U",   "ve": "Bs.F",
    "bo": "Bs.",  "ec": "$",    "py": "₲",    "gy": "$",    "sr": "$",
    "cu": "$",    "do": "RD$",  "ht": "G",    "jm": "$",    "tt": "$",
    "bb": "$",    "bs": "$",    "bz": "$",    "gt": "Q",    "hn": "L",
    "ni": "C$",   "cr": "₡",   "pa": "B/.",
    # Europe
    "gb": "£",    "fr": "€",    "de": "€",    "es": "€",    "it": "€",
    "nl": "€",    "be": "€",    "at": "€",    "pt": "€",    "gr": "€",
    "ie": "€",    "fi": "€",    "lu": "€",    "sk": "€",    "si": "€",
    "ee": "€",    "lv": "€",    "lt": "€",    "cy": "€",    "mt": "€",
    "hr": "€",    "ch": "CHF",  "no": "kr",   "se": "kr",   "dk": "kr",
    "pl": "zł",   "cz": "Kč",  "hu": "Ft",   "ro": "lei",  "bg": "лв",
    "rs": "din",  "ua": "₴",    "tr": "₺",    "al": "L",    "ba": "KM",
    "mk": "ден",  "me": "€",    "xk": "€",    "md": "L",    "by": "Br",
    "am": "֏",    "az": "₼",    "ge": "₾",    "is": "kr",
    # Middle East / West Asia
    "ae": "AED",  "sa": "SAR",  "qa": "QAR",  "kw": "KD",   "bh": "BD",
    "om": "OMR",  "jo": "JD",   "il": "₪",    "lb": "£",    "sy": "£",
    "iq": "ID",   "ir": "﷼",    "ye": "﷼",
    # Asia-Pacific
    "in": "₹",   "pk": "₨",    "bd": "৳",    "lk": "₨",    "np": "₨",
    "cn": "¥",    "jp": "¥",    "kr": "₩",    "kp": "₩",    "tw": "NT$",
    "hk": "HK$",  "mo": "P",    "sg": "S$",   "my": "RM",   "id": "Rp",
    "th": "฿",    "ph": "₱",    "vn": "₫",    "mm": "K",    "kh": "KHR",
    "la": "₭",    "bn": "$",    "tl": "$",    "mn": "₮",    "af": "؋",
    "uz": "сум",  "kz": "₸",    "kg": "лв",   "tj": "SM",   "tm": "T",
    "au": "A$",   "nz": "$",    "fj": "$",    "pg": "K",    "sb": "$",
    "vu": "Vt",   "ws": "T",    "to": "T$",   "ki": "$",    "tv": "$",
    "nr": "$",    "pw": "$",    "fm": "$",    "mh": "$",
    # Africa
    "ng": "₦",    "za": "R",    "ke": "KSh",  "gh": "₵",    "et": "Br",
    "tz": "TSh",  "ug": "USh",  "eg": "£",    "ma": "MAD",  "dz": "DA",
    "tn": "DT",   "ly": "LD",   "sd": "SDG",  "so": "Sh",   "ss": "£",
    "cm": "FCFA", "cd": "FC",   "cg": "FCFA", "ci": "FCFA", "sn": "FCFA",
    "ml": "FCFA", "bf": "FCFA", "ne": "FCFA", "tg": "FCFA", "bj": "FCFA",
    "gn": "FG",   "sl": "Le",   "lr": "$",    "gm": "D",    "gw": "FCFA",
    "mr": "UM",   "ao": "Kz",   "mz": "MT",   "zm": "ZK",   "zw": "$",
    "bw": "P",    "na": "$",    "sz": "L",    "ls": "L",    "mg": "Ar",
    "mw": "MK",   "rw": "RF",   "bi": "Fr",   "dj": "Fdj",  "er": "Nfk",
    "km": "CF",   "sc": "SR",   "mu": "₨",    "cv": "$",    "st": "Db",
    "gq": "FCFA", "ga": "FCFA", "cf": "FCFA", "td": "FCFA",
}

# In-process cache: lowercase city name → resolved currency symbol.
_currency_cache: dict[str, str] = {}


def get_currency_for_city(city: str) -> str:
    """Dynamically resolve the currency for any city via Nominatim geocoding.
    Falls back to '$' when the city cannot be resolved."""
    lower = city.strip().lower()
    if not lower:
        return "$"
    if lower in _currency_cache:
        return _currency_cache[lower]
    try:
        country_code = get_country_code_for_city(city)
        symbol = _COUNTRY_CURRENCY.get(country_code, "$") if country_code else "$"
    except Exception:
        symbol = "$"
    _currency_cache[lower] = symbol
    return symbol


def get_currency_for_location(city: str, country_code: str = "") -> str:
  normalized_code = country_code.strip().lower()
  if normalized_code:
    return _COUNTRY_CURRENCY.get(normalized_code, get_currency_for_city(city))
  return get_currency_for_city(city)


# Non-English country names to English equivalents (from Nominatim responses)
_COUNTRY_NAME_NORMALIZATION: dict[str, str] = {
    "日本": "Japan",
    "中国": "China",
    "한국": "South Korea",
    "태국": "Thailand",
    "베트남": "Vietnam",
    "필리핀": "Philippines",
    "인도네시아": "Indonesia",
    "말레이시아": "Malaysia",
    "싱가포르": "Singapore",
    "홍콩": "Hong Kong",
    "대만": "Taiwan",
    "캄보디아": "Cambodia",
    "라오스": "Laos",
    "미얀마": "Myanmar",
    "방글라데시": "Bangladesh",
    "파키스탄": "Pakistan",
    "인도": "India",
    "스리랑카": "Sri Lanka",
    "네팔": "Nepal",
    "부탄": "Bhutan",
    "몰디브": "Maldives",
    "Deutschland": "Germany",
    "España": "Spain",
    "Schweiz/Suisse/Svizzera/Svizra": "Switzerland",
    "Schweiz": "Switzerland",
    "Suisse": "Switzerland",
    "Svizzera": "Switzerland",
    "Österreich": "Austria",
    "België / Belgique / Belgien": "Belgium",
    "Belgique": "Belgium",
    "België": "Belgium",
    "Brasil": "Brazil",
    "Россия": "Russia",
    "مصر": "Egypt",
    "Polska": "Poland",
    "Magyarország": "Hungary",
    "Sverige": "Sweden",
    "Norge": "Norway",
    "Danmark": "Denmark",
    "Suomi / Finland": "Finland",
    "Suomi": "Finland",
    "Türkiye": "Turkey",
    "ไทย": "Thailand",
    "Việt Nam": "Vietnam",
    "المملكة العربية السعودية": "Saudi Arabia",
    "إيران": "Iran",
    "ایران": "Iran",
    "ישראל": "Israel",
    "Italia": "Italy",
    "Nederland": "Netherlands",
    "Ελλάδα": "Greece",
    "Česko": "Czech Republic",
    "한국 / 대한민국": "South Korea",
    "대한민국": "South Korea",
    "中國": "China",
}


def resolve_city_country_options(city: str) -> list[dict[str, str]]:
  cleaned_city = city.strip()
  if not cleaned_city:
    return []

  params = urlencode(
    {
      "q": cleaned_city,
      "format": "jsonv2",
      "addressdetails": 1,
      "limit": 12,
    }
  )
  url = f"https://nominatim.openstreetmap.org/search?{params}"
  request = Request(
    url,
    headers={
      "User-Agent": "GenAiEventPlanner/1.0 (city-country-disambiguation)",
      "Accept-Language": "en",
    },
    method="GET",
  )

  try:
    with urlopen(request, timeout=6) as response:
      payload = json.loads(response.read().decode("utf-8"))
  except Exception:
    return []

  if not isinstance(payload, list):
    return []

  options_by_code: dict[str, dict[str, str]] = {}
  best_match_rank: dict[str, tuple[int, int, int]] = {}
  cleaned_city_lower = cleaned_city.lower()
  
  for rank, item in enumerate(payload):
    if not isinstance(item, dict):
      continue
    address = item.get("address", {}) if isinstance(item.get("address", {}), dict) else {}
    country_raw = str(address.get("country", "")).strip()
    country_code = str(address.get("country_code", "")).strip().upper()
    if not country_raw or not country_code:
      continue

    country = _COUNTRY_NAME_NORMALIZATION.get(country_raw, country_raw)

    state = str(
      address.get("state", "")
      or address.get("region", "")
      or address.get("county", "")
    ).strip()
    
    city_field = str(address.get("city", "")).strip().lower()
    town_field = str(address.get("town", "")).strip().lower()
    
    city_field_words = set(city_field.split()) if city_field else set()
    town_field_words = set(town_field.split()) if town_field else set()
    cleaned_city_words = set(cleaned_city_lower.split())
    
    is_exact_city_match = city_field == cleaned_city_lower
    is_exact_town_match = town_field == cleaned_city_lower
    is_city_substring_match = cleaned_city_lower in city_field.replace(" ", "")
    is_town_substring_match = cleaned_city_lower in town_field.replace(" ", "")
    is_city_word_match = cleaned_city_words <= city_field_words
    is_town_word_match = cleaned_city_words <= town_field_words
    
    has_state = bool(state)
    
    if is_exact_city_match or is_exact_town_match:
      quality = 0
    elif is_city_substring_match or is_town_substring_match or is_city_word_match or is_town_word_match:
      quality = 1
    else:
      quality = 2
    
    match_score = (0 if not has_state else 1, quality, rank)
    
    option = {
      "country": country,
      "country_code": country_code,
      "label": f"{country} ({country_code})" if not state else f"{country} ({country_code}) - {state}",
    }
    
    if country_code not in options_by_code:
      options_by_code[country_code] = option
      best_match_rank[country_code] = match_score
    else:
      if match_score < best_match_rank.get(country_code, (999, 999)):
        best_match_rank[country_code] = match_score

  options = list(options_by_code.values())
  if any(rank[0] == 0 for rank in best_match_rank.values()):
    options.sort(key=lambda row: best_match_rank.get(row.get("country_code"), (999, 999, 999)))
  else:
    options.sort(key=lambda row: row.get("country", "").lower())
  return options
  return options


def parse_country_options_json(raw_value: str) -> list[dict[str, str]]:
  try:
    parsed = json.loads(raw_value)
  except Exception:
    return []
  if not isinstance(parsed, list):
    return []

  options: list[dict[str, str]] = []
  for item in parsed:
    if not isinstance(item, dict):
      continue
    country = str(item.get("country", "")).strip()
    country_code = str(item.get("country_code", "")).strip().upper()
    label = str(item.get("label", "")).strip() or f"{country} ({country_code})"
    if not country or not country_code:
      continue
    options.append(
      {
        "country": country,
        "country_code": country_code,
        "label": label,
      }
    )
  return options


def clean_venue_value(value: object) -> str:
    text = str(value).strip()
    if text.lower() in {"string", "", "null", "none", "n/a", "na", "undefined"}:
        return "Not available"
    return text


def normalize_display_address(address_value: object, city_value: object) -> str:
  """Keep address visible in UI/final summary with a city-center fallback."""
  cleaned_address = clean_venue_value(address_value)
  if cleaned_address != "Not available":
    return cleaned_address

  cleaned_city = clean_venue_value(city_value)
  if cleaned_city != "Not available":
    return f"{cleaned_city} city center"
  return "Not available"


def slugify(value: str) -> str:
    cleaned_value = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return cleaned_value.strip("_") or "topic"


def ensure_venue_details_json(file_path: Path, fallback_data: dict) -> None:
    if not file_path.exists() or file_path.stat().st_size == 0:
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(fallback_data, file, indent=2)
        return

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            loaded = json.load(file)
        if not isinstance(loaded, dict) or not loaded:
            raise ValueError("invalid venue details shape")

        required_keys = [
            "name",
            "address",
            "capacity",
            "booking_status",
            "contact_phone",
            "contact_email",
        ]
        placeholder_values = {
          "string",
          "",
          "null",
          "none",
          "n/a",
          "na",
          "undefined",
          "+1-555-0100",
        }
        for key in required_keys:
            value = str(loaded.get(key, "")).strip().lower()
            if value in placeholder_values:
                raise ValueError("invalid placeholder venue details")
    except Exception:
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(fallback_data, file, indent=2)


def build_event_markdown_with_venue(base_result: str, file_path: Path) -> str:
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            venue = json.load(file)
    except Exception:
        venue = {}

    venue_name = clean_venue_value(venue.get("name", "Not available"))
    venue_address = clean_venue_value(venue.get("address", "Not available"))
    venue_capacity = clean_venue_value(venue.get("capacity", "Not available"))
    booking_status = clean_venue_value(venue.get("booking_status", "Not available"))
    contact_phone = clean_venue_value(venue.get("contact_phone", "Not available"))
    contact_email = clean_venue_value(venue.get("contact_email", "Not available"))

    venue_section = (
        "\n\n## Finalized Venue Details\n"
        f"- Name: {venue_name}\n"
        f"- Address: {venue_address}\n"
        f"- Capacity: {venue_capacity}\n"
        f"- Booking Status: {booking_status}\n"
        f"- Contact Phone: {contact_phone}\n"
        f"- Contact Email: {contact_email}\n"
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
        f"- Name: {clean_venue_value(venue.get('name', 'Not available'))}\n"
        f"- Address: {clean_venue_value(venue.get('address', 'Not available'))}\n"
        f"- Capacity: {clean_venue_value(venue.get('capacity', 'Not available'))}\n"
        f"- Booking Status: {clean_venue_value(venue.get('booking_status', 'Not available'))}\n\n"
        f"- Contact Phone: {clean_venue_value(venue.get('contact_phone', 'Not available'))}\n"
        f"- Contact Email: {clean_venue_value(venue.get('contact_email', 'Not available'))}\n\n"
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


def build_structured_final_markdown(
    form_data: dict[str, str],
    venue_path: Path,
    operations_insights: dict[str, object],
) -> str:
    try:
        with open(venue_path, "r", encoding="utf-8") as f:
            venue = json.load(f)
    except Exception:
        venue = {}

    topic = form_data.get("event_topic", "").strip()
    city = form_data.get("event_city", "").strip()
    date = form_data.get("tentative_date", "").strip()
    participants = form_data.get("expected_participants", "").strip()
    budget = form_data.get("budget", "").strip()
    currency = get_currency_for_city(city)
    venue_type = form_data.get("venue_type", "").strip()
    food_type = form_data.get("food_type", "").strip() or "No preference"
    dietary_requirements = form_data.get("dietary_requirements", "").strip() or "No preference"
    decor_style = form_data.get("decor_style", "").strip() or "No preference"
    av_requirements = form_data.get("av_requirements", "").strip() or "No preference"

    budget_breakdown = operations_insights.get("budget_breakdown", [])
    timeline = operations_insights.get("timeline", [])
    weather = str(operations_insights.get("weather", "Not available"))
    email_draft = str(operations_insights.get("email_confirmation", ""))

    budget_lines = "\n".join(
        f"- {row.get('category', '')}: {row.get('percent', '')} (~{row.get('amount', '')})"
        for row in budget_breakdown
    )
    timeline_lines = "\n".join(f"- {step}" for step in timeline)

    return (
        "# Event Plan Report\n\n"
        "## Event Details\n"
        f"- Topic: {topic}\n"
        f"- City: {city}\n"
      f"- Date: {date}\n"
      f"- Expected Participants: {participants}\n"
      f"- Budget: {currency} {budget}\n"
      f"- Preferred Venue Type: {venue_type}\n\n"
      "## Vendor Preferences\n"
      f"- Food Type: {food_type}\n"
      f"- Dietary Requirements: {dietary_requirements}\n"
      f"- Decor Style: {decor_style}\n"
      f"- AV Requirements: {av_requirements}\n\n"
      "## Finalized Venue Details\n"
      f"- Name: {clean_venue_value(venue.get('name', 'Not available'))}\n"
      f"- Address: {clean_venue_value(venue.get('address', 'Not available'))}\n"
      f"- Capacity: {clean_venue_value(venue.get('capacity', 'Not available'))}\n"
      f"- Booking Status: {clean_venue_value(venue.get('booking_status', 'Not available'))}\n"
      f"- Contact Phone: {clean_venue_value(venue.get('contact_phone', 'Not available'))}\n"
      f"- Contact Email: {clean_venue_value(venue.get('contact_email', 'Not available'))}\n\n"
      "## Logistics Checklist\n"
      "- Catering vendor shortlisting completed\n"
      "- AV setup plan prepared (mics, speakers, projection, backup power)\n"
      "- Onsite staffing plan drafted\n"
      "- Contingency allocation reserved\n\n"
      "## Marketing Plan\n"
      "- Launch announcement across social and email\n"
      "- Weekly content cadence with speaker/event highlights\n"
      "- Registration reminder campaign\n\n"
      "## Cost Estimation and Budget Breakdown\n"
      f"{budget_lines}\n\n"
      "## Timeline and Checklist\n"
      f"{timeline_lines}\n\n"
      "## Weather Forecast\n"
      f"- {weather}\n\n"
      "## Email Confirmation Draft\n"
      f"```text\n{email_draft}\n```\n"
    )

def build_selected_venue_summary(form_data: dict[str, str], venue: dict[str, str]) -> str:
  topic = form_data.get("event_topic", "").strip()
  city = form_data.get("event_city", "").strip()
  date = form_data.get("tentative_date", "").strip()
  participants = form_data.get("expected_participants", "").strip()
  budget = form_data.get("budget", "").strip()
  currency = get_currency_for_city(city)
  preferred_venue_type = form_data.get("venue_type", "").strip()
  food_type = form_data.get("food_type", "").strip() or "No preference"
  dietary_requirements = form_data.get("dietary_requirements", "").strip() or "No preference"
  decor_style = form_data.get("decor_style", "").strip() or "No preference"
  av_requirements = form_data.get("av_requirements", "").strip() or "No preference"
  email_draft = build_email_confirmation_draft(form_data, preferred_venue_type)

  return (
    "# Event Plan Summary\n\n"
    "## Event Details\n"
    f"- Topic: {topic}\n"
    f"- City: {city}\n"
    f"- Date: {date}\n"
    f"- Expected Participants: {participants}\n"
    f"- Budget: {currency} {budget}\n"
    f"- Preferred Venue Type: {preferred_venue_type}\n\n"
    "## Preferences\n"
    f"- Food Type: {food_type}\n"
    f"- Dietary Requirements: {dietary_requirements}\n"
    f"- Decor Style: {decor_style}\n"
    f"- AV Requirements: {av_requirements}\n\n"
    "## Selected Venue\n"
    f"- Name: {clean_venue_value(venue.get('name', 'Not available'))}\n"
    f"- Address: {normalize_display_address(venue.get('address', 'Not available'), city)}\n"
    f"- Capacity: {clean_venue_value(venue.get('capacity', 'Not available'))}\n"
    f"- Booking Status: {clean_venue_value(venue.get('booking_status', 'Finalized'))}\n"
    f"- Contact No.: {clean_venue_value(venue.get('contact_phone', 'Not available'))}\n"
    f"- Contact Email: {clean_venue_value(venue.get('contact_email', 'Not available'))}\n\n"
    "## Email Confirmation Draft\n"
    f"```text\n{email_draft}\n```\n"
  )


def render_page(
    error: str = "",
    result: str = "",
    output_file: str = "",
    form_data: dict[str, str] | None = None,
    field_errors: dict[str, str] | None = None,
    field_warnings: dict[str, str] | None = None,
    venue_recommendations: list[dict[str, object]] | None = None,
    selection_error: str = "",
    operations_insights: dict[str, object] | None = None,
    location_success: str = "",
) -> str:
    form_data = form_data or {}
    field_errors = field_errors or {}
    field_warnings = field_warnings or {}
    venue_recommendations = venue_recommendations or []
    operations_insights = operations_insights or {}

    def field(name: str, default: str = "") -> str:
        return html.escape(form_data.get(name, default))

    def field_error(name: str) -> str:
        return html.escape(field_errors.get(name, ""))

    def field_warning(name: str) -> str:
        return html.escape(field_warnings.get(name, ""))

    def input_class(name: str) -> str:
        return "input-error" if name in field_errors else ""

    safe_error = html.escape(error)
    safe_result = html.escape(result)
    safe_output = html.escape(output_file)
    safe_selection_error = html.escape(selection_error)
    safe_location_success = html.escape(location_success)
    location_verified = form_data.get("location_verified", "").strip().lower() == "true"
    country_selection_required = form_data.get("country_selection_required", "").strip().lower() == "true"
    country_options = parse_country_options_json(form_data.get("country_options_json", ""))

    greeting = get_time_based_greeting()
    safe_intro_line = html.escape(
        f"Hello, {greeting}! Fill in event details to start your plan."
    )

    if result:
        current_step = 4
    elif selection_error:
        current_step = 3
    elif venue_recommendations:
        current_step = 2
    else:
        current_step = 1

    selected_venue = form_data.get("selected_venue_type", "")
    expected_participants_str = form_data.get("expected_participants", "0")
    try:
        expected_participants_int = int(expected_participants_str.strip())
    except ValueError:
        expected_participants_int = 0

    option_cards: list[str] = []
    selectable_venue_count = 0
    selected_venue_is_selectable = False
    for item in venue_recommendations:
        name_raw = str(item.get("name", ""))
        name = html.escape(name_raw)
        address_value = normalize_display_address(
            item.get("address", "Not available"),
            form_data.get("event_city", ""),
        )
        address = html.escape(address_value)
        contact_email = html.escape(str(item.get("contact_email", "Not available")))
        contact_phone = html.escape(str(item.get("contact_phone", "Not available")))
        website_raw = str(item.get("website", "Not available")).strip() or "Not available"
        website = html.escape(website_raw)
        source = html.escape(str(item.get("source", "places")))
        google_link = item.get("google_link")
        google_link_html = f'<a href="{html.escape(google_link)}" target="_blank" rel="noopener">View on Google</a>' if google_link else ""
        if website_raw != "Not available" and website_raw.startswith(("http://", "https://")):
            website_display_html = f'<a href="{html.escape(website_raw)}" target="_blank" rel="noopener">Official site</a>'
        else:
            website_display_html = website
        if website_raw != "Not available" and google_link_html:
            website_row_html = f"{website_display_html} | {google_link_html}"
        else:
            website_row_html = website_display_html if website_raw != "Not available" else google_link_html
        pros = item.get("pros", [])
        cons = item.get("cons", [])
        perks_html = "".join(f"<li>{html.escape(str(perk))}</li>" for perk in pros[:3])
        cons_html = "".join(f"<li>{html.escape(str(con))}</li>" for con in cons[:3])
        checked = "checked" if selected_venue == name_raw else ""
        selected_cls = " selected" if checked else ""

        estimated_cap = estimate_venue_capacity(name_raw)
        cap_warning = validate_venue_capacity(name_raw, expected_participants_str)
        over_capacity = expected_participants_int > estimated_cap if expected_participants_int > 0 else False
        disabled = "disabled" if over_capacity else ""
        disabled_cls = " disabled" if over_capacity else ""
        if not over_capacity:
            selectable_venue_count += 1
            if selected_venue == name_raw:
                selected_venue_is_selectable = True
        if cap_warning:
            over = over_capacity
            badge_color = "#b91c1c" if over else "#92400e"
            badge_bg = "#fef2f2" if over else "#fffbeb"
            badge_border = "#fecaca" if over else "#fde68a"
            badge_icon = "⚠️ Over capacity" if over else "⚠️ Near capacity"
            cap_badge_html = (
                f"<div style='margin:6px 0;padding:6px 10px;border-radius:8px;"
                f"background:{badge_bg};border:1px solid {badge_border};"
                f"color:{badge_color};font-size:12px;font-weight:600;'>"
                f"{badge_icon} — est. max ~{estimated_cap} people"
                f"</div>"
            )
            cap_data_attr = f'data-cap-warn="true" data-cap-over="{"true" if over else "false"}"'
        else:
            cap_badge_html = ""
            cap_data_attr = 'data-cap-warn="false"'

        option_cards.append(
            f"""
            <label class="venue-option{selected_cls}{disabled_cls}" data-name="{name}" data-address="{address}" data-email="{contact_email}" data-phone="{contact_phone}" data-website="{website}" data-google-link="{html.escape(str(google_link or ""))}" data-source="{source}" {cap_data_attr}>
              <div class="venue-head">
                <input type="radio" name="selected_venue_type" value="{name}" {checked} {disabled} required />
                <span class="venue-name">{name}</span>
              </div>
              <div class="venue-detail-row"><span class="venue-detail-label">Address:</span><span>{address}</span></div>
              <div class="venue-detail-row"><span class="venue-detail-label">Email:</span><span class="venue-contact-email">{contact_email}</span></div>
              <div class="venue-detail-row"><span class="venue-detail-label">Contact No.:</span><span class="venue-contact-phone">{contact_phone}</span></div>
              <div class="venue-detail-row"><span class="venue-detail-label">Website:</span><span>{website_row_html}</span></div>
              {cap_badge_html}
              <div class="venue-meta">
                <div>
                  <strong>Perks</strong>
                  <ul>{perks_html}</ul>
                </div>
                <div>
                  <strong>Cons</strong>
                  <ul>{cons_html}</ul>
                </div>
              </div>
            </label>
            """
        )

    hidden_fields = []
    for key, value in form_data.items():
      if key in {"selected_venue_type", "action"}:
        continue
      hidden_fields.append(
        f"<input type=\"hidden\" name=\"{html.escape(str(key))}\" value=\"{html.escape(str(value))}\" />"
      )

    selection_banner = ""
    if venue_recommendations and selectable_venue_count == 0:
      selection_banner = (
        '<div id="venueCapacityBanner" class="error">'
        'All recommended venues are below your required guest capacity. '
        'Please choose some other venue or reduce the guest count.'
        '</div>'
      )
    elif venue_recommendations:
      selection_banner = (
        '<div id="venueCapacityBanner" class="error" style="display:none;">'
        'Please choose some other venue. The selected option cannot support your guest count.'
        '</div>'
      )

    # Step 2 tabs
    tab_buttons = ""
    tab_panels = ""
    if operations_insights:
        availability = operations_insights.get("availability", [])
        budget_breakdown = operations_insights.get("budget_breakdown", [])
        vendors = operations_insights.get("vendors", {})
        timeline = operations_insights.get("timeline", [])
        weather = html.escape(str(operations_insights.get("weather", "Not available")))
        accommodation = operations_insights.get("accommodation", [])
        transport = operations_insights.get("transport", [])
        accessibility = operations_insights.get("accessibility", [])
        comparison = operations_insights.get("comparison", [])
        email_confirmation = html.escape(str(operations_insights.get("email_confirmation", "")))

        availability_html = "".join(
            f"<li><strong>{html.escape(str(item.get('venue', 'Venue')))}:</strong> "
            f"{html.escape(str(item.get('status', 'Unknown')))} "
            f"<span class='subtle'>{html.escape(str(item.get('source_note', '')))}</span></li>"
            for item in availability
        )
        budget_html = "".join(
            f"<li>{html.escape(str(row.get('category', '')))} - {html.escape(str(row.get('percent', '')))} "
            f"(~{html.escape(str(row.get('amount', '')))} )</li>"
            for row in budget_breakdown
        )
        vendor_parts: list[str] = []
        for category, picks in vendors.items():
            entries = "".join(
                f"<li>{html.escape(str(pick.get('name', '')))} | {html.escape(str(pick.get('review', '')))}</li>"
                for pick in picks
            )
            vendor_parts.append(f"<p><strong>{html.escape(str(category))}</strong></p><ul>{entries}</ul>")
        vendor_html = "".join(vendor_parts)

        timeline_html = "".join(f"<li>{html.escape(str(step))}</li>" for step in timeline)
        accommodation_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in accommodation)
        transport_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in transport)
        accessibility_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in accessibility)
        comparison_html = "".join(
            "<tr>"
            f"<td>{html.escape(str(row.get('venue', '')))}</td>"
            f"<td>{html.escape(str(row.get('fit', '')))}</td>"
            f"<td>{html.escape(str(row.get('budget_fit', '')))}</td>"
            f"<td>{html.escape(str(row.get('score', '')))}</td>"
            "</tr>"
            for row in comparison
        )

        tabs = [
            ("availability", "Availability", f"<ul>{availability_html}</ul>"),
            ("budget", "Budget", f"<ul>{budget_html}</ul>"),
            ("vendors", "Vendors", vendor_html),
            ("timeline", "Timeline", f"<ul>{timeline_html}</ul>"),
            ("weather", "Weather", f"<p>{weather}</p>"),
            ("accommodation", "Accommodation", f"<ul>{accommodation_html}</ul>"),
            ("transport", "Transport", f"<ul>{transport_html}</ul>"),
            ("accessibility", "Accessibility", f"<ul>{accessibility_html}</ul>"),
            (
                "comparison",
                "Comparison",
                "<table class='comparison-table'><thead><tr><th>Venue</th><th>Capacity Fit</th><th>Budget Fit</th><th>Score</th></tr></thead>"
                f"<tbody>{comparison_html}</tbody></table>",
            ),
            ("email", "Email Draft", f"<pre class='email-draft'>{email_confirmation}</pre>"),
        ]

        tab_buttons = "".join(
            f"<button type='button' class='tab-btn{' active' if i == 0 else ''}' data-tab='{tab_id}'>{label}</button>"
            for i, (tab_id, label, _) in enumerate(tabs)
        )
        tab_panels = "".join(
            f"<div class='tab-panel{' active' if i == 0 else ''}' id='tab-{tab_id}'>{content}</div>"
            for i, (tab_id, _, content) in enumerate(tabs)
        )

    if location_verified:
      resolved_country_raw = form_data.get("resolved_country", "").strip()
      resolved_country_code_raw = form_data.get("resolved_country_code", "").strip().upper()
      resolved_country_display = ""
      if resolved_country_raw:
        resolved_country_display = resolved_country_raw
        if resolved_country_code_raw:
          resolved_country_display = f"{resolved_country_raw} ({resolved_country_code_raw})"

      country_display_html = ""
      if resolved_country_display:
        country_display_html = f"""
        <div>
          <label for="resolved_country_display">Resolved Country</label>
          <input id="resolved_country_display" value="{html.escape(resolved_country_display)}" readonly style="background:#f0fdf4;color:#166534;font-weight:600;border-color:#86efac;" />
        </div>
        """

        step1_form_html = f"""
        {f'<div class="success">{safe_location_success}</div>' if safe_location_success else ''}

        <form id="eventForm" data-show-loader="true" method="post" action="/">
          {''.join(hidden_fields)}
          <div class="grid">
            <div>
              <label for="event_city">Event City</label>
              <input id="event_city" name="event_city" value="{field('event_city')}" readonly />
              {f'<div class="field-error">{field_error("event_city")}</div>' if field_error('event_city') else ''}
            </div>
            <div>
              <label for="venue_type">Preferred Venue Type</label>
              <input id="venue_type" name="venue_type" value="{field('venue_type')}" readonly />
              {f'<div class="field-error">{field_error("venue_type")}</div>' if field_error('venue_type') else ''}
            </div>
            {country_display_html}
            <div class="full">
              <label for="event_topic">Event Topic</label>
              <input class="{input_class('event_topic')}" id="event_topic" name="event_topic" value="{field('event_topic')}" required />
              {f'<div class="field-error">{field_error("event_topic")}</div>' if field_error('event_topic') else ''}
            </div>
            <div>
              <label for="expected_participants">Expected Participants</label>
              <input class="{input_class('expected_participants')}" id="expected_participants" name="expected_participants" inputmode="numeric" value="{field('expected_participants')}" required />
              {f'<div class="field-error">{field_error("expected_participants")}</div>' if field_error('expected_participants') else ''}
            </div>
            <div>
              <label for="budget">Budget</label>
              <div class="budget-input-group">
                <span class="currency-badge">{html.escape(get_currency_for_location(form_data.get('event_city', ''), form_data.get('resolved_country_code', '')))}</span>
                <input class="{input_class('budget')}" id="budget" name="budget" inputmode="numeric" value="{field('budget')}" required />
              </div>
              {f'<div class="field-error">{field_error("budget")}</div>' if field_error('budget') else ''}
            </div>
            <div>
              <label for="tentative_date">Tentative Date (YYYY-MM-DD)</label>
              <input class="{input_class('tentative_date')}" id="tentative_date" name="tentative_date" placeholder="2026-12-31" value="{field('tentative_date')}" required />
              {f'<div class="field-error">{field_error("tentative_date")}</div>' if field_error('tentative_date') else ''}
              {f'<div class="field-warning">{field_warning("tentative_date")}</div>' if field_warning('tentative_date') else ''}
            </div>
            <div>
              <label for="food_type">Food Type Preference (optional)</label>
              <input class="{input_class('food_type')}" id="food_type" name="food_type" placeholder="e.g., Indian, Continental, Mixed" value="{field('food_type')}" />
              {f'<div class="field-error">{field_error("food_type")}</div>' if field_error('food_type') else ''}
            </div>
            <div>
              <label for="dietary_requirements">Dietary Requirements (optional)</label>
              <input class="{input_class('dietary_requirements')}" id="dietary_requirements" name="dietary_requirements" placeholder="e.g., Vegan, Halal, Gluten-Free" value="{field('dietary_requirements')}" />
              {f'<div class="field-error">{field_error("dietary_requirements")}</div>' if field_error('dietary_requirements') else ''}
            </div>
            <div>
              <label for="decor_style">Decor Style (optional)</label>
              <input class="{input_class('decor_style')}" id="decor_style" name="decor_style" placeholder="e.g., Minimal, Rustic, Corporate" value="{field('decor_style')}" />
              {f'<div class="field-error">{field_error("decor_style")}</div>' if field_error('decor_style') else ''}
            </div>
            <div>
              <label for="av_requirements">AV Requirements (optional)</label>
              <input class="{input_class('av_requirements')}" id="av_requirements" name="av_requirements" placeholder="e.g., LED wall, 2 mics, live streaming" value="{field('av_requirements')}" />
              {f'<div class="field-error">{field_error("av_requirements")}</div>' if field_error('av_requirements') else ''}
            </div>
          </div>
          <div class="button-row">
            <button type="submit" name="action" value="back_to_location" formnovalidate>Back</button>
            <button type="submit" name="action" value="recommend">Find Best Venue Types</button>
          </div>
        </form>
        """
    elif country_selection_required and country_options:
        selected_country_code = form_data.get("selected_country_code", "").strip().upper()
        option_cards = "".join(
          (
            f"<label class='venue-option{' selected' if selected_country_code == row['country_code'] else ''}'>"
            "<div class='venue-head country-option-head'>"
            f"<input type='radio' name='selected_country_code' value='{html.escape(row['country_code'])}' {'checked' if selected_country_code == row['country_code'] else ''} required />"
            f"<span class='venue-name country-option-name'>{html.escape(row['label'])}</span>"
            "</div>"
            "</label>"
          )
          for row in country_options
        )

        step1_form_html = f"""
        <div style="margin-bottom:14px;padding:12px 14px;border-radius:10px;background:#fffbeb;border:1px solid #fde68a;color:#92400e;font-weight:600;">
          Multiple countries matched the city <strong>{field('event_city')}</strong>. Please choose one country to continue.
        </div>

        <form method="post" action="/">
          {''.join(hidden_fields)}
          <div class="venue-options" style="grid-template-columns:1fr;">{option_cards}</div>
          <div class="button-row">
            <button type="submit" name="action" value="back_to_location" formnovalidate style="background:#e2e8f0;color:#0f172a;">Back</button>
            <button type="submit" name="action" value="confirm_country">Continue with selected country</button>
          </div>
        </form>
        """
    else:
        step1_form_html = f"""
        <p style="margin-bottom:12px;color:#0f172a;font-weight:600;">Fill city and venue type first. We will validate both with the LLM before showing remaining fields.</p>

        <form id="locationVerifyForm" data-show-loader="true" method="post" action="/">
          <input type="hidden" name="action" value="verify_location" />
          <div class="grid">
            <div>
              <label for="event_city">Event City</label>
              <input class="{input_class('event_city')}" id="event_city" name="event_city" value="{field('event_city')}" required />
              {f'<div class="field-error">{field_error("event_city")}</div>' if field_error('event_city') else ''}
            </div>
            <div>
              <label for="venue_type">Preferred Venue Type</label>
              <input class="{input_class('venue_type')}" id="venue_type" name="venue_type" value="{field('venue_type')}" required />
              {f'<div class="field-error">{field_error("venue_type")}</div>' if field_error('venue_type') else ''}
            </div>
          </div>
          <div class="button-row">
            <button type="submit">Validate City and Venue</button>
          </div>
        </form>
        """

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Automate Event Planning UI</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --card: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --primary: #0f766e;
      --danger: #b91c1c;
      --border: #d8dee9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #e2f5f3 0%, var(--bg) 30%);
      color: var(--text);
    }}
    .container {{ max-width: 980px; margin: 0 auto; padding: 20px; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 20px;
      box-shadow: 0 12px 34px rgba(2, 6, 23, 0.08);
      margin-bottom: 16px;
    }}
    h1 {{ margin: 0 0 8px; color: #134e4a; }}
    h2 {{ margin: 0 0 10px; color: #0f172a; }}
    p {{ color: var(--muted); margin-top: 0; }}
    .intro {{ font-size: 17px; line-height: 1.45; margin-bottom: 14px; }}

    .stepper {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 16px; }}
    .step {{
      border: 1px solid var(--border);
      background: #f8fafc;
      border-radius: 10px;
      text-align: center;
      padding: 10px;
      font-weight: 700;
      color: #475569;
      font-size: 13px;
    }}
    .step.active {{ background: #ccfbf1; border-color: #5eead4; color: #134e4a; }}

    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .full {{ grid-column: 1 / -1; }}
    label {{ display: block; font-weight: 600; margin-bottom: 6px; }}
    input {{
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 10px;
      font-size: 15px;
    }}
    .input-error {{ border-color: #fca5a5; background: #fff7f7; }}
    .field-error {{ margin-top: 6px; color: var(--danger); font-size: 13px; font-weight: 600; }}
    .budget-input-group {{ display: flex; align-items: stretch; }}
    .budget-input-group input {{ border-radius: 0 10px 10px 0; border-left: none; flex: 1; min-width: 0; }}
    .budget-input-group input.input-error {{ border-left: none; }}
    .currency-badge {{
      display: flex; align-items: center; padding: 0 13px;
      background: #eef2ff; border: 1px solid var(--border);
      border-right: none; border-radius: 10px 0 0 10px;
      font-weight: 700; color: var(--primary); font-size: 15px;
      white-space: nowrap; user-select: none;
    }}
    .field-warning {{ margin-top: 6px; color: #92400e; font-size: 13px; font-weight: 600; }}

    .button-row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }}
    button, .btn-link {{
      background: var(--primary);
      color: #fff;
      border: none;
      padding: 11px 16px;
      border-radius: 10px;
      cursor: pointer;
      font-weight: 700;
      font-size: 15px;
      text-decoration: none;
      display: inline-block;
    }}
    .btn-link.alt, button.alt {{
      background: #fff;
      color: var(--primary);
      border: 1px solid var(--primary);
    }}

    .error {{
      border: 1px solid #fecaca;
      background: #fef2f2;
      color: var(--danger);
      border-radius: 10px;
      padding: 10px 12px;
      margin-bottom: 14px;
      white-space: pre-wrap;
    }}
    .success {{
      border: 1px solid #bbf7d0;
      background: #f0fdf4;
      color: #166534;
      border-radius: 10px;
      padding: 10px 12px;
      margin-bottom: 14px;
    }}

    .panel {{ display: none; }}
    .panel.active {{ display: block; }}

    .tabs {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }}
    .tab-btn {{
      background: #f1f5f9;
      color: #334155;
      border: 1px solid #cbd5e1;
      border-radius: 999px;
      padding: 7px 12px;
      font-size: 13px;
    }}
    .tab-btn.active {{ background: #ccfbf1; color: #115e59; border-color: #5eead4; }}
    .tab-panel {{ display: none; border-top: 1px solid #e2e8f0; padding-top: 12px; }}
    .tab-panel.active {{ display: block; }}
    .subtle {{ color: #64748b; font-size: 12px; }}

    .venue-options {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 8px;
    }}
    .venue-option {{
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      background: #fcfdff;
      display: block;
      cursor: pointer;
    }}
    .venue-option.selected {{ border-color: #14b8a6; background: #f0fdfa; }}
    .venue-option:hover {{ border-color: #94a3b8; background: #f8fafc; }}
    .venue-option.disabled {{ opacity: 0.62; cursor: not-allowed; background: #f8fafc; }}
    .venue-option.disabled:hover {{ border-color: var(--border); background: #f8fafc; }}
    .venue-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
    .venue-head input[type="radio"] {{ width: 16px; height: 16px; margin: 0; }}
    .venue-head input[type="radio"]:disabled {{ cursor: not-allowed; }}
    .venue-name {{ font-weight: 700; color: #0f172a; }}
    .country-option-head {{ justify-content: flex-start; text-align: left; margin-bottom: 0; }}
    .country-option-name {{ text-align: left; }}
    .venue-detail-row {{
      display: grid;
      grid-template-columns: 92px 1fr;
      gap: 8px;
      color: #475569;
      font-size: 13px;
      margin-bottom: 6px;
      align-items: start;
    }}
    .venue-detail-label {{ font-weight: 700; color: #334155; }}
    .venue-meta {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .venue-meta strong {{ color: #0f172a; font-size: 13px; }}
    .venue-meta ul {{ margin: 6px 0 0; padding-left: 16px; color: #334155; font-size: 13px; line-height: 1.35; }}

    .comparison-table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    .comparison-table th, .comparison-table td {{ border: 1px solid #cbd5e1; padding: 8px; text-align: left; }}
    .email-draft {{
      white-space: pre-wrap;
      background: #f8fafc;
      color: #0f172a;
      border: 1px solid #cbd5e1;
      border-radius: 10px;
      padding: 12px;
    }}
    pre.output {{
      white-space: pre-wrap;
      background: #0b1120;
      color: #e2e8f0;
      border-radius: 10px;
      padding: 14px;
      overflow: auto;
      line-height: 1.5;
    }}

    .loading-backdrop {{
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.28);
      backdrop-filter: blur(4px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 999;
      padding: 16px;
    }}
    .loading-backdrop.show {{ display: flex; }}
    .loading-modal {{
      width: min(520px, 100%);
      background: #ffffff;
      border: 1px solid #cbd5e1;
      border-radius: 14px;
      box-shadow: 0 20px 50px rgba(15, 23, 42, 0.24);
      padding: 24px;
      text-align: center;
    }}
    .loading-title {{ margin: 0; color: #0f172a; font-size: 20px; font-weight: 700; }}
    .spinner {{
      width: 44px;
      height: 44px;
      margin: 0 auto 14px;
      border-radius: 50%;
      border: 4px solid #dbeafe;
      border-top-color: var(--primary);
      animation: spin 1s linear infinite;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    .dimmed {{ filter: blur(2px) saturate(0.9); pointer-events: none; user-select: none; }}

    @media (max-width: 760px) {{
      .grid, .venue-options, .venue-meta {{ grid-template-columns: 1fr; }}
      .stepper {{ grid-template-columns: repeat(2, 1fr); }}
    }}
  </style>
</head>
<body>
  <div id="pageContent" class="container">
    <div class="stepper">
      <div id="stepper1" class="step {'active' if current_step == 1 else ''}">1. Event Details</div>
      <div id="stepper2" class="step {'active' if current_step == 2 else ''}">2. Intelligence</div>
      <div id="stepper3" class="step {'active' if current_step == 3 else ''}">3. Venue Selection</div>
      <div id="stepper4" class="step {'active' if current_step == 4 else ''}">4. Final Plan</div>
    </div>

    <div class="panel {'active' if current_step == 1 else ''}" id="step1">
      <div class="card">
        <h1>Automate Event Planning</h1>
        <p class="intro">{safe_intro_line}</p>
        {f'<div class="error">{safe_error}</div>' if safe_error else ''}
        {step1_form_html}
      </div>
    </div>

    <div class="panel {'active' if current_step == 2 else ''}" id="step2">
      <div class="card">
        <h2>Planning Intelligence</h2>
        <p>Explore one insight at a time, then continue to venue selection.</p>
        <div class="tabs">{tab_buttons}</div>
        {tab_panels}
        <div class="button-row">
          <button type="button" class="alt" id="backToStep1">Back</button>
          <button type="button" id="toStep3">Continue to Venue Selection</button>
        </div>
      </div>
    </div>

    <div class="panel {'active' if current_step == 3 else ''}" id="step3">
      <div class="card">
        <h2>Choose a Venue Type</h2>
        <p>Select one recommended venue type and generate your final plan.</p>
        {f'<div class="error">{safe_selection_error}</div>' if safe_selection_error else ''}
        {selection_banner}
        {'<div style="margin-bottom:12px;padding:10px 14px;border-radius:10px;background:#fffbeb;border:1px solid #fde68a;color:#92400e;font-size:13px;font-weight:600;">⚠️ High attendance event (' + str(expected_participants_int) + ' participants). Check each venue&apos;s capacity badge before confirming.</div>' if expected_participants_int > 500 else ''}

        <form id="venueSelectForm" method="post" action="/">
          {''.join(hidden_fields)}
          <input type="hidden" name="action" value="final" />
          <input type="hidden" name="selected_venue_address" id="selectedVenueAddress" value="" />
          <input type="hidden" name="selected_venue_email" id="selectedVenueEmail" value="" />
          <input type="hidden" name="selected_venue_phone" id="selectedVenuePhone" value="" />
          <input type="hidden" name="selected_venue_website" id="selectedVenueWebsite" value="" />
          <input type="hidden" name="selected_venue_google_link" id="selectedVenueGoogleLink" value="" />
          <input type="hidden" name="selected_venue_source" id="selectedVenueSource" value="" />
          <div class="venue-options">{''.join(option_cards)}</div>
          <div class="button-row">
            <button type="button" class="alt" id="backToStep2">Back</button>
            <button type="submit" id="generateFinalResponseBtn" {'disabled' if not selected_venue_is_selectable else ''}>Generate Final Response</button>
          </div>
        </form>
      </div>
    </div>

    <div class="panel {'active' if current_step == 4 else ''}" id="step4">
      <div class="card">
        {f'<div class="success">Saved output to: {safe_output}</div>' if safe_output else ''}
        <h2>Final Event Plan</h2>
        <pre class="output">{safe_result}</pre>
        <div class="button-row">
          <a class="btn-link alt" href="/">Plan Another Event</a>
        </div>
      </div>
    </div>
  </div>

  <div id="loadingBackdrop" class="loading-backdrop" aria-live="polite" aria-hidden="true">
    <div class="loading-modal" role="status">
      <div class="spinner"></div>
      <p class="loading-title">Please wait, we are finding a perfect location for you.</p>
    </div>
  </div>

<script>
  const loadingBackdrop = document.getElementById('loadingBackdrop');
  const pageContent = document.getElementById('pageContent');

  // Clear dimming immediately when page loads
  if (pageContent) {{
    pageContent.classList.remove('dimmed');
  }}
  if (loadingBackdrop) {{
    loadingBackdrop.classList.remove('show');
    loadingBackdrop.setAttribute('aria-hidden', 'true');
  }}

  document.querySelectorAll('form[data-show-loader="true"]').forEach((formEl) => {{
    if (loadingBackdrop && pageContent) {{
      formEl.addEventListener('submit', () => {{
        loadingBackdrop.classList.add('show');
        loadingBackdrop.setAttribute('aria-hidden', 'false');
        pageContent.classList.add('dimmed');
      }});
    }}
  }});

  document.querySelectorAll('.tab-btn').forEach((btn) => {{
    btn.addEventListener('click', () => {{
      document.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach((p) => p.classList.remove('active'));
      btn.classList.add('active');
      const tabId = btn.getAttribute('data-tab');
      const panel = document.getElementById('tab-' + tabId);
      if (panel) panel.classList.add('active');
    }});
  }});

  const step1 = document.getElementById('step1');
  const step2 = document.getElementById('step2');
  const step3 = document.getElementById('step3');
  const backToStep1 = document.getElementById('backToStep1');
  const toStep3 = document.getElementById('toStep3');
  const backToStep2 = document.getElementById('backToStep2');

  const stepperItems = [
    document.getElementById('stepper1'),
    document.getElementById('stepper2'),
    document.getElementById('stepper3'),
    document.getElementById('stepper4'),
  ];

  const setActiveStep = (stepNumber) => {{
    stepperItems.forEach((item, index) => {{
      if (!item) return;
      if (index === stepNumber - 1) {{
        item.classList.add('active');
      }} else {{
        item.classList.remove('active');
      }}
    }});
  }};

  if (backToStep1 && step1 && step2) {{
    backToStep1.addEventListener('click', () => {{
      step2.classList.remove('active');
      step1.classList.add('active');
      setActiveStep(1);
    }});
  }}

  if (toStep3 && step2 && step3) {{
    toStep3.addEventListener('click', () => {{
      step2.classList.remove('active');
      step3.classList.add('active');
      setActiveStep(3);
    }});
  }}
  if (backToStep2 && step2 && step3) {{
    backToStep2.addEventListener('click', () => {{
      step3.classList.remove('active');
      step2.classList.add('active');
      setActiveStep(2);
    }});
  }}

  document.querySelectorAll('input').forEach((input) => {{
    input.addEventListener('input', () => {{
      input.classList.remove('input-error');
      const maybeError = input.nextElementSibling;
      if (maybeError && maybeError.classList.contains('field-error')) {{
        maybeError.remove();
      }}
    }});
  }});

  document.querySelectorAll('.venue-option input[type="radio"]').forEach((radio) => {{
    radio.addEventListener('change', () => {{
      document.querySelectorAll('.venue-option').forEach((card) => card.classList.remove('selected'));
      const parent = radio.closest('.venue-option');
      if (parent) {{
        parent.classList.add('selected');
        const selectedVenueAddress = document.getElementById('selectedVenueAddress');
        const selectedVenueEmail = document.getElementById('selectedVenueEmail');
        const selectedVenuePhone = document.getElementById('selectedVenuePhone');
        const selectedVenueWebsite = document.getElementById('selectedVenueWebsite');
        const selectedVenueGoogleLink = document.getElementById('selectedVenueGoogleLink');
        const selectedVenueSource = document.getElementById('selectedVenueSource');
        if (selectedVenueAddress) selectedVenueAddress.value = parent.getAttribute('data-address') || '';
        if (selectedVenueEmail) selectedVenueEmail.value = parent.getAttribute('data-email') || '';
        if (selectedVenuePhone) selectedVenuePhone.value = parent.getAttribute('data-phone') || '';
        if (selectedVenueWebsite) selectedVenueWebsite.value = parent.getAttribute('data-website') || '';
        if (selectedVenueGoogleLink) selectedVenueGoogleLink.value = parent.getAttribute('data-google-link') || '';
        if (selectedVenueSource) selectedVenueSource.value = parent.getAttribute('data-source') || '';
      }}
      const generateFinalResponseBtn = document.getElementById('generateFinalResponseBtn');
      const venueCapacityBanner = document.getElementById('venueCapacityBanner');
      if (generateFinalResponseBtn) generateFinalResponseBtn.disabled = radio.disabled;
      if (venueCapacityBanner) venueCapacityBanner.style.display = radio.disabled ? 'block' : 'none';
    }});
  }});

  const hydrateVenueContacts = async () => {{
    const cityInput = document.querySelector('input[name="event_city"]');
    const city = cityInput ? cityInput.value.trim() : '';
    const cards = Array.from(document.querySelectorAll('.venue-option'));
    await Promise.allSettled(cards.map(async (card) => {{
      const phoneEl = card.querySelector('.venue-contact-phone');
      const emailEl = card.querySelector('.venue-contact-email');
      const currentPhone = phoneEl ? phoneEl.textContent.trim() : '';
      const currentEmail = emailEl ? emailEl.textContent.trim() : '';
      if (currentPhone && currentPhone !== 'Not available' && currentEmail && currentEmail !== 'Not available') {{
        return;
      }}

      const params = new URLSearchParams({{
        city,
        venue_name: card.getAttribute('data-name') || '',
        address: card.getAttribute('data-address') || '',
        website: card.getAttribute('data-website') || '',
        google_link: card.getAttribute('data-google-link') || '',
      }});

      try {{
        const response = await fetch('/contacts?' + params.toString(), {{
          headers: {{ 'Accept': 'application/json' }},
        }});
        if (!response.ok) return;
        const data = await response.json();
        if (phoneEl && data.contact_phone && data.contact_phone !== 'Not available') {{
          phoneEl.textContent = data.contact_phone;
          card.setAttribute('data-phone', data.contact_phone);
        }}
        if (emailEl && data.contact_email && data.contact_email !== 'Not available') {{
          emailEl.textContent = data.contact_email;
          card.setAttribute('data-email', data.contact_email);
        }}
        if (data.website && data.website !== 'Not available') {{
          card.setAttribute('data-website', data.website);
        }}
      }} catch (error) {{
        // Leave the raw recommendation in place if contact hydration fails.
      }}
    }}));
  }};

  if (document.querySelectorAll('.venue-option').length > 0) {{
    hydrateVenueContacts();
  }}

  // Enter key navigates to next field instead of submitting, except on the last field
  document.querySelectorAll('#locationVerifyForm input, #eventForm input').forEach((input) => {{
    input.addEventListener('keydown', (e) => {{
      if (e.key !== 'Enter') return;
      const form = input.form;
      if (!form) return;
      const inputs = Array.from(form.querySelectorAll('input:not([type="hidden"]):not([readonly]):not([disabled])'));
      const idx = inputs.indexOf(input);
      if (idx !== -1 && idx < inputs.length - 1) {{
        e.preventDefault();
        inputs[idx + 1].focus();
      }}
      // If it's the last input, allow default behaviour (form submit)
    }});
  }});

  const venueSelectForm = document.getElementById('venueSelectForm');
  if (venueSelectForm) {{
    const generateFinalResponseBtn = document.getElementById('generateFinalResponseBtn');
    const venueCapacityBanner = document.getElementById('venueCapacityBanner');
    const checked = venueSelectForm.querySelector('input[name="selected_venue_type"]:checked');
    const checkedParent = checked ? checked.closest('.venue-option') : null;
    if (generateFinalResponseBtn) {{
      generateFinalResponseBtn.disabled = !checked || checked.disabled;
    }}
    if (venueCapacityBanner && checkedParent) {{
      venueCapacityBanner.style.display = checked.disabled ? 'block' : 'none';
    }}

    venueSelectForm.addEventListener('submit', (event) => {{
      const checked = venueSelectForm.querySelector('input[name="selected_venue_type"]:checked');
      const parent = checked ? checked.closest('.venue-option') : null;
      if (!checked || checked.disabled) {{
        if (generateFinalResponseBtn) generateFinalResponseBtn.disabled = true;
        if (venueCapacityBanner) venueCapacityBanner.style.display = 'block';
        event.preventDefault();
        return;
      }}
      const selectedVenueAddress = document.getElementById('selectedVenueAddress');
      const selectedVenueEmail = document.getElementById('selectedVenueEmail');
      const selectedVenuePhone = document.getElementById('selectedVenuePhone');
      const selectedVenueWebsite = document.getElementById('selectedVenueWebsite');
      const selectedVenueSource = document.getElementById('selectedVenueSource');
      if (parent) {{
        if (selectedVenueAddress) selectedVenueAddress.value = parent.getAttribute('data-address') || '';
        if (selectedVenueEmail) selectedVenueEmail.value = parent.getAttribute('data-email') || '';
        if (selectedVenuePhone) selectedVenuePhone.value = parent.getAttribute('data-phone') || '';
        if (selectedVenueWebsite) selectedVenueWebsite.value = parent.getAttribute('data-website') || '';
        if (selectedVenueSource) selectedVenueSource.value = parent.getAttribute('data-source') || '';
      }}
    }});
  }}
</script>
</body>
</html>
"""


class EventPlanningHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/contacts":
            params = parse_qs(parsed_path.query)
            city = params.get("city", [""])[0].strip()
            venue_name = params.get("venue_name", [""])[0].strip()
            address = params.get("address", [""])[0].strip()
            website = params.get("website", [""])[0].strip()
            google_link = params.get("google_link", [""])[0].strip()
            resolved_contact = resolve_contact_details_for_selected_venue(
              city=city,
              venue_name=venue_name,
              address=address,
              website=website,
              google_link=google_link,
            )
            payload = json.dumps(
                {
                "contact_phone": resolved_contact.get("contact_phone", "Not available"),
                "contact_email": resolved_contact.get("contact_email", "Not available"),
                "website": resolved_contact.get("website", website or "Not available"),
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        content = render_page()
        self._write_html(content)

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length).decode("utf-8", errors="ignore")
        # Prefer the last value for duplicate keys so edited visible inputs
        # override stale hidden fields sent earlier in the form markup.
        form = {
          k: v[-1]
          for k, v in parse_qs(raw_body, keep_blank_values=True).items()
        }
        action = form.get("action", "verify_location").strip().lower()
        location_verified = form.get("location_verified", "").strip().lower() == "true"

        def validate_location_inputs(city_value: str, venue_value: str) -> dict[str, str]:
            errors: dict[str, str] = {}
            if not city_value:
                errors["event_city"] = "Event City cannot be empty."
            else:
                city_error = validate_event_city(city_value)
                if city_error:
                    errors["event_city"] = city_error

            if not venue_value:
                errors["venue_type"] = "Preferred Venue Type cannot be empty."
            else:
                venue_type_error = validate_venue_type_input(venue_value)
                if venue_type_error:
                    errors["venue_type"] = venue_type_error

            if not errors:
                is_valid, code, message = validate_city_and_venue_with_llm(
                    city_value,
                    venue_value,
                city_prevalidated=False,
                )
                if not is_valid:
                  message_lower = message.lower()
                  if (
                    code == "city_not_found"
                    and "ambiguous" in message_lower
                    and "multiple countr" in message_lower
                  ):
                    # Let verify_location continue to the country-selection branch.
                    return errors
                    if code == "city_not_found":
                        errors["event_city"] = (
                            f"City does not exist or could not be validated: {message}"
                        )
                    elif code == "venue_not_found":
                        errors["venue_type"] = (
                            f"Venue type does not exist in the desired city: {message}"
                        )
                    else:
                        if "city" in message_lower and "venue" not in message_lower:
                            errors["event_city"] = message
                        elif "venue" in message_lower and "city" not in message_lower:
                            errors["venue_type"] = message
                        else:
                            errors["event_city"] = message

            return errors

        if action == "back_to_location":
            form["location_verified"] = "false"
            form["verified_event_city"] = ""
            form["verified_venue_type"] = ""
            form["country_selection_required"] = "false"
            form["country_options_json"] = ""
            form["selected_country_code"] = ""
            form["resolved_country"] = ""
            form["resolved_country_code"] = ""
            content = render_page(form_data=form)
            self._write_html(content)
            return

        if action == "verify_location":
            city_value = form.get("event_city", "").strip()
            venue_value = form.get("venue_type", "").strip()
            field_errors = validate_location_inputs(city_value, venue_value)

            if field_errors:
                content = render_page(
                    form_data=form,
                    field_errors=field_errors,
                )
                self._write_html(content)
                return

            country_options = resolve_city_country_options(city_value)
            if len(country_options) > 1:
                form["location_verified"] = "false"
                form["country_selection_required"] = "true"
                form["country_options_json"] = json.dumps(country_options)
                form["selected_country_code"] = ""
                form["resolved_country"] = ""
                form["resolved_country_code"] = ""
                form["verified_event_city"] = city_value
                form["verified_venue_type"] = venue_value
                content = render_page(
                    form_data=form,
                    location_success=(
                        "City and venue type validated. Multiple country matches were found for this city. "
                        "Please pick one country to continue."
                    ),
                )
                self._write_html(content)
                return

            form["location_verified"] = "true"
            form["country_selection_required"] = "false"
            form["verified_event_city"] = city_value
            form["verified_venue_type"] = venue_value
            form["country_options_json"] = ""

            if country_options:
                chosen_country = country_options[0]
                form["selected_country_code"] = chosen_country.get("country_code", "")
                form["resolved_country"] = chosen_country.get("country", "")
                form["resolved_country_code"] = chosen_country.get("country_code", "")
                location_message = (
                    f"City exists and venue type is available in that city. "
                    f"Resolved country: {chosen_country.get('country', '')} ({chosen_country.get('country_code', '')}). "
                    "Please continue with the remaining fields."
                )
            else:
                form["selected_country_code"] = ""
                form["resolved_country"] = ""
                form["resolved_country_code"] = ""
                location_message = (
                    "City exists and venue type is available in that city. "
                    "Please continue with the remaining fields."
                )

            content = render_page(
                form_data=form,
                location_success=location_message,
            )
            self._write_html(content)
            return

        if action == "confirm_country":
            options = parse_country_options_json(form.get("country_options_json", ""))
            selected_country_code = form.get("selected_country_code", "").strip().upper()
            selected_option = next(
                (row for row in options if row.get("country_code", "").upper() == selected_country_code),
                None,
            )

            if not selected_option:
                content = render_page(
                    form_data=form,
                    error="Please select a country to continue.",
                )
                self._write_html(content)
                return

            form["location_verified"] = "true"
            form["country_selection_required"] = "false"
            form["verified_event_city"] = form.get("event_city", "").strip()
            form["verified_venue_type"] = form.get("venue_type", "").strip()
            form["selected_country_code"] = selected_option.get("country_code", "")
            form["resolved_country"] = selected_option.get("country", "")
            form["resolved_country_code"] = selected_option.get("country_code", "")
            form["country_options_json"] = ""

            content = render_page(
                form_data=form,
                location_success=(
                    f"Location confirmed: {form.get('event_city', '').strip()}, "
                    f"{selected_option.get('country', '')} ({selected_option.get('country_code', '')}). "
                    "Please continue with the remaining fields."
                ),
            )
            self._write_html(content)
            return

        city_value = form.get("event_city", "").strip()
        venue_value = form.get("venue_type", "").strip()
        verified_city_value = form.get("verified_event_city", "").strip()
        verified_venue_value = form.get("verified_venue_type", "").strip()

        city_or_venue_changed = (
            bool(verified_city_value and city_value and verified_city_value.casefold() != city_value.casefold())
            or bool(verified_venue_value and venue_value and verified_venue_value.casefold() != venue_value.casefold())
        )

        if location_verified and city_or_venue_changed:
            location_verified = False
            form["location_verified"] = "false"
            form["country_selection_required"] = "false"
            form["country_options_json"] = ""
            form["selected_country_code"] = ""
            form["resolved_country"] = ""
            form["resolved_country_code"] = ""

        if action in {"recommend", "final"} and form.get("country_selection_required", "").strip().lower() == "true":
            content = render_page(
                form_data=form,
                error="Please select the country for this city before continuing.",
            )
            self._write_html(content)
            return

        if action in {"recommend", "final"}:
            auto_location_errors = validate_location_inputs(city_value, venue_value)
            if auto_location_errors:
                form["location_verified"] = "false"
                form["verified_event_city"] = ""
                form["verified_venue_type"] = ""
                form["country_selection_required"] = "false"
                form["country_options_json"] = ""
                form["selected_country_code"] = ""
                form["resolved_country"] = ""
                form["resolved_country_code"] = ""
                content = render_page(
                    form_data=form,
                    field_errors=auto_location_errors,
                    error="Location details changed or expired. Please re-validate city and venue type.",
                )
                self._write_html(content)
                return

            location_verified = True
            form["location_verified"] = "true"
            form["verified_event_city"] = city_value
            form["verified_venue_type"] = venue_value

        if not location_verified:
            content = render_page(
                form_data=form,
                error="Please validate city and venue type first.",
            )
            self._write_html(content)
            return

        required_fields = [
            "event_topic",
            "event_city",
            "expected_participants",
            "tentative_date",
            "budget",
            "venue_type",
        ]

        field_errors: dict[str, str] = {}
        field_warnings: dict[str, str] = {}
        for req_field in required_fields:
            if not form.get(req_field, "").strip():
                field_errors[req_field] = f"{req_field.replace('_', ' ').title()} cannot be empty."

        participants_error = validate_positive_integer(form.get("expected_participants", ""), "expected participants")
        if participants_error:
            field_errors["expected_participants"] = participants_error

        try:
          expected_participants_int = int(form.get("expected_participants", "0").strip())
        except ValueError:
          expected_participants_int = 0

        city_error = validate_event_city(form.get("event_city", ""))
        if city_error:
            field_errors["event_city"] = city_error

        venue_type_error = validate_venue_type_input(form.get("venue_type", ""))
        if venue_type_error:
            field_errors["venue_type"] = venue_type_error

        budget_error = validate_positive_integer(form.get("budget", ""), "budget")
        if budget_error:
            field_errors["budget"] = budget_error

        date_value = form.get("tentative_date", "").strip()
        if date_value:
            date_error = validate_future_date(date_value)
            if date_error:
                field_errors["tentative_date"] = date_error
            else:
                date_warning = get_date_bandwidth_warning(date_value)
                if date_warning:
                    field_warnings["tentative_date"] = date_warning

        optional_preference_fields = {
            "food_type": "food type",
            "dietary_requirements": "dietary requirements",
            "decor_style": "decor style",
            "av_requirements": "AV requirements",
        }
        for preference_field, label in optional_preference_fields.items():
            pref_error = validate_preference_text(form.get(preference_field, ""), label)
            if pref_error:
                field_errors[preference_field] = pref_error

        # Only run semantic LLM guardrails before recommendation generation.
        # For final submission, we generate a deterministic summary from selected venue + user inputs.
        if action == "recommend":
          guardrail_errors = review_form_guardrails(form)
          if location_verified:
            guardrail_errors.pop("event_city", None)
            guardrail_errors.pop("venue_type", None)
          for field_name, message in guardrail_errors.items():
            if field_name not in field_errors:
              field_errors[field_name] = message

        if field_errors:
            content = render_page(
                form_data=form,
                field_errors=field_errors,
                field_warnings=field_warnings,
            )
            self._write_html(content)
            return

        if action == "recommend":
            venue_recommendations = get_venue_recommendations(form)
            if not venue_recommendations:
                content = render_page(
                    form_data=form,
                    field_warnings=field_warnings,
                    error=(
                        "No venue matches were found for this input. "
                        "Please use a specific city (not a state/region), try a different venue type, or retry in a moment."
                    ),
                )
                self._write_html(content)
                return

            try:
                operations_insights = build_operations_insights(
                    form,
                    venue_recommendations,
                    form.get("venue_type", ""),
                )
            except Exception:
                operations_insights = {
                    "availability": [
                        {
                            "venue": str(v.get("name", "Venue")),
                            "status": "Available",
                            "source_note": "Auto fallback",
                        }
                        for v in venue_recommendations[:5]
                    ],
                    "budget_breakdown": [],
                    "vendors": {},
                    "timeline": [],
                    "weather": "Not available",
                    "accommodation": [],
                    "transport": [],
                    "accessibility": [],
                    "comparison": [],
                    "email_confirmation": build_email_confirmation_draft(
                        form,
                        venue_recommendations,
                        form.get("venue_type", ""),
                    ),
                }

            content = render_page(
                form_data=form,
                field_warnings=field_warnings,
                venue_recommendations=venue_recommendations,
                operations_insights=operations_insights,
            )
            self._write_html(content)
            return

        selected_venue_type = form.get("selected_venue_type", "").strip()
        if not selected_venue_type:
          venue_recommendations = get_venue_recommendations(form)
          content = render_page(
            form_data=form,
            field_warnings=field_warnings,
            venue_recommendations=venue_recommendations,
            selection_error="Please select one venue type from the recommended list.",
          )
          self._write_html(content)
          return

        selected_venue_capacity = estimate_venue_capacity(selected_venue_type)
        if expected_participants_int > 0 and expected_participants_int > selected_venue_capacity:
          venue_recommendations = get_venue_recommendations(form)
          content = render_page(
            form_data=form,
            field_warnings=field_warnings,
            venue_recommendations=venue_recommendations,
            selection_error=(
              "Please choose some other venue. "
              f"'{selected_venue_type}' supports only about {selected_venue_capacity} guests."
            ),
          )
          self._write_html(content)
          return

        form["venue_type"] = selected_venue_type

        # Use the contact details already resolved when the user browsed the cards.
        # Only fall back to live resolution if the hidden fields are genuinely empty.
        cached_phone = form.get("selected_venue_phone", "").strip()
        cached_email = form.get("selected_venue_email", "").strip()
        cached_address = form.get("selected_venue_address", "").strip()
        cached_website = form.get("selected_venue_website", "").strip()

        needs_resolve = (
            (not cached_phone or cached_phone == "Not available")
            and (not cached_email or cached_email == "Not available")
        )
        if needs_resolve:
            resolved_contact = resolve_contact_details_for_selected_venue(
                city=form.get("event_city", ""),
                venue_name=selected_venue_type,
                address=cached_address,
                website=cached_website,
                google_link=form.get("selected_venue_google_link", ""),
            )
            cached_address = resolved_contact.get("address", cached_address) or cached_address
            cached_phone = resolved_contact.get("contact_phone", "Not available")
            cached_email = resolved_contact.get("contact_email", "Not available")
            cached_website = resolved_contact.get("website", cached_website) or cached_website

        selected_venue = {
            "name": selected_venue_type,
            "address": cached_address or "Not available",
            "capacity": form.get("expected_participants", "Not available"),
            "booking_status": "Finalized",
            "contact_phone": cached_phone or "Not available",
            "contact_email": cached_email or "Not available",
            "website": cached_website or "Not available",
            "source": form.get("selected_venue_source", "places") or "places",
        }

        safety_decision = evaluate_venue_profile(selected_venue, form.get("event_city", ""))
        if not safety_decision.allowed:
            venue_recommendations = get_venue_recommendations(form)
            content = render_page(
                form_data=form,
                field_warnings=field_warnings,
                venue_recommendations=venue_recommendations,
                selection_error=(
                    "Selected venue failed safety validation. "
                    f"Reason: {safety_decision.reason}. Please choose another venue."
                ),
            )
            self._write_html(content)
            return

        selected_venue = safety_decision.profile

        try:
            venue_path = Path("venue_details.json")
            with open(venue_path, "w", encoding="utf-8") as file:
                json.dump(selected_venue, file, indent=2)

            final_result = build_selected_venue_summary(form, selected_venue)
            output_dir = Path("output")
            output_dir.mkdir(exist_ok=True)
            output_file = str(output_dir / f"event_{slugify(form.get('event_topic', 'event'))}.md")
            with open(output_file, "w", encoding="utf-8") as file:
                file.write(final_result)

            content = render_page(
                result=final_result,
                output_file=output_file,
                form_data=form,
                field_warnings=field_warnings,
            )
            self._write_html(content)
        except Exception as exc:
            venue_recommendations = get_venue_recommendations(form)
            content = render_page(
                form_data=form,
                field_warnings=field_warnings,
                venue_recommendations=venue_recommendations,
                selection_error=f"Failed to generate event plan: {exc}",
            )
            self._write_html(content)

    def log_message(self, format: str, *args) -> None:
        return

    def _write_html(self, content: str) -> None:
        try:
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            # Client disconnected before response could be sent; this is normal
            pass


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), EventPlanningHandler)
    print(f"Event Planning UI running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
