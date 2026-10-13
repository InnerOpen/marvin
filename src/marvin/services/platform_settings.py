"""Read/write access to the keyed `platform_settings` table."""

from sqlalchemy.orm import Session

from marvin.db.models.platform.platform_settings import PlatformSettingsModel

SUBMISSION_PROTECTION_KEY = "submission_protection"


class PlatformSettingsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, key: str) -> dict | None:
        row = self.session.query(PlatformSettingsModel).filter(PlatformSettingsModel.key == key).first()
        return row.value_json if row else None

    def set(self, key: str, value: dict) -> dict:
        row = self.session.query(PlatformSettingsModel).filter(PlatformSettingsModel.key == key).first()
        if row is None:
            row = PlatformSettingsModel(session=self.session, key=key, value_json=value)
            self.session.add(row)
        else:
            row.value_json = value
        self.session.commit()
        return value
