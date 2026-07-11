from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.tenant import Hotel, HotelChain
from app.services.budget_scope import get_or_create_budget_scope, get_or_create_project_for_budget


def test_contextual_budget_scope_and_project_are_idempotent_with_null_hotel():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    brand_a, brand_b = HotelChain(name="A"), HotelChain(name="B")
    db.add_all([brand_a, brand_b])
    db.flush()

    first = get_or_create_budget_scope(db, 2025, brand_a.id, None, "252536")
    same = get_or_create_budget_scope(db, 2025, brand_a.id, None, "252536")
    next_year = get_or_create_budget_scope(db, 2026, brand_a.id, None, "252536")
    other_brand = get_or_create_budget_scope(db, 2025, brand_b.id, None, "252536")
    project = get_or_create_project_for_budget(db, 2025, brand_a.id, None, first.id)
    same_project = get_or_create_project_for_budget(db, 2025, brand_a.id, None, first.id)

    assert first.id == same.id
    assert {first.id, next_year.id, other_brand.id}.__len__() == 3
    assert project.id == same_project.id


def test_contextual_budget_scope_distinguishes_hotels():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    brand = HotelChain(name="A")
    db.add(brand)
    db.flush()
    hotel_a, hotel_b = Hotel(chain_id=brand.id, name="Hotel A"), Hotel(chain_id=brand.id, name="Hotel B")
    db.add_all([hotel_a, hotel_b])
    db.flush()

    a = get_or_create_budget_scope(db, 2025, brand.id, hotel_a.id, "252536")
    b = get_or_create_budget_scope(db, 2025, brand.id, hotel_b.id, "252536")
    assert a.id != b.id
