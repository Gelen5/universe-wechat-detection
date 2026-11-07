import sqlalchemy as sa

from scripts.install_content_factory_v3_schema import install
from server.content_factory_v3_store import metadata


def test_v3_install_is_repeatable_and_creates_singleton_as_stopped(tmp_path):
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'schema.db').as_posix()}")
    assert install(engine)
    assert install(engine)
    inspector = sa.inspect(engine)
    assert {table.name for table in metadata.sorted_tables} <= set(inspector.get_table_names())
    with engine.connect() as connection:
        settings = connection.execute(sa.text(
            "SELECT emergency_stop, automatic_article_publish, automatic_image_publish "
            "FROM content_factory_v3_settings WHERE id=1")).one()
        assert settings[0] in (True, 1)
        assert settings[1] in (False, 0) and settings[2] in (False, 0)


def test_v3_install_repairs_known_columns_on_a_partial_schema(tmp_path):
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'partial.db').as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """CREATE TABLE content_factory_v3_settings (
                id INTEGER PRIMARY KEY,
                automatic_selection BOOLEAN NOT NULL DEFAULT 0,
                scheduled_selection BOOLEAN NOT NULL DEFAULT 0,
                automatic_articles BOOLEAN NOT NULL DEFAULT 0,
                automatic_images BOOLEAN NOT NULL DEFAULT 0,
                automatic_article_publish BOOLEAN NOT NULL DEFAULT 0,
                automatic_image_publish BOOLEAN NOT NULL DEFAULT 0,
                emergency_stop BOOLEAN NOT NULL DEFAULT 1,
                daily_budget_micros INTEGER NOT NULL DEFAULT 0,
                title_call_bound_micros INTEGER NOT NULL DEFAULT 0,
                article_call_bound_micros INTEGER NOT NULL DEFAULT 0,
                image_call_bound_micros INTEGER NOT NULL DEFAULT 0,
                detector_call_bound_micros INTEGER NOT NULL DEFAULT 0,
                cost_bound_verified BOOLEAN NOT NULL DEFAULT 0,
                article_limit INTEGER NOT NULL DEFAULT 0,
                image_limit INTEGER NOT NULL DEFAULT 0,
                minimum_score INTEGER NOT NULL DEFAULT 70,
                tracks_json TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL
            )""")
    from server.content_factory_v3_store import runs
    runs.create(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE content_factory_v3_runs DROP COLUMN attempt")

    assert install(engine)
    inspector = sa.inspect(engine)
    assert 'vision_call_bound_micros' in {
        item['name'] for item in inspector.get_columns('content_factory_v3_settings')}
    assert 'attempt' in {
        item['name'] for item in inspector.get_columns('content_factory_v3_runs')}
