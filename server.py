import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


DB_PATH = Path("imdb_movies.db")
STATIC_DIR = Path("static")
MAX_ROWS = 100


def load_local_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = value


load_local_env()

app = FastAPI(title="IMDb Chat With Your Data")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


SCHEMA_DESCRIPTION = """
Tables:

movies(
  tconst TEXT primary key,
  primary_title TEXT,
  original_title TEXT,
  start_year INTEGER,
  runtime_minutes INTEGER,
  genres TEXT comma-separated,
  average_rating REAL,
  num_votes INTEGER
)

movie_genres(
  tconst TEXT references movies.tconst,
  genre TEXT
)
"""


SAMPLE_QUESTIONS = [
    "What are the top 10 highest rated movies with at least 100000 votes?",
    "Which genres have the highest average rating?",
    "Show the number of movies released each year since 2010.",
    "What are the most common genres?",
    "Which decade has the highest average movie rating?",
    "Show top action movies after 2015.",
    "What are the longest movies with at least 50000 votes?",
    "How many movies are in the database?",
    "Which year had the most highly rated movies?",
    "Show average runtime by genre.",
]

API_DOCS = [
    {
        "method": "GET",
        "path": "/",
        "purpose": "Serves the frontend web app.",
        "request": "No request body.",
        "response": "HTML page.",
    },
    {
        "method": "GET",
        "path": "/api/status",
        "purpose": "Shows whether the app is using OpenAI or demo-rule fallback mode.",
        "request": "No request body.",
        "response": "database, llm_enabled, model, fallback.",
    },
    {
        "method": "GET",
        "path": "/api/schema",
        "purpose": "Returns the SQLite tables and columns so the UI can show the data model.",
        "request": "No request body.",
        "response": "schema text plus table column metadata.",
    },
    {
        "method": "GET",
        "path": "/api/table-preview",
        "purpose": "Returns row counts and preview rows for the SQL tables.",
        "request": "Optional table name and row limit query parameters.",
        "response": "Preview rows for movies and movie_genres, or one selected table.",
    },
    {
        "method": "GET",
        "path": "/api/sample-questions",
        "purpose": "Returns the prepared demo questions.",
        "request": "No request body.",
        "response": "List of natural-language questions.",
    },
    {
        "method": "POST",
        "path": "/api/ask",
        "purpose": "Converts a user question into SQL, runs it safely, and returns an answer.",
        "request": '{ "question": "Which genres have the highest average rating?" }',
        "response": "answer, generated SQL, result rows, confidence, source.",
    },
]


class QuestionRequest(BaseModel):
    question: str


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=400,
            detail="Database not found. Run `python seed_db.py` first.",
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def generate_fallback_sql(question: str) -> tuple[str, float]:
    q = normalize(question)

    if "how many" in q or "count" in q:
        return "SELECT COUNT(*) AS movie_count FROM movies;", 0.98

    if "top" in q and ("rated" in q or "rating" in q):
        votes = 100000 if "100000" in q or "100 000" in q else 50000
        return f"""
            SELECT primary_title, start_year, genres, average_rating, num_votes
            FROM movies
            WHERE num_votes >= {votes}
            ORDER BY average_rating DESC, num_votes DESC
            LIMIT 10;
        """, 0.94

    if "genre" in q and ("highest average rating" in q or "average rating" in q):
        return """
            SELECT g.genre, ROUND(AVG(m.average_rating), 2) AS avg_rating, COUNT(*) AS movie_count
            FROM movie_genres g
            JOIN movies m ON m.tconst = g.tconst
            GROUP BY g.genre
            HAVING COUNT(*) >= 1
            ORDER BY avg_rating DESC, movie_count DESC
            LIMIT 10;
        """, 0.92

    if "released each year" in q or ("movies" in q and "year" in q and "since" in q):
        year_match = re.search(r"(20\d{2}|19\d{2})", q)
        start_year = year_match.group(1) if year_match else "2010"
        return f"""
            SELECT start_year, COUNT(*) AS movie_count
            FROM movies
            WHERE start_year >= {start_year}
            GROUP BY start_year
            ORDER BY start_year;
        """, 0.91

    if "common genres" in q or "popular genres" in q:
        return """
            SELECT genre, COUNT(*) AS movie_count
            FROM movie_genres
            GROUP BY genre
            ORDER BY movie_count DESC
            LIMIT 10;
        """, 0.95

    if "decade" in q:
        return """
            SELECT (start_year / 10) * 10 AS decade,
                   ROUND(AVG(average_rating), 2) AS avg_rating,
                   COUNT(*) AS movie_count
            FROM movies
            GROUP BY decade
            HAVING COUNT(*) >= 1
            ORDER BY avg_rating DESC
            LIMIT 10;
        """, 0.9

    if "action" in q:
        year_match = re.search(r"(20\d{2}|19\d{2})", q)
        start_year = year_match.group(1) if year_match else "2015"
        return f"""
            SELECT m.primary_title, m.start_year, m.average_rating, m.num_votes
            FROM movies m
            JOIN movie_genres g ON g.tconst = m.tconst
            WHERE g.genre = 'Action' AND m.start_year > {start_year}
            ORDER BY m.average_rating DESC, m.num_votes DESC
            LIMIT 10;
        """, 0.89

    if "longest" in q or "runtime" in q and "movie" in q:
        return """
            SELECT primary_title, start_year, runtime_minutes, average_rating, num_votes
            FROM movies
            WHERE runtime_minutes IS NOT NULL AND num_votes >= 50000
            ORDER BY runtime_minutes DESC
            LIMIT 10;
        """, 0.9

    if "highly rated" in q and "year" in q:
        return """
            SELECT start_year, COUNT(*) AS highly_rated_movies
            FROM movies
            WHERE average_rating >= 8.0 AND num_votes >= 10000
            GROUP BY start_year
            ORDER BY highly_rated_movies DESC, start_year DESC
            LIMIT 10;
        """, 0.88

    if "average runtime by genre" in q or ("runtime" in q and "genre" in q):
        return """
            SELECT g.genre, ROUND(AVG(m.runtime_minutes), 1) AS avg_runtime_minutes, COUNT(*) AS movie_count
            FROM movie_genres g
            JOIN movies m ON m.tconst = g.tconst
            WHERE m.runtime_minutes IS NOT NULL
            GROUP BY g.genre
            HAVING COUNT(*) >= 1
            ORDER BY avg_runtime_minutes DESC
            LIMIT 10;
        """, 0.9

    raise HTTPException(
        status_code=422,
        detail="I could not map that question to the IMDb schema. Try one of the sample questions or ask about movies, genres, ratings, years, votes, or runtime.",
    )


def generate_openai_sql(question: str) -> tuple[str, float] | None:
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Generate one SQLite SELECT query for the user's question. "
                        "Use only the provided schema. Return JSON with keys sql and confidence. "
                        "Never use INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA, or multiple statements.\n"
                        f"{SCHEMA_DESCRIPTION}"
                    ),
                },
                {"role": "user", "content": question},
            ],
        )
        content = response.choices[0].message.content or ""
        parsed = json.loads(content)
        return parsed["sql"], float(parsed.get("confidence", 0.75))
    except Exception:
        return None


def validate_sql(sql: str) -> str:
    cleaned = sql.strip().rstrip(";")
    lowered = cleaned.lower()
    forbidden = ["insert ", "update ", "delete ", "drop ", "alter ", "pragma ", "attach ", "detach "]
    if not lowered.startswith("select") or any(word in lowered for word in forbidden):
        raise HTTPException(status_code=400, detail="Only safe SELECT queries are allowed.")
    if ";" in cleaned:
        raise HTTPException(status_code=400, detail="Only one SQL statement is allowed.")
    if " limit " not in lowered:
        cleaned = f"{cleaned} LIMIT {MAX_ROWS}"
    return cleaned + ";"


def run_query(sql: str) -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = conn.execute(sql).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as exc:
        raise HTTPException(status_code=400, detail=f"SQL error: {exc}") from exc
    finally:
        conn.close()


def summarize(question: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No matching rows were found."
    if len(rows) == 1 and len(rows[0]) == 1:
        key, value = next(iter(rows[0].items()))
        return f"{key.replace('_', ' ').title()}: {value}."
    first = rows[0]
    if "primary_title" in first:
        details = []
        if "start_year" in first:
            details.append(str(first["start_year"]))
        if "average_rating" in first:
            details.append(f"rating {first['average_rating']}")
        suffix = f" ({', '.join(details)})" if details else ""
        return f"Top result: {first['primary_title']}{suffix}. Showing {len(rows)} rows."
    label_key = next(iter(first.keys()))
    value_keys = [key for key in first.keys() if key != label_key]
    if value_keys:
        value_key = value_keys[0]
        return f"Top result: {first[label_key]} with {first[value_key]} {value_key.replace('_', ' ')}. Showing {len(rows)} rows."
    return f"Found {len(rows)} result rows for: {question}"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/schema")
def schema():
    conn = connect()
    try:
        tables = {}
        for table in ["movies", "movie_genres"]:
            columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
            tables[table] = [dict(column) for column in columns]
        return {"schema": SCHEMA_DESCRIPTION, "tables": tables}
    finally:
        conn.close()


@app.get("/api/table-preview")
def table_preview(
    table: str | None = Query(default=None, pattern="^(movies|movie_genres)$"),
    limit: int = Query(default=8, ge=1, le=25),
):
    conn = connect()
    try:
        tables = [table] if table else ["movies", "movie_genres"]
        previews = {}
        for table_name in tables:
            count = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()["count"]
            rows = conn.execute(f"SELECT * FROM {table_name} LIMIT ?", (limit,)).fetchall()
            previews[table_name] = {
                "count": count,
                "rows": [dict(row) for row in rows],
            }
        return {"tables": previews}
    finally:
        conn.close()


@app.get("/api/docs")
def api_docs():
    return {"endpoints": API_DOCS}


@app.get("/api/sample-questions")
def sample_questions():
    return {"questions": SAMPLE_QUESTIONS}


@app.get("/api/status")
def status():
    load_local_env()
    env_path = Path(".env")
    env_key_in_file = False
    if env_path.exists():
        env_key_in_file = any(
            line.strip().startswith("OPENAI_API_KEY=")
            for line in env_path.read_text(encoding="utf-8").splitlines()
        )
    return {
        "database": DB_PATH.name,
        "llm_enabled": bool(os.getenv("OPENAI_API_KEY")),
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "fallback": "demo-rule",
        "cwd": str(Path.cwd()),
        "env_file_exists": env_path.exists(),
        "env_key_in_file": env_key_in_file,
    }


@app.post("/api/ask")
def ask(request: QuestionRequest):
    llm_result = generate_openai_sql(request.question)
    sql, confidence = llm_result or generate_fallback_sql(request.question)
    safe_sql = validate_sql(sql)
    rows = run_query(safe_sql)
    return {
        "question": request.question,
        "answer": summarize(request.question, rows),
        "sql": safe_sql,
        "rows": rows,
        "confidence": confidence,
        "source": "openai" if llm_result else "demo-rule",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="127.0.0.1", port=port, reload=False)
