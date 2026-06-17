import csv
import gzip
import sqlite3
from pathlib import Path

import requests


DATA_DIR = Path("data")
DB_PATH = Path("imdb_movies.db")
BASE_URL = "https://datasets.imdbws.com"
FILES = {
    "basics": "title.basics.tsv.gz",
    "ratings": "title.ratings.tsv.gz",
}

MIN_YEAR = 2000
MIN_VOTES = 1000


def download_file(filename: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    target = DATA_DIR / filename
    if target.exists():
        print(f"Using cached {target}")
        return target

    url = f"{BASE_URL}/{filename}"
    print(f"Downloading {url}")
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with target.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return target


def none_if_missing(value: str):
    return None if value == r"\N" else value


def int_or_none(value: str):
    value = none_if_missing(value)
    return int(value) if value else None


def float_or_none(value: str):
    value = none_if_missing(value)
    return float(value) if value else None


def load_ratings(path: Path) -> dict[str, tuple[float, int]]:
    ratings = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            votes = int_or_none(row["numVotes"])
            if votes is not None and votes >= MIN_VOTES:
                ratings[row["tconst"]] = (
                    float_or_none(row["averageRating"]),
                    votes,
                )
    return ratings


def reset_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS movie_genres;
        DROP TABLE IF EXISTS movies;

        CREATE TABLE movies (
            tconst TEXT PRIMARY KEY,
            primary_title TEXT NOT NULL,
            original_title TEXT,
            start_year INTEGER,
            runtime_minutes INTEGER,
            genres TEXT,
            average_rating REAL,
            num_votes INTEGER
        );

        CREATE TABLE movie_genres (
            tconst TEXT NOT NULL,
            genre TEXT NOT NULL,
            FOREIGN KEY (tconst) REFERENCES movies(tconst)
        );

        CREATE INDEX idx_movies_year ON movies(start_year);
        CREATE INDEX idx_movies_rating ON movies(average_rating);
        CREATE INDEX idx_movies_votes ON movies(num_votes);
        CREATE INDEX idx_movie_genres_genre ON movie_genres(genre);
        """
    )


def seed_database() -> None:
    basics_path = download_file(FILES["basics"])
    ratings_path = download_file(FILES["ratings"])
    ratings = load_ratings(ratings_path)

    conn = sqlite3.connect(DB_PATH)
    reset_schema(conn)

    movie_rows = []
    genre_rows = []

    with gzip.open(basics_path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tconst = row["tconst"]
            if row["titleType"] != "movie" or tconst not in ratings:
                continue

            year = int_or_none(row["startYear"])
            if year is None or year < MIN_YEAR:
                continue

            average_rating, num_votes = ratings[tconst]
            genres = none_if_missing(row["genres"]) or ""
            movie_rows.append(
                (
                    tconst,
                    row["primaryTitle"],
                    none_if_missing(row["originalTitle"]),
                    year,
                    int_or_none(row["runtimeMinutes"]),
                    genres,
                    average_rating,
                    num_votes,
                )
            )

            for genre in [g.strip() for g in genres.split(",") if g.strip()]:
                genre_rows.append((tconst, genre))

    conn.executemany(
        """
        INSERT INTO movies (
            tconst, primary_title, original_title, start_year, runtime_minutes,
            genres, average_rating, num_votes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        movie_rows,
    )
    conn.executemany(
        "INSERT INTO movie_genres (tconst, genre) VALUES (?, ?)",
        genre_rows,
    )
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    conn.close()
    print(f"Seeded {count:,} movies into {DB_PATH}")


if __name__ == "__main__":
    seed_database()
