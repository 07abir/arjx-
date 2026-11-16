"""Initialize the local SQLite database."""

from database.db import initialize_database


if __name__ == "__main__":
    initialize_database()
    print("MarketPilot AI database is ready.")

