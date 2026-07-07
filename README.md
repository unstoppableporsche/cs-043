# IMDb Chat With Your Data

A small Paladio AI internship project: ingest public IMDb title data into SQLite, expose the schema, and let users ask plain-English questions that are translated into safe SQL and displayed with answers.

## Stack

- Backend: Python FastAPI
- Frontend: vanilla HTML/CSS/JavaScript
- Database: SQLite
- Dataset: IMDb public non-commercial datasets from https://datasets.imdbws.com/
- LLM: optional OpenAI SQL generation when `OPENAI_API_KEY` is set, with deterministic demo-question fallbacks

## Quick Start

```bash
pip install -r requirements.txt
python seed_db.py
python server.py
```

Open http://127.0.0.1:8000.

For a fast local smoke test without downloading the full IMDb files:

```bash
python seed_sample_db.py
python server.py
```

## Dataset

The seed script downloads and normalizes a focused subset from IMDb:

- `title.basics.tsv.gz`: movie metadata, year, runtime, genres
- `title.ratings.tsv.gz`: average rating and vote count

To keep the demo fast, the loader stores only feature films from 2000 onward with at least 1,000 votes by default. You can change this in `seed_db.py`.

## Schema

### movies

| Column | Type | Description |
| --- | --- | --- |
| `tconst` | TEXT primary key | IMDb title id |
| `primary_title` | TEXT | Display title |
| `original_title` | TEXT | Original title |
| `start_year` | INTEGER | Release year |
| `runtime_minutes` | INTEGER | Runtime |
| `genres` | TEXT | Comma-separated genre list |
| `average_rating` | REAL | IMDb average rating |
| `num_votes` | INTEGER | Number of IMDb votes |

### movie_genres

| Column | Type | Description |
| --- | --- | --- |
| `tconst` | TEXT | IMDb title id |
| `genre` | TEXT | One genre per row |

## Sample Questions

1. What are the top 10 highest rated movies with at least 100000 votes?
2. Which genres have the highest average rating?
3. Show the number of movies released each year since 2010.
4. What are the most common genres?
5. Which decade has the highest average movie rating?
6. Show top action movies after 2015.
7. What are the longest movies with at least 50000 votes?
8. How many movies are in the database?
9. Which year had the most highly rated movies?
10. Show average runtime by genre.

## Notes

What worked: SQLite plus a small normalized genre table makes the dataset easy to inspect and query. The app shows the generated SQL for transparency and validates SQL before execution.

What failed or was limited: the public IMDb files are large, so this project intentionally loads a filtered subset for demo. Furthermore, the SQL tables are limited in the amount of rows/columns that they can show. A production version would use background ingestion, richer cast/crew tables, and a more robust parsing.

What I would improve: add actor/director tables, save chat history to an audit table, and add chart type selection for time series and genre comparisons. I would also make the SQL shown in the UI more readable, instead of the side bar.
