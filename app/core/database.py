#创建sqlite连接和数据库session
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import sessionmaker

from app.core.config import DATABASE_URL


# 所有数据库表共同继承的基础类
class Base(DeclarativeBase):
    pass


# 创建SQLite数据库引擎
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False
    },
    echo=False
)


# 每次连接SQLite时，开启外键约束
@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(
    dbapi_connection,
    connection_record
):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# 创建数据库Session的工厂
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)


def get_db():
    """创建并自动关闭数据库Session"""

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def create_tables():
    """根据entities.py中的模型创建数据库表"""

    # 导入entities后，SQLAlchemy才能知道有哪些表
    import app.models.entities 

    Base.metadata.create_all(
        bind=engine
    )