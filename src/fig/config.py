import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

@dataclass(frozen=True)
class Settings:
    database_url: str
    archive_dir: Path

    @classmethod
    def from_env(cls):
        load_dotenv(Path.cwd()/".env",override=False)
        return cls(os.getenv("FIG_DATABASE_URL", "sqlite:///data/fixture.sqlite3"),
                   Path(os.getenv("FIG_ARCHIVE_DIR", "data/archive")))
