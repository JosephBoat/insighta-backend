# Stage 2 — Intelligence Query Engine

A demographic intelligence API built for Insighta Labs. Stores 2026+ profiles and exposes advanced filtering, sorting, pagination, and natural language search.

## Live API

```
https://hng-stage1-profiles.fly.dev
```

## Tech Stack

- **Framework:** Django + Django REST Framework
- **Database:** PostgreSQL (Neon)
- **Deployment:** Fly.io

## Endpoints

### Get All Profiles
```
GET /api/profiles
```

Supports filtering, sorting, and pagination combined:

| Parameter | Type | Description |
|---|---|---|
| `gender` | string | `male` or `female` |
| `age_group` | string | `child`, `teenager`, `adult`, `senior` |
| `country_id` | string | ISO code e.g. `NG`, `KE` |
| `min_age` | integer | Minimum age (inclusive) |
| `max_age` | integer | Maximum age (inclusive) |
| `min_gender_probability` | float | e.g. `0.8` |
| `min_country_probability` | float | e.g. `0.5` |
| `sort_by` | string | `age`, `created_at`, `gender_probability` |
| `order` | string | `asc` or `desc` (default: `asc`) |
| `page` | integer | Page number (default: `1`) |
| `limit` | integer | Results per page (default: `10`, max: `50`) |

Example:
```
GET /api/profiles?gender=male&country_id=NG&min_age=25&sort_by=age&order=desc&page=1&limit=10
```

### Natural Language Search
```
GET /api/profiles/search?q=young males from nigeria
```

Pagination parameters (`page`, `limit`) also apply here.

### Get Single Profile
```
GET /api/profiles/{id}
```

### Create Profile
```
POST /api/profiles
Content-Type: application/json

{ "name": "john" }
```

### Delete Profile
```
DELETE /api/profiles/{id}
```
Returns 204 No Content.

---

## Natural Language Parsing

### Approach

The parser (`profiles/parser.py`) uses rule-based keyword matching — no AI or LLMs. It tokenizes the query into lowercase words and matches against known keyword sets.

### Supported Keywords

**Gender:**
| Keywords | Maps to |
|---|---|
| male, males, men, man, boy, boys | `gender=male` |
| female, females, women, woman, girl, girls | `gender=female` |

**Age Groups:**
| Keywords | Maps to |
|---|---|
| child, children | `age_group=child` |
| teenager, teenagers, teen, teens | `age_group=teenager` |
| adult, adults | `age_group=adult` |
| senior, seniors, elderly | `age_group=senior` |

**Special Age Keywords:**
| Keywords | Maps to |
|---|---|
| young | `min_age=16`, `max_age=24` |
| above X, over X, older than X | `min_age=X` |
| below X, under X, younger than X | `max_age=X` |

**Country (via "from" keyword):**
Detects country names after the word "from". Supports multi-word countries.
Examples: `from nigeria` → `NG`, `from south africa` → `ZA`, `from united kingdom` → `GB`

### Example Mappings

| Query | Filters Applied |
|---|---|
| `young males from nigeria` | `gender=male, min_age=16, max_age=24, country_id=NG` |
| `females above 30` | `gender=female, min_age=30` |
| `adult males from kenya` | `gender=male, age_group=adult, country_id=KE` |
| `senior women` | `gender=female, age_group=senior` |
| `teenagers from ghana` | `age_group=teenager, country_id=GH` |

### How the Logic Works

1. Query is lowercased and split into tokens
2. Each token is checked against keyword sets in order: gender → young → age group → age comparisons → country
3. Country detection looks for the word "from" then tries to match everything after it against a country name dictionary (longest match first, to handle multi-word names like "south africa")
4. If no keywords are matched at all, returns `"Unable to interpret query"`

---

## Limitations

- **"young" is not a stored age_group** — it maps to `min_age=16, max_age=24` for parsing only
- **Only one gender per query** — "male and female" will only capture "male" (first match wins)
- **Country must follow "from"** — `"nigeria males"` won't detect Nigeria; it must be `"males from nigeria"`
- **No synonym support beyond defined keywords** — "guys", "lads", "gents" are not recognized
- **No age range expressions** — "between 20 and 30" is not supported
- **No negation** — "not from nigeria" is not supported
- **Country name must be in the known dictionary** — obscure country names may not be recognized

---

## Error Responses

All errors follow this structure:
```json
{ "status": "error", "message": "<error message>" }
```

| Status | Meaning |
|---|---|
| 400 | Missing or empty parameter |
| 422 | Invalid parameter type |
| 404 | Profile not found |
| 502 | External API returned invalid response |

---

## Local Setup

```bash
git clone <your-repo-url>
cd stage1-profiles
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash
pip install -r requirements.txt
```

Create a `.env` file:
```
DATABASE_URL=your_neon_postgres_url
SECRET_KEY=your_secret_key
DEBUG=False
```

```bash
python manage.py migrate
python manage.py seed   # loads 2026 profiles
python manage.py runserver
```