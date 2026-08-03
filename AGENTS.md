# CV Tailor Backend — Agent Guide

## Tech Stack
- **Framework:** FastAPI (async)
- **Database:** PostgreSQL + SQLAlchemy (async via asyncpg)
- **Auth:** JWT (python-jose) + bcrypt
- **LLM Gateway:** OpenRouter API (OpenAI-compatible SDK via httpx)
- **Package Manager:** uv

## How to Run

```bash
uv run fastapi dev app/main.py    # development
```

Config via `.env` (copy from `.env.example`).

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI entry + lifespan (init_db + seed_templates + checkpointer + memory store)
│   ├── config.py            # Env vars: DB_URL, SECRET_KEY, OPENROUTER_*
│   ├── database.py          # Async engine + session + get_db dependency
│   ├── models.py            # SQLAlchemy models: User, Template, UserCV, CVVersion
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── auth.py              # JWT create/decode, bcrypt hashing, get_current_user
│   ├── seed.py              # Startup seeder for default template
│   ├── resume-template.html # Default CV seed template
│   ├── agent/
│   │   ├── agent.py         # build_agent (async): CV tools + memory tools, auto-inject memori ke system prompt
│   │   ├── checkpointer.py  # AsyncPostgresSaver singleton (chat history per thread)
│   │   ├── memory_store.py  # AsyncPostgresStore singleton (long-term memory fakta user)
│   │   └── tools/
│   │       ├── cv.py        # CV edit tools: get_current_html, read_lines, edit_lines, cv_replace, set_cv_title
│   │       └── memory.py    # Memory tools: get_memory, save_fact, delete_fact
│   ├── services/
│   │   ├── agent_session_service.py  # SSE streaming agent runs, thread history
│   │   └── tool_progress.py
│   └── routers/
│       ├── auth.py          # POST /api/auth/register, /login, GET /api/auth/me
│       ├── templates.py     # GET /api/templates
│       ├── cv.py            # CRUD /api/cv + versioning + publish
│       ├── memory.py        # GET/POST/PATCH/DELETE /api/memory (kelola long-term memory)
│       ├── public.py        # GET /api/cv/p/{slug} public CV
│       └── agent_protocol.py# POST/GET/DELETE /api/threads (chat agent protocol)
├── .env.example
└── pyproject.toml
```

## Database Schema

### User
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| email | VARCHAR UNIQUE | |
| display_name | VARCHAR | Wajib register |
| hashed_password | VARCHAR | bcrypt |
| created_at | DATETIME | auto |
| updated_at | DATETIME | auto |

### Template
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| title | VARCHAR | |
| html_code | TEXT | Full HTML |
| creator_id | FK→User | NULL for seed |
| is_published | BOOL | |
| created_at, updated_at | DATETIME | |

### UserCV
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| user_id | FK→User | |
| template_id | FK→Template | |
| title | VARCHAR | User-editable (defaults to template title) |
| created_at, updated_at | DATETIME | |

### CVVersion
| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| user_cv_id | FK→UserCV | |
| html_content | TEXT | Full HTML snapshot |
| created_at | DATETIME | |

> `current_html` is NOT stored on UserCV — always derived from latest `cv_version` (ORDER BY created_at DESC LIMIT 1).

## API Endpoints

### Auth (`/api/auth`)
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /register | No | Register → JWT |
| POST | /login | No | Login → JWT |
| GET | /me | Yes | Current user info |

### Templates (`/api/templates`)
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | / | No | List published templates |

### CV (`/api/cv`)
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | / | Yes | List user's CVs |
| POST | / | Yes | Create CV + first generate (takes template_id + prompt) |
| GET | /{id} | Yes | CV detail + latest HTML |
| PATCH | /{id} | Yes | Update CV title |
| DELETE | /{id} | Yes | Delete CV + all versions |
| GET | /{id}/versions | Yes | List version history |
| POST | /{id}/versions/{vid}/revert | Yes | Restore old version → new version |
| POST | /{id}/generate | Yes | Refine CV via LLM chat |

### Memory (`/api/memory`)
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | / | Yes | List all user facts: `{facts: [...]}` |
| POST | / | Yes | Create fact `{category, content}` (category bebas) |
| PATCH | /{key} | Yes | Update fact content (last-write-wins) |
| DELETE | /{key} | Yes | Delete fact |

## LLM Integration (OpenRouter)

- **System Prompt:** Dynamic — base prompt + injected long-term memory summary (`build_memory_summary`)
- **Model:** Configurable via `OPENROUTER_MODEL` env (default: `google/gemini-3.6-flash`)
- **Tools:** CV edit tools (`tools/cv.py`) + memory tools (`tools/memory.py` — get_memory(category), save_fact, delete_fact)
- **Long-term Memory:** `AsyncPostgresStore` (tabel `store`), namespace `("user", id)`; fakta = JSON docs `{category, content, created_at, updated_at}`, key = uuid; kategori bebas
- **Error:** Missing API key → clear error message

## Migrations (Alembic)

Setup: `uv run alembic init alembic` (already done)

Commands:
```bash
uv run alembic revision --autogenerate -m "description"   # auto-detect schema changes
uv run alembic upgrade head                                # apply pending migrations
uv run alembic downgrade -1                                # undo last migration
```

> Note: The database has circular FK between `user_cv.current_version_id` → `cv_version.id` and `cv_version.user_cv_id` → `user_cv.id`. Autogenerate may fail to sort tables — if so, manually reorder in the generated migration file.

## Adding New Features

### New Router
1. Create `app/routers/feature.py`
2. Add `app.include_router(feature.router)` in `main.py`
3. Define pydantic schemas in `schemas.py` if needed

### New Model
1. Add class in `models.py` extending `Base`
2. Add relationship if needed
3. `init_db()` auto-creates tables on startup

### New Endpoint
- Use `Depends(get_db)` for DB session
- Use `Depends(get_current_user)` for protected routes
- Return pydantic models via `response_model`

## Key Conventions
- All datetime columns use `server_default=func.now()` + `onupdate`
- CV HTML content always served from `cv_version` (never stored directly on UserCV)
- `cv_version` is immutable — no updates, only inserts
- Async everywhere (no sync DB calls)
