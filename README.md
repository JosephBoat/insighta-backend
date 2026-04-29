# Insighta Labs — Backend

The core API for the Insighta Labs+ platform. Provides profile intelligence, authentication, and data management.

## Live API
```
https://hng-stage1-profiles.fly.dev
```

## Tech Stack
- **Framework:** Django + Django REST Framework
- **Database:** PostgreSQL (Neon)
- **Deployment:** Fly.io
- **Auth:** GitHub OAuth 2.0 with PKCE + JWT tokens

---

## System Architecture

```
CLI / Web Portal
      │
      ▼
Fly.io (Django API)
      │
      ├── /auth/*     → GitHub OAuth, token management
      └── /api/*      → Profile CRUD, search, export
              │
              ▼
      Neon PostgreSQL
```

---

## Authentication Flow

1. Client initiates login → `GET /auth/github`
2. Backend redirects to GitHub OAuth page
3. User authorizes on GitHub
4. GitHub redirects to `GET /auth/github/callback?code=...`
5. Backend exchanges code for GitHub access token
6. Backend fetches user info from GitHub API
7. Backend creates/updates user in DB
8. Backend issues access token (3min) + refresh token (5min)
9. CLI/API clients receive JSON tokens and use `Authorization: Bearer <token>`
10. Browser clients receive HTTP-only cookies plus a readable CSRF cookie

### PKCE Flow (CLI)
The CLI generates a `code_verifier` (random secret) and `code_challenge` (SHA256 hash of verifier). The challenge is sent to GitHub. When exchanging the code, the verifier is sent to prove the same client initiated the flow.

### Token Handling
- **Access token** — JWT, stateless, 3 minute expiry
- **Refresh token** — stored in DB, 5 minute expiry, single use (rotated on every refresh)
- **Logout** — deletes refresh token from DB immediately

---

Web portal cookies use HTTP-only `access_token` and `refresh_token` values; unsafe cookie-authenticated requests must send `X-CSRF-Token`.

## Role Enforcement

| Role | Permissions |
|---|---|
| `admin` | Full access: create, read, delete profiles, search, export |
| `analyst` | Read-only: list, get, search, export profiles |

All `/api/*` endpoints require:
1. Valid `Authorization: Bearer <token>` header
2. `X-API-Version: 1` header, or use the `/api/v1/*` route aliases
3. Appropriate role for the operation

The first user to log in is automatically assigned `admin` when no admin exists. All subsequent users get `analyst`.

---

## API Endpoints

### Auth
```
GET  /auth/github              → Redirect to GitHub OAuth
GET  /auth/github/callback     → Handle OAuth callback
POST /auth/refresh             → Refresh token pair
POST /auth/logout              → Invalidate refresh token
GET  /auth/whoami              → Get current user info
```

### Profiles (require X-API-Version: 1 + Bearer token)
```
GET    /api/profiles           → List profiles (filter, sort, paginate)
POST   /api/profiles           → Create profile (admin only)
GET    /api/profiles/search    → Natural language search
GET    /api/profiles/export    → Export CSV
GET    /api/profiles/{id}      → Get single profile
DELETE /api/profiles/{id}      → Delete profile (admin only)
```

### Filtering Parameters
| Parameter | Description |
|---|---|
| `gender` | male or female |
| `age_group` | child, teenager, adult, senior |
| `country_id` | ISO code e.g. NG |
| `min_age` / `max_age` | Age range |
| `min_gender_probability` | e.g. 0.8 |
| `min_country_probability` | e.g. 0.5 |
| `sort_by` | age, created_at, gender_probability |
| `order` | asc or desc |
| `page` / `limit` | Pagination (max limit: 50) |

---

## Natural Language Parsing

The parser (`profiles/parser.py`) uses rule-based keyword matching — no AI.

### Supported Keywords
| Input | Maps to |
|---|---|
| male, males, men, man | `gender=male` |
| female, females, women, woman | `gender=female` |
| young | `min_age=16, max_age=24` |
| above X, over X, older than X | `min_age=X` |
| below X, under X, younger than X | `max_age=X` |
| child, children | `age_group=child` |
| teenager, teen | `age_group=teenager` |
| adult, adults | `age_group=adult` |
| senior, elderly | `age_group=senior` |
| from \<country\> | `country_id=<ISO code>` |

### Limitations
- One gender per query (first match wins)
- Country must follow "from" keyword
- No negation support ("not from nigeria")
- No age range expressions ("between 20 and 30")
- "young" maps to 16-24 for parsing only, not a stored age group

---

## Rate Limiting
| Scope | Limit |
|---|---|
| `/auth/*` | 10 requests/minute |
| All other endpoints | 60 requests/minute per user |

---

## Local Setup

```bash
git clone https://github.com/JosephBoat/insighta-backend.git
cd insighta-backend
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash
pip install -r requirements.txt
```

Create `.env`:
```
DATABASE_URL=your_neon_postgres_url
SECRET_KEY=your_secret_key
DEBUG=False
GITHUB_CLIENT_ID=your_github_client_id
GITHUB_CLIENT_SECRET=your_github_client_secret
GITHUB_REDIRECT_URI=http://localhost:8000/auth/github/callback
JWT_SECRET=your_jwt_secret
FRONTEND_URL=http://localhost:3000
```

```bash
python manage.py migrate
python manage.py seed
python manage.py runserver
```
