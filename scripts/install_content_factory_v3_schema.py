"""Add only V3 automation tables and columns; never drops or rewrites data."""
from sqlalchemy import inspect, text

from server import database
from server.content_factory_v3_store import metadata

KNOWN_ADDITIVE_COLUMNS = {
    "content_factory_v3_settings": {
        "vision_call_bound_micros": "INTEGER NOT NULL DEFAULT 0",
        "image_people_mode": "VARCHAR(16) NOT NULL DEFAULT 'auto'",
    },
    "content_factory_v3_runs": {
        "attempt": "INTEGER NOT NULL DEFAULT 0",
    },
}


def install(engine):
    with engine.begin() as connection:
        metadata.create_all(connection, checkfirst=True)
        # create_all() creates missing tables, but it never adds columns to an
        # existing table. Reconcile the columns introduced after the first V3
        # rollout before deciding whether the schema is complete.
        inspector = inspect(connection)
        for table_name, columns in KNOWN_ADDITIVE_COLUMNS.items():
            if not inspector.has_table(table_name):
                continue
            actual = {item['name'] for item in inspector.get_columns(table_name)}
            for column, definition in columns.items():
                if column in actual:
                    continue
                quote = connection.dialect.identifier_preparer.quote
                connection.exec_driver_sql(
                    f"ALTER TABLE {quote(table_name)} ADD COLUMN {quote(column)} {definition}"
                )
        if not connection.execute(
                text("SELECT 1 FROM content_factory_v3_settings WHERE id = 1 LIMIT 1")).first():
            from server.content_factory_v3_store import ensure_settings
            ensure_settings(connection)
    inspector = inspect(engine)
    for table in metadata.sorted_tables:
        if not inspector.has_table(table.name):
            raise RuntimeError(f"Missing V3 table: {table.name}")
        actual = {item['name'] for item in inspector.get_columns(table.name)}
        if not set(table.c.keys()).issubset(actual):
            raise RuntimeError(f"Incomplete V3 table: {table.name}")
    return True


if __name__ == '__main__':
    install(database.ENGINE)
    print('Content factory V3 schema installed and verified')
