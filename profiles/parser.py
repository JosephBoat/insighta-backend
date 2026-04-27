"""
Natural language query parser.
Converts plain English queries into filter dictionaries.

Supported keywords and their mappings:
- Gender: "male", "males", "men", "man", "female", "females", "women", "woman", "girl", "girls", "boy", "boys"
- Age groups: "child", "children", "teenager", "teenagers", "teen", "teens", "adult", "adults", "senior", "seniors", "elderly"
- Young: maps to min_age=16, max_age=24 (for parsing only, not a stored age group)
- Age comparisons: "above X", "over X", "below X", "under X", "older than X", "younger than X"
- Country: "from <country name>" → mapped to country_id
"""

# Map country names to ISO codes
COUNTRY_NAME_TO_ID = {
    "nigeria": "NG",
    "ghana": "GH",
    "kenya": "KE",
    "tanzania": "TZ",
    "uganda": "UG",
    "south africa": "ZA",
    "ethiopia": "ET",
    "egypt": "EG",
    "cameroon": "CM",
    "senegal": "SN",
    "mali": "ML",
    "angola": "AO",
    "mozambique": "MZ",
    "zambia": "ZM",
    "zimbabwe": "ZW",
    "rwanda": "RW",
    "somalia": "SO",
    "sudan": "SD",
    "chad": "TD",
    "niger": "NE",
    "burkina faso": "BF",
    "benin": "BJ",
    "togo": "TG",
    "guinea": "GN",
    "sierra leone": "SL",
    "liberia": "LR",
    "gambia": "GM",
    "mauritania": "MR",
    "morocco": "MA",
    "algeria": "DZ",
    "tunisia": "TN",
    "libya": "LY",
    "malawi": "MW",
    "namibia": "NA",
    "botswana": "BW",
    "mauritius": "MU",
    "united states": "US",
    "usa": "US",
    "america": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "britain": "GB",
    "england": "GB",
    "france": "FR",
    "germany": "DE",
    "italy": "IT",
    "spain": "ES",
    "portugal": "PT",
    "netherlands": "NL",
    "belgium": "BE",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "poland": "PL",
    "russia": "RU",
    "ukraine": "UA",
    "turkey": "TR",
    "greece": "GR",
    "india": "IN",
    "china": "CN",
    "japan": "JP",
    "south korea": "KR",
    "indonesia": "ID",
    "philippines": "PH",
    "vietnam": "VN",
    "thailand": "TH",
    "malaysia": "MY",
    "singapore": "SG",
    "pakistan": "PK",
    "bangladesh": "BD",
    "brazil": "BR",
    "argentina": "AR",
    "colombia": "CO",
    "chile": "CL",
    "peru": "PE",
    "mexico": "MX",
    "canada": "CA",
    "australia": "AU",
    "new zealand": "NZ",
    "saudi arabia": "SA",
    "uae": "AE",
    "united arab emirates": "AE",
    "israel": "IL",
    "iran": "IR",
    "iraq": "IQ",
    "democratic republic of the congo": "CD",
    "drc": "CD",
    "congo": "CG",
    "ivory coast": "CI",
    "côte d'ivoire": "CI",
    "cote divoire": "CI",
}

MALE_WORDS = {"male", "males", "men", "man", "boy", "boys"}
FEMALE_WORDS = {"female", "females", "women", "woman", "girl", "girls"}
AGE_GROUP_WORDS = {
    "child",
    "children",
    "teenager",
    "teenagers",
    "teen",
    "teens",
    "adult",
    "adults",
    "senior",
    "seniors",
    "elderly",
}
AGE_GROUP_MAP = {
    "child": "child",
    "children": "child",
    "teenager": "teenager",
    "teenagers": "teenager",
    "teen": "teenager",
    "teens": "teenager",
    "adult": "adult",
    "adults": "adult",
    "senior": "senior",
    "seniors": "senior",
    "elderly": "senior",
}


def parse_query(q: str) -> tuple:
    """
    Parse a plain English query into a filters dictionary.
    Returns (filters_dict, error_message) — one will always be None.

    Examples:
        "young males from nigeria"   → {'gender': 'male', 'min_age': 16, 'max_age': 24, 'country_id': 'NG'}
        "females above 30"           → {'gender': 'female', 'min_age': 30}
        "adult males from kenya"     → {'gender': 'male', 'age_group': 'adult', 'country_id': 'KE'}
    """
    if not q or not q.strip():
        return None, "Unable to interpret query"

    q_lower = q.lower().strip()
    tokens = q_lower.split()
    filters = {}
    interpreted = False

    # --- Gender detection ---
    for token in tokens:
        if token in MALE_WORDS:
            filters["gender"] = "male"
            interpreted = True
            break
        elif token in FEMALE_WORDS:
            filters["gender"] = "female"
            interpreted = True
            break

    # --- "young" keyword → ages 16-24 ---
    if "young" in tokens:
        filters["min_age"] = 16
        filters["max_age"] = 24
        interpreted = True

    # --- Age group detection ---
    for token in tokens:
        if token in AGE_GROUP_WORDS:
            filters["age_group"] = AGE_GROUP_MAP[token]
            interpreted = True
            break

    # --- Age comparison: "above X", "over X", "older than X" ---
    age_above_triggers = {"above", "over", "older"}
    age_below_triggers = {"below", "under", "younger"}

    for i, token in enumerate(tokens):
        if token in age_above_triggers and i + 1 < len(tokens):
            next_token = tokens[i + 1]
            # handle "older than 30" — skip "than"
            if next_token == "than" and i + 2 < len(tokens):
                next_token = tokens[i + 2]
            if next_token.isdigit():
                filters["min_age"] = int(next_token)
                interpreted = True

        if token in age_below_triggers and i + 1 < len(tokens):
            next_token = tokens[i + 1]
            if next_token == "than" and i + 2 < len(tokens):
                next_token = tokens[i + 2]
            if next_token.isdigit():
                filters["max_age"] = int(next_token)
                interpreted = True

    # --- Country detection: look for "from <country>" ---
    if "from" in tokens:
        from_index = tokens.index("from")
        # Everything after "from" could be a country name (handles multi-word countries)
        after_from = " ".join(tokens[from_index + 1 :])

        # Try longest match first (e.g. "south africa" before "africa")
        matched_country = None
        for country_name in sorted(COUNTRY_NAME_TO_ID.keys(), key=len, reverse=True):
            if after_from.startswith(country_name):
                matched_country = COUNTRY_NAME_TO_ID[country_name]
                break

        if matched_country:
            filters["country_id"] = matched_country
            interpreted = True

    if not interpreted:
        return None, "Unable to interpret query"

    return filters, None
