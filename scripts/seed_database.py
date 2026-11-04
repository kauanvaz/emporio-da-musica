import logging
import os

from dotenv import load_dotenv

from mcp_server.database.seed import SeedValidationError, seed_database

logger = logging.getLogger(__name__)


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(message)s",
    )

    database_path = os.getenv("DATABASE_PATH", "emporio.db")
    data_dir = os.getenv("DATA_DIR", "data")

    try:
        final_path = seed_database(
            database_path=database_path,
            data_dir=data_dir,
        )
    except SeedValidationError as exc:
        logger.error("Seed failed: %s", exc)
        return 1

    logger.info("Database seeded at %s", final_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
