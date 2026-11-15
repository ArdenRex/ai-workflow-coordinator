"""Run after rotating APP_SECRET_KEY (old value in APP_SECRET_KEY_PREVIOUS):
    python -m app.reencrypt
Then remove the old key from APP_SECRET_KEY_PREVIOUS."""
from app.credentials_service import CredentialService
from app.database import get_session_factory


def main() -> None:
    with get_session_factory()() as db:
        print(f"re-encrypted {CredentialService(db).reencrypt_all()} credential(s)")


if __name__ == "__main__":
    main()
