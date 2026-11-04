from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine():
    return create_engine(get_settings().database_url)


def get_db() -> Iterator[Session]:
    with sessionmaker(bind=get_engine(), expire_on_commit=False)() as db:
        yield db
