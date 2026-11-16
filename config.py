"""Application configuration for local MarketPilot AI development."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


def _project_path(value: str, default: str) -> Path:
    path = Path(value or default).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str
    database_path: Path
    upload_dir: Path
    max_workflows_per_day: int
    max_image_bytes: int
    max_images_per_product: int
    allowed_image_extensions: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")


def get_settings() -> Settings:
    max_image_mb = int(os.getenv("MAX_IMAGE_MB", "5"))
    max_images = int(os.getenv("MAX_IMAGES_PER_PRODUCT", "5"))
    workflows = int(os.getenv("MAX_WORKFLOWS_PER_DAY", "20"))
    if min(max_image_mb, max_images, workflows) < 1:
        raise ValueError("Image and workflow limits must be positive integers")
    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        database_path=_project_path(os.getenv("DATABASE_PATH", "marketpilot.db"), "marketpilot.db"),
        upload_dir=_project_path(os.getenv("UPLOAD_DIR", "uploads/products"), "uploads/products"),
        max_workflows_per_day=workflows,
        max_image_bytes=max_image_mb * 1024 * 1024,
        max_images_per_product=max_images,
    )

