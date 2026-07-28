from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from .config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        await conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'cv_version' AND column_name = 'parent_version_id'
                ) THEN
                    ALTER TABLE cv_version ADD COLUMN parent_version_id INTEGER;
                END IF;
            END $$;
        """))

        await conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'user_cv' AND column_name = 'current_version_id'
                ) THEN
                    ALTER TABLE user_cv ADD COLUMN current_version_id INTEGER;
                END IF;
            END $$;
        """))

        await conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'user_cv_current_version_id_fkey' AND table_name = 'user_cv'
                ) THEN
                    ALTER TABLE user_cv
                        ADD CONSTRAINT user_cv_current_version_id_fkey
                        FOREIGN KEY (current_version_id) REFERENCES cv_version(id);
                END IF;
            END $$;
        """))

        await conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'cv_version_parent_version_id_fkey' AND table_name = 'cv_version'
                ) THEN
                    ALTER TABLE cv_version
                        ADD CONSTRAINT cv_version_parent_version_id_fkey
                        FOREIGN KEY (parent_version_id) REFERENCES cv_version(id);
                END IF;
            END $$;
        """))
