"""Install only the new factory tables without running older Alembic revisions.

Back up the database first. Never drops or alters existing tables.
"""
from sqlalchemy import inspect

from server import database
from server.content_factory_purchase import metadata


def install(engine):
    inspector = inspect(engine)
    existing = {table.name for table in metadata.sorted_tables if inspector.has_table(table.name)}
    expected = {table.name for table in metadata.sorted_tables}
    if existing and existing != expected:
        raise RuntimeError("Partial content-factory schema; inspect manually before continuing")
    if not existing:
        with engine.begin() as connection:
            metadata.create_all(connection, checkfirst=False)
    inspector = inspect(engine)
    for table in metadata.sorted_tables:
        actual = {item['name'] for item in inspector.get_columns(table.name)}
        if not set(table.c.keys()).issubset(actual):
            raise RuntimeError(f"Incomplete content-factory table: {table.name}")
    unique = inspector.get_unique_constraints('content_factory_products')
    if not any(item.get('column_names') == ['content_fingerprint'] for item in unique):
        raise RuntimeError('Missing content fingerprint uniqueness constraint')


if __name__ == '__main__':
    install(database.ENGINE)
    print('Content factory schema installed and verified')
