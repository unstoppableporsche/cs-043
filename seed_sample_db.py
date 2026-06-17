import sqlite3
from pathlib import Path


DB_PATH = Path("imdb_movies.db")

MOVIES = [
    ("tt1375666", "Inception", "Inception", 2010, 148, "Action,Adventure,Sci-Fi", 8.8, 2600000),
    ("tt0816692", "Interstellar", "Interstellar", 2014, 169, "Adventure,Drama,Sci-Fi", 8.7, 2200000),
    ("tt0468569", "The Dark Knight", "The Dark Knight", 2008, 152, "Action,Crime,Drama", 9.0, 2900000),
    ("tt6751668", "Parasite", "Gisaengchung", 2019, 132, "Drama,Thriller", 8.5, 1000000),
    ("tt4154796", "Avengers: Endgame", "Avengers: Endgame", 2019, 181, "Action,Adventure,Drama", 8.4, 1300000),
    ("tt7286456", "Joker", "Joker", 2019, 122, "Crime,Drama,Thriller", 8.4, 1600000),
    ("tt1853728", "Django Unchained", "Django Unchained", 2012, 165, "Drama,Western", 8.5, 1700000),
    ("tt4154756", "Avengers: Infinity War", "Avengers: Infinity War", 2018, 149, "Action,Adventure,Sci-Fi", 8.4, 1200000),
    ("tt2582802", "Whiplash", "Whiplash", 2014, 106, "Drama,Music", 8.5, 1000000),
    ("tt2380307", "Coco", "Coco", 2017, 105, "Adventure,Animation,Drama", 8.4, 650000),
    ("tt9362722", "Spider-Man: Across the Spider-Verse", "Spider-Man: Across the Spider-Verse", 2023, 140, "Action,Adventure,Animation", 8.6, 420000),
    ("tt15398776", "Oppenheimer", "Oppenheimer", 2023, 180, "Biography,Drama,History", 8.3, 850000),
]


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


def seed_sample_database() -> None:
    conn = sqlite3.connect(DB_PATH)
    reset_schema(conn)
    conn.executemany(
        """
        INSERT INTO movies (
            tconst, primary_title, original_title, start_year, runtime_minutes,
            genres, average_rating, num_votes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        MOVIES,
    )

    genre_rows = []
    for movie in MOVIES:
        tconst = movie[0]
        for genre in movie[5].split(","):
            genre_rows.append((tconst, genre))

    conn.executemany(
        "INSERT INTO movie_genres (tconst, genre) VALUES (?, ?)",
        genre_rows,
    )
    conn.commit()
    conn.close()
    print(f"Seeded {len(MOVIES)} sample movies into {DB_PATH}")


if __name__ == "__main__":
    seed_sample_database()
