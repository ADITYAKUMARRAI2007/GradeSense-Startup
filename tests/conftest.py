import pytest
from dotenv import load_dotenv

# Load environment variables used by app.database (MONGO_URL, DB_NAME)
load_dotenv()

# Ensure Motor client is re-initialized for test runs so it doesn't hold
# references to an event loop closed by pytest-asyncio.
# This fixes "Event loop is closed" errors in async DB tests.
from app import database
from motor.motor_asyncio import AsyncIOMotorClient


@pytest.fixture(scope="session", autouse=True)
def reset_motor_client():
    database.client = AsyncIOMotorClient(database.mongo_url)
    database.db = database.client[database.db_name]
    yield
    try:
        database.client.close()
    except Exception:
        pass
