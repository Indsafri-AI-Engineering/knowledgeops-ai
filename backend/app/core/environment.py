from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_environment(env_file: Path | None = None) -> None:
    load_dotenv(
        dotenv_path=env_file or PROJECT_ROOT / ".env",
        override=False,
    )
