"""Keep temporary unit-test databases from leaking into later API tests."""
import pytest
from tests import support  # noqa: F401 - select an isolated DB before collection imports server code


@pytest.fixture(autouse=True)
def restore_database_bindings():
    # Snapshot after collection, so API module initialization has finished.
    from server import database
    previous = database.ENGINE, database.SessionLocal
    try:
        yield
    finally:
        database.ENGINE, database.SessionLocal = previous
