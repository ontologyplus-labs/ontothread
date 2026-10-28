"""Wait for dedicated test databases; never modifies their contents."""
import os
import time
import psycopg
from neo4j import GraphDatabase


def main():
    deadline = time.monotonic() + 120
    while True:
        try:
            with psycopg.connect(os.environ["FIG_TEST_DATABASE_URL"], connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            with GraphDatabase.driver(os.environ["FIG_TEST_NEO4J_URI"],
                    auth=("neo4j", os.environ["FIG_TEST_NEO4J_PASSWORD"]),
                    connection_timeout=3, connection_acquisition_timeout=5) as driver:
                driver.verify_connectivity()
            print("Dedicated PostgreSQL and Neo4j services are ready.")
            return
        except Exception:
            if time.monotonic() >= deadline:
                raise SystemExit("Test services did not become ready within 120 seconds.") from None
            time.sleep(2)


if __name__ == "__main__":
    main()
