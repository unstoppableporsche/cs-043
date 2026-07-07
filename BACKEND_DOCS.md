# Backend API Docs

The backend is a FastAPI app in `server.py`. It exposes JSON endpoints that the frontend calls with `fetch()`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Serves the frontend app. |
| `GET` | `/api/status` | Shows database name, model name, and whether OpenAI is enabled. |
| `GET` | `/api/schema` | Returns SQLite table and column metadata. |
| `GET` | `/api/table-preview` | Returns row counts and preview rows for the SQL tables. |
| `GET` | `/api/sample-questions` | Returns the 10 prepared demo questions. |
| `POST` | `/api/register` | Creates a local user with a unique username and hashed password. |
| `POST` | `/api/login` | Verifies credentials, creates a session cookie, and records the login event. |
| `POST` | `/api/logout` | Clears the active session. |
| `GET` | `/api/me` | Returns the current logged-in user. |
| `GET` | `/api/login-events` | Returns recent successful login events. |
| `GET` | `/api/chat-audit` | Returns recent question-to-SQL history for the logged-in user. |
| `POST` | `/api/ask` | Accepts a user question, generates SQL, runs it, and returns the answer. |

## Main Chat Request

```http
POST /api/ask
Content-Type: application/json
```

```json
{
  "question": "Which genres have the highest average rating?"
}
```

## Main Chat Response

```json
{
  "question": "Which genres have the highest average rating?",
  "answer": "Top result: Crime with 8.7 avg rating. Showing 10 rows.",
  "sql": "SELECT g.genre, ROUND(AVG(m.average_rating), 2) AS avg_rating ...",
  "rows": [],
  "confidence": 0.92,
  "source": "demo-rule"
}
```

## Safety Rules

- Users must log in before asking chat questions.
- Usernames are unique in the `users` table.
- Passwords are hashed with PBKDF2 and are not stored as plaintext.
- Successful logins are recorded in the `login_events` audit table.
- Chat questions are recorded in the `chat_audit` table with generated SQL, answer summary, source, confidence, row count, success/failure, and timestamp.
- Prompts are checked for sensitive data before any LLM call.
- The app blocks likely Social Security numbers, API keys, credit card numbers, emails, and phone numbers.
- Only `SELECT` statements are allowed.
- Multiple SQL statements are blocked.
- Destructive SQL keywords like `DROP`, `DELETE`, `UPDATE`, and `INSERT` are blocked.
- A default `LIMIT` is added when the model does not provide one.
- The LLM receives the exact schema so it is less likely to invent fields.

## Graceful Fallback

The chat endpoint tries answers in this order:

1. Use LiteLLM model routing when `LITELLM_MODELS` or `OPENAI_API_KEY` is configured.
2. If LiteLLM is unavailable, fall back to the direct OpenAI SDK path.
3. If model generation is unavailable or its SQL fails validation/execution, try deterministic demo-rule SQL.
4. If neither path can answer the question, return a clear error plus suggested sample questions.

This means the app still works for known demo questions when the LLM is unavailable, and it fails clearly for unsupported questions instead of pretending to know the answer.

## Memory / Audit Trail

The app uses database-backed memory instead of relying on the LLM to remember previous messages.

Each logged-in user's chat request is stored in `chat_audit` with:

- user id and username
- original question
- generated SQL
- answer summary
- model/source
- confidence score
- row count
- success or failure
- error message when applicable
- timestamp

This makes the app easier to debug and gives a transparent question -> SQL -> result history.

Optional multi-model routing can be configured with:

```text
LITELLM_MODELS=openai/gpt-4.1-mini,gemini/gemini-1.5-flash,anthropic/claude-3-5-haiku
```

Each provider still needs its own API key in the environment. SQL validation remains the final safety gate no matter which model generated the query.
