"""Application settings loaded from the process environment and optional .env file.

Usage:
    from lending_library.config import settings
    client_project = settings.firebase_project_id
"""

from pathlib import Path

from dotenv import load_dotenv
import os


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parent

load_dotenv(PROJECT_ROOT / ".env")


class Settings:
    """Runtime configuration for the lending library web application.

    Parameters are read from environment variables. Missing optional values
    use the defaults documented on each attribute.
    """

    def __init__(self) -> None:
        """Load environment values into typed attributes."""
        self.firebase_project_id = os.getenv("FIREBASE_PROJECT_ID", "")
        self.firebase_service_account = os.getenv("FIREBASE_SERVICE_ACCOUNT", "")
        self.firebase_service_account_json = os.getenv(
            "FIREBASE_SERVICE_ACCOUNT_JSON", ""
        )
        self.staff_password = os.getenv("STAFF_PASSWORD", "")
        self.google_books_api_key = os.getenv("GOOGLE_BOOKS_API_KEY", "")
        self.site_contact = os.getenv(
            "SITE_CONTACT", "https://library.exeter.edu/home"
        )
        self.open_library_user_agent = (
            f"ExeterLendingLibrary/0.1 ({self.site_contact})"
        )


settings = Settings()
