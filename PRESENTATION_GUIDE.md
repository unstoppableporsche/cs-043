# Final Presentation Guide

Use this as your talking script for the Paladio AI demo.

## 1. Frontend

I used a simple HTML, CSS, and JavaScript frontend so the project stays focused on the data flow instead of framework setup.

Main UI components:

- Question box: user types a natural-language movie question.
- Sample questions: 10 prepared demo questions.
- Answer card: concise natural-language answer.
- Results section: table output and simple bar chart when numeric data is returned.
- Query details: expandable SQL transparency section.
- Dataset schema: expandable schema explorer.

The chat box sends a question with `fetch()`:

```js
POST /api/ask
{ "question": "Which genres have the highest average rating?" }
```

The frontend displays returned answers, SQL, rows, confidence, and errors.

## 2. Backend / API

An API is the contract that lets the frontend talk to the backend. The frontend sends HTTP requests, and the backend returns JSON.

- `GET`: reads data from the backend.
- `POST`: sends new data to the backend for processing.
- `PUT`: updates existing data.
- `DELETE`: removes data.

Endpoints created:

- `GET /`: returns the web app.
- `GET /api/schema`: returns database tables and columns.
- `GET /api/sample-questions`: returns the 10 demo questions.
- `GET /api/status`: returns whether the OpenAI model is enabled.
- `POST /api/ask`: accepts a question, generates SQL, runs it, and returns the answer.

Data sent from frontend to backend:

```json
{ "question": "Show average runtime by genre." }
```

Data returned from backend:

```json
{
  "answer": "Top result: Biography with 180 avg runtime minutes. Showing 10 rows.",
  "sql": "SELECT ...",
  "rows": [],
  "confidence": 0.9,
  "source": "demo-rule"
}
```

## 3. Database

Database used: SQLite.

Tables:

- `movies`: one row per movie.
- `movie_genres`: one row per movie and genre, so genre questions are easier to query.

Important columns:

- `primary_title`
- `start_year`
- `runtime_minutes`
- `genres`
- `average_rating`
- `num_votes`

Example SQL:

```sql
SELECT primary_title, start_year, average_rating, num_votes
FROM movies
WHERE num_votes >= 100000
ORDER BY average_rating DESC
LIMIT 10;
```

```sql
SELECT genre, COUNT(*) AS movie_count
FROM movie_genres
GROUP BY genre
ORDER BY movie_count DESC
LIMIT 10;
```

```sql
SELECT start_year, COUNT(*) AS movie_count
FROM movies
WHERE start_year >= 2010
GROUP BY start_year
ORDER BY start_year;
```

## 4. LLM / Chat Model

The app supports OpenAI with `gpt-4.1-mini` when `OPENAI_API_KEY` is set. I chose it because it is fast, affordable, and strong enough for SQL generation from a small schema.

The backend passes schema context to the model in the system prompt. The model is told:

- Use only the listed tables and columns.
- Return one SQLite `SELECT` query.
- Do not return destructive SQL.
- Return JSON with `sql` and `confidence`.

To reduce hallucinations:

- The prompt includes the exact schema.
- SQL is validated before execution.
- Only `SELECT` statements are allowed.
- Multiple statements and destructive keywords are blocked.
- If no API key is configured, the app uses deterministic demo rules for reliability.

What can go wrong:

- The model may invent a column.
- The model may misunderstand vague questions.
- The model may generate SQL that is valid but not what the user intended.

## 5. Testing

Basic tests to show:

- Run all 10 sample questions.
- Ask an invalid question: `Who won the Super Bowl?`
- Ask a no-result question: `Show top action movies after 2099.`
- Send malformed API JSON to `POST /api/ask`.
- Confirm generated SQL only uses `movies` and `movie_genres`.
- Confirm the frontend shows backend errors cleanly.

## 6. Final Demo Script

1. Dataset: IMDb public movie title and ratings files.
2. Database: SQLite with `movies` and `movie_genres`.
3. Frontend: question box, answer, results, SQL details, schema details.
4. Backend flow: frontend sends question to `POST /api/ask`.
5. Model flow: OpenAI generates SQL when API key is set; otherwise demo rules handle sample questions.
6. Example: ask `Which genres have the highest average rating?`
7. Show generated SQL in Query details.
8. Show table and chart results.
9. Failure case: ask an unrelated question and show the clean error.
10. Improvements: add actors/directors, persistent audit trail, better chart selection, and more automated tests.
