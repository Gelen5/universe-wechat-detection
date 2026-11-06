from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select

from server.content_factory_purchase import InsufficientPoints, SoldOut, metadata, products, purchase
from server.models import PointTransaction, Wallet


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'factory.db').as_posix()}", connect_args={"timeout": 10})
    # Tables from the legacy account service are deliberately independent of
    # the new product schema in production.
    Wallet.__table__.create(engine, checkfirst=True)
    PointTransaction.__table__.create(engine, checkfirst=True)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(products.insert().values(id="p", status="published", price_points=5))
        connection.execute(Wallet.__table__.insert(), [
            dict(user_id=user, balance=10, trial_balance=2, bonus_balance=3, paid_balance=5, updated_at="now")
            for user in ("a", "b")
        ])
    return engine


def test_purchase_is_idempotent_and_exclusive(engine):
    assert not purchase(engine, "p", "a")["already_owned"]
    assert purchase(engine, "p", "a")["already_owned"]
    with pytest.raises(SoldOut):
        purchase(engine, "p", "b")
    with engine.connect() as connection:
        assert connection.execute(select(Wallet.balance).where(Wallet.user_id == "a")).scalar_one() == 5
        assert connection.execute(select(Wallet.balance).where(Wallet.user_id == "b")).scalar_one() == 10
        assert len(connection.execute(select(PointTransaction.__table__)).all()) == 1


def test_insufficient_balance_rolls_back_claim(engine):
    with engine.begin() as connection:
        connection.execute(products.update().values(price_points=11))
    with pytest.raises(InsufficientPoints):
        purchase(engine, "p", "a")
    with engine.connect() as connection:
        assert connection.execute(select(products.c.status)).scalar_one() == "published"
        assert not connection.execute(select(PointTransaction.__table__)).all()


def test_concurrent_buyers_only_one_is_charged(engine):
    def buy(user):
        try:
            purchase(engine, "p", user)
            return "bought"
        except SoldOut:
            return "sold"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(buy, ("a", "b"))) == ["bought", "sold"]
    with engine.connect() as connection:
        assert sum(connection.execute(select(Wallet.balance)).scalars()) == 15
        assert len(connection.execute(select(PointTransaction.__table__)).all()) == 1


def test_ledger_failure_rolls_back_wallet_and_product(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TRIGGER reject_ledger BEFORE INSERT ON point_transactions BEGIN SELECT RAISE(ABORT, 'failure'); END")
    with pytest.raises(Exception):
        purchase(engine, "p", "a")
    with engine.connect() as connection:
        assert connection.execute(select(products.c.status)).scalar_one() == "published"
        assert connection.execute(select(Wallet.balance).where(Wallet.user_id == "a")).scalar_one() == 10


def test_migration_creates_new_tables_without_touching_other_tables(tmp_path, monkeypatch):
    from sqlalchemy import inspect
    engine = create_engine(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
    revision = Path(__file__).resolve().parents[1] / 'db/alembic/versions/20261107_0017_content_factory.py'
    spec = importlib.util.spec_from_file_location('factory_revision', revision)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE existing (id INTEGER PRIMARY KEY)')
        monkeypatch.setattr(module.op, 'get_bind', lambda: connection)
        module.upgrade()
        module.upgrade()
    assert {'existing', 'content_factory_products', 'content_factory_feedback', 'content_factory_jobs'} <= set(inspect(engine).get_table_names())


def test_schema_installer_is_additive_and_idempotent(tmp_path):
    from scripts.install_content_factory_schema import install
    engine = create_engine(f"sqlite:///{(tmp_path / 'install.db').as_posix()}")
    install(engine)
    install(engine)
