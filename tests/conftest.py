"""Pytest fixtures for bot template tests."""

from pathlib import Path
import pytest
from PIL import Image

from app.database.connection import Database
from app.database.repository import DatabaseRepository


@pytest.fixture
def sample_jpeg(tmp_path: Path) -> Path:
    img_path = tmp_path / 'sample.jpg'
    img = Image.new('RGB', (200, 200), color=(255, 0, 100))
    img.save(img_path, format='JPEG')
    return img_path


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    img_path = tmp_path / 'sample.png'
    img = Image.new('RGBA', (200, 200), color=(0, 150, 255, 180))
    img.save(img_path, format='PNG')
    return img_path


@pytest.fixture
async def test_db(tmp_path: Path):
    db_file = tmp_path / 'test.db'
    db = Database(db_file)
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
async def test_repo(test_db: Database) -> DatabaseRepository:
    return DatabaseRepository(test_db)
