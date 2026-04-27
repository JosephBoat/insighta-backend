import httpx
import asyncio


async def _fetch_all_apis(name: str) -> tuple:
    """Call all three external APIs concurrently"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        gender_res, age_res, nation_res = await asyncio.gather(
            client.get(f"https://api.genderize.io?name={name}"),
            client.get(f"https://api.agify.io?name={name}"),
            client.get(f"https://api.nationalize.io?name={name}"),
        )
    return gender_res.json(), age_res.json(), nation_res.json()


def fetch_profile_data(name: str) -> tuple:
    """
    Fetch and validate data from all three external APIs.
    Returns (data_dict, error_message) — one will always be None.

    This is the single place where all external API logic lives.
    Views never talk to external APIs directly.
    """
    try:
        gender_data, age_data, nation_data = asyncio.run(_fetch_all_apis(name))
    except Exception:
        return None, "Failed to reach external APIs"

    # Validate Genderize
    if not gender_data.get("gender") or gender_data.get("count", 0) == 0:
        return None, "Genderize returned an invalid response"

    # Validate Agify
    if age_data.get("age") is None:
        return None, "Agify returned an invalid response"

    # Validate Nationalize
    countries = nation_data.get("country", [])
    if not countries:
        return None, "Nationalize returned an invalid response"

    # Pick country with highest probability
    top_country = max(countries, key=lambda c: c["probability"])

    return {
        "gender": gender_data["gender"],
        "gender_probability": gender_data["probability"],
        "sample_size": gender_data["count"],
        "age": age_data["age"],
        "age_group": _get_age_group(age_data["age"]),
        "country_id": top_country["country_id"],
        "country_name": _get_country_name(top_country["country_id"]),
        "country_probability": top_country["probability"],
    }, None


def _get_age_group(age: int) -> str:
    """Classify age into a group based on task rules"""
    if age <= 12:
        return "child"
    elif age <= 19:
        return "teenager"
    elif age <= 59:
        return "adult"
    else:
        return "senior"


def _get_country_name(country_id: str) -> str:
    """
    Map ISO country code to full country name.
    Covers the most common codes. Falls back to the code itself if not found.
    """
    country_map = {
        "NG": "Nigeria",
        "GH": "Ghana",
        "KE": "Kenya",
        "TZ": "Tanzania",
        "UG": "Uganda",
        "ZA": "South Africa",
        "ET": "Ethiopia",
        "EG": "Egypt",
        "CM": "Cameroon",
        "CI": "Côte d'Ivoire",
        "SN": "Senegal",
        "ML": "Mali",
        "BF": "Burkina Faso",
        "NE": "Niger",
        "TD": "Chad",
        "SD": "Sudan",
        "AO": "Angola",
        "MZ": "Mozambique",
        "MG": "Madagascar",
        "ZM": "Zambia",
        "ZW": "Zimbabwe",
        "RW": "Rwanda",
        "BI": "Burundi",
        "SO": "Somalia",
        "DJ": "Djibouti",
        "ER": "Eritrea",
        "SS": "South Sudan",
        "CF": "Central African Republic",
        "CG": "Republic of the Congo",
        "CD": "Democratic Republic of the Congo",
        "GA": "Gabon",
        "GQ": "Equatorial Guinea",
        "ST": "São Tomé and Príncipe",
        "BJ": "Benin",
        "TG": "Togo",
        "GN": "Guinea",
        "GW": "Guinea-Bissau",
        "SL": "Sierra Leone",
        "LR": "Liberia",
        "GM": "Gambia",
        "CV": "Cape Verde",
        "MR": "Mauritania",
        "MA": "Morocco",
        "DZ": "Algeria",
        "TN": "Tunisia",
        "LY": "Libya",
        "MW": "Malawi",
        "NA": "Namibia",
        "BW": "Botswana",
        "LS": "Lesotho",
        "SZ": "Eswatini",
        "MU": "Mauritius",
        "SC": "Seychelles",
        "KM": "Comoros",
        "US": "United States",
        "GB": "United Kingdom",
        "FR": "France",
        "DE": "Germany",
        "IT": "Italy",
        "ES": "Spain",
        "PT": "Portugal",
        "NL": "Netherlands",
        "BE": "Belgium",
        "CH": "Switzerland",
        "AT": "Austria",
        "SE": "Sweden",
        "NO": "Norway",
        "DK": "Denmark",
        "FI": "Finland",
        "PL": "Poland",
        "CZ": "Czech Republic",
        "SK": "Slovakia",
        "HU": "Hungary",
        "RO": "Romania",
        "BG": "Bulgaria",
        "HR": "Croatia",
        "RS": "Serbia",
        "GR": "Greece",
        "TR": "Turkey",
        "RU": "Russia",
        "UA": "Ukraine",
        "IN": "India",
        "CN": "China",
        "JP": "Japan",
        "KR": "South Korea",
        "ID": "Indonesia",
        "PH": "Philippines",
        "VN": "Vietnam",
        "TH": "Thailand",
        "MY": "Malaysia",
        "SG": "Singapore",
        "PK": "Pakistan",
        "BD": "Bangladesh",
        "LK": "Sri Lanka",
        "NP": "Nepal",
        "MM": "Myanmar",
        "KH": "Cambodia",
        "BR": "Brazil",
        "AR": "Argentina",
        "CO": "Colombia",
        "CL": "Chile",
        "PE": "Peru",
        "VE": "Venezuela",
        "EC": "Ecuador",
        "BO": "Bolivia",
        "PY": "Paraguay",
        "UY": "Uruguay",
        "MX": "Mexico",
        "CA": "Canada",
        "AU": "Australia",
        "NZ": "New Zealand",
        "IL": "Israel",
        "SA": "Saudi Arabia",
        "AE": "United Arab Emirates",
        "QA": "Qatar",
        "KW": "Kuwait",
        "IQ": "Iraq",
        "IR": "Iran",
        "JO": "Jordan",
        "LB": "Lebanon",
        "SY": "Syria",
        "YE": "Yemen",
        "CY": "Cyprus",
        "MT": "Malta",
        "IE": "Ireland",
        "IS": "Iceland",
        "AL": "Albania",
        "MK": "North Macedonia",
        "BA": "Bosnia and Herzegovina",
        "ME": "Montenegro",
        "XK": "Kosovo",
        "LV": "Latvia",
        "LT": "Lithuania",
        "EE": "Estonia",
        "BY": "Belarus",
        "MD": "Moldova",
        "GE": "Georgia",
        "AM": "Armenia",
        "AZ": "Azerbaijan",
        "KZ": "Kazakhstan",
        "UZ": "Uzbekistan",
        "TM": "Turkmenistan",
        "KG": "Kyrgyzstan",
        "TJ": "Tajikistan",
        "AF": "Afghanistan",
        "MN": "Mongolia",
        "KP": "North Korea",
        "TW": "Taiwan",
        "HK": "Hong Kong",
        "MO": "Macau",
        "FJ": "Fiji",
        "PG": "Papua New Guinea",
        "SB": "Solomon Islands",
        "VU": "Vanuatu",
        "WS": "Samoa",
        "TO": "Tonga",
        "CU": "Cuba",
        "DO": "Dominican Republic",
        "PR": "Puerto Rico",
        "JM": "Jamaica",
        "TT": "Trinidad and Tobago",
        "BB": "Barbados",
        "HT": "Haiti",
        "GT": "Guatemala",
        "HN": "Honduras",
        "SV": "El Salvador",
        "NI": "Nicaragua",
        "CR": "Costa Rica",
        "PA": "Panama",
    }
    return country_map.get(country_id, country_id)
