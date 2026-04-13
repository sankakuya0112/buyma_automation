"""SQLite セッション・トランザクション管理"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base

_engine = None
_SessionFactory = None


def init_db(db_path: str) -> None:
    """
    データベースエンジンを初期化し、テーブルを作成する。
    アプリ起動時に一度だけ呼び出す。
    """
    global _engine, _SessionFactory

    _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(_engine)
    _SessionFactory = sessionmaker(bind=_engine)


def get_session() -> Session:
    """
    新しい DB セッションを返す。
    呼び出し側が .close() を責任を持って呼ぶこと。
    with get_session_context() の使用を推奨。
    """
    if _SessionFactory is None:
        raise RuntimeError("DB not initialized. Call init_db() first.")
    return _SessionFactory()


@contextmanager
def get_session_context() -> Generator[Session, None, None]:
    """
    コンテキストマネージャー形式でセッションを提供。
    例外時は自動ロールバック、終了時は自動クローズ。

    Usage:
        with get_session_context() as session:
            session.add(...)
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
