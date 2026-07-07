# Paladio AI Internship Demo: Chat With Your Data

## Slide 1: Problem and Solution

**Problem**

- Public datasets are useful, but most people cannot easily query them with SQL.
- Raw IMDb files are large and not friendly for quick exploration.
- A user should be able to ask a normal English question and see where the answer came from.

**Solution**

- I built an IMDb “Chat with Your Data” web app.
- The app loads IMDb movie data into a SQLite database.
- A user asks a plain-English question.
- The backend converts the question into SQL, validates it, runs it, and returns the answer.
- The UI shows the answer, result table/chart, and generated SQL for transparency.

**Demo Example**

Question:

> Which genres have the highest average rating?

Flow:

> Question -> Backend -> SQL -> SQLite -> Answer + Results

## Slide 2: Tech Stack

**Frontend**

- HTML
- CSS
- JavaScript
- `fetch()` for API requests
- Two-tab UI: Chat and Data & Backend

**Backend / API**

- Python
- FastAPI
- Uvicorn local server
- Local login system with hashed passwords and login audit table
- Chat memory/audit table for question -> SQL -> result history
- JSON API endpoints:
  - `GET /api/schema`
  - `GET /api/table-preview`
  - `GET /api/status`
  - `POST /api/register`
  - `POST /api/login`
  - `POST /api/ask`

**Database and Dataset**

- SQLite database: `imdb_movies.db`
- IMDb public datasets:
  - `title.basics.tsv.gz`
  - `title.ratings.tsv.gz`
- Tables:
  - `movies`
  - `movie_genres`

**LLM**

- OpenAI API
- Model: `gpt-4.1-mini`
- `.env` file for API key
- LiteLLM model routing for optional secondary providers
- Prompt safety checks for sensitive personal data
- SQL validation layer to reduce unsafe or hallucinated queries
- Graceful fallback: LiteLLM/OpenAI first, demo rules second, suggestions if neither works

## Slide 3: Learnings

**What I Learned**

- How frontend and backend communicate through an API.
- How login/session flow works at a basic level.
- What `GET` and `POST` requests do.
- How to load, clean, and structure a real dataset.
- How SQLite tables and joins work.
- How an LLM can generate SQL from schema context.
- Why generated SQL should be shown and validated.
- Why prompts should be checked before sending them to an LLM.

**What Was Difficult**

- Managing environment variables and the OpenAI API key.
- Debugging stale localhost server processes and port issues.
- Making sure the model did not invent fields that were not in the database.
- Preventing private information, like SSNs or API keys, from being sent through the chat.
- Handling duplicate usernames and avoiding plaintext password storage.
- Keeping the UI simple while still showing schema, SQL, and backend details.

**What Worked**

- SQLite made the project easy to run locally.
- FastAPI made it straightforward to create API endpoints.
- The two-tab UI keeps the chat clean while still showing technical transparency.
- The fallback demo rules made the sample questions reliable.
- Suggested questions made unsupported prompts fail clearly instead of silently breaking.

**What I Would Improve Next**

- Add actors, directors, and cast tables.
- Expand the audit trail into dashboards for model quality and user history.
- Add more automated tests.
- Add better charts and follow-up question suggestions.
