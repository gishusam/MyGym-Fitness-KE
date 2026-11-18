from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.platform.app import GymTenant, PlatformAudit, PlatformBase
from backend.platform.link_existing import KNOWN_GYMS, sync_known_gyms


def test_sync_known_gyms_dry_run_and_idempotent(monkeypatch):
    monkeypatch.setenv('GYM_SOURCE_DATABASE_URL', 'postgresql+psycopg://fake@localhost/mygym_fitness_dev')
    monkeypatch.setenv('PLATFORM_DATABASE_URL', 'postgresql+psycopg://fake@localhost/mygym_platform')
    engine = create_engine('sqlite://')
    PlatformBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(GymTenant(slug='mygym-fitness-ke', name='MyGym Fitness KE'))
        db.commit()
    verify = lambda source, db, platform: 'DemoFit Studio' if db == 'mygym_demo' else 'MyGym Fitness KE'
    assert len(sync_known_gyms(verify=verify, session_factory=lambda:factory)) == 2
    with factory() as db:
        assert len(db.scalars(select(GymTenant)).all()) == 1
    assert len(sync_known_gyms(apply=True, verify=verify, session_factory=lambda:factory)) == 2
    assert len(sync_known_gyms(apply=True, verify=verify, session_factory=lambda:factory)) == 2
    with factory() as db:
        rows = db.scalars(select(GymTenant)).all()
        assert len(rows) == 2
        by_slug = {row.slug:row for row in rows}
        assert by_slug['mygym-fitness-ke'].database_ref == 'mygym_fitness_dev'
        assert by_slug['demofit-studio'].database_ref == 'mygym_demo'
        assert by_slug['mygym-fitness-ke'].status == 'linked'
        assert by_slug['demofit-studio'].environment_kind == 'demo'
        assert len(db.scalars(select(PlatformAudit)).all()) == 2
    engine.dispose()


def test_sync_refuses_reassigning_database(monkeypatch):
    monkeypatch.setenv('GYM_SOURCE_DATABASE_URL', 'postgresql+psycopg://fake@localhost/mygym_fitness_dev')
    monkeypatch.setenv('PLATFORM_DATABASE_URL', 'postgresql+psycopg://fake@localhost/mygym_platform')
    engine = create_engine('sqlite://')
    PlatformBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(GymTenant(name='Wrong gym', slug='wrong-gym', database_ref='mygym_demo'))
        db.commit()
    try:
        sync_known_gyms(apply=True, verify=lambda *a: 'Verified', session_factory=lambda:factory)
        assert False, 'Expected duplicate database refusal'
    except ValueError as e:
        assert 'already linked' in str(e)
    with factory() as db:
        assert len(db.scalars(select(GymTenant)).all()) == 1
    engine.dispose()


def test_sync_rejects_platform_database_as_source(monkeypatch):
    monkeypatch.setenv('GYM_SOURCE_DATABASE_URL', 'postgresql+psycopg://fake@localhost/mygym_platform')
    monkeypatch.setenv('PLATFORM_DATABASE_URL', 'postgresql+psycopg://fake@localhost/mygym_platform')
    try:
        sync_known_gyms(verify=lambda *a: 'Verified')
        assert False, 'Expected separation failure'
    except ValueError as e:
        assert 'separate' in str(e)
