"""Gmail via the official API. OAuth token stored as JSON, never pickle."""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from pathlib import Path

from ..core.errors import ConfigurationError, SourceError
from .base import RawEmail

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailSource:
    name = "gmail"

    def __init__(
        self, credentials_path: Path, token_path: Path, *, query: str = "is:unread"
    ) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.query = query
        self._service = None

    # -- auth -------------------------------------------------------------

    def authorize(self, *, interactive: bool = True):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif interactive:
            if not self.credentials_path.exists():
                raise ConfigurationError(
                    f"Gmail credentials not found at {self.credentials_path}. "
                    "Download an OAuth 'Desktop app' client from Google Cloud Console and save it there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            raise ConfigurationError("Gmail is not authorized. Run `email-agent auth gmail`.")
        self.token_path.write_text(creds.to_json())
        self.token_path.chmod(0o600)
        return creds

    def is_authorized(self) -> bool:
        return self.token_path.exists()

    def _svc(self):
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build(
                "gmail", "v1", credentials=self.authorize(interactive=False), cache_discovery=False
            )
        return self._service

    # -- fetch ------------------------------------------------------------

    def fetch(self, *, since: str | None, limit: int, skip=lambda _id: False) -> list[RawEmail]:
        """Return up to `limit` new messages. `skip` receives store-form ids ("gmail:<id>")."""
        q = self.query
        if since:
            q += " after:" + datetime.fromisoformat(since).strftime("%Y/%m/%d")
        try:
            svc = self._svc()
            listing = (
                svc.users()
                .messages()
                .list(userId="me", q=q, maxResults=min(limit * 3, 100))
                .execute()
            )
        except ConfigurationError:
            raise
        except Exception as e:  # noqa: BLE001
            raise SourceError(f"Gmail list failed: {e}") from e

        wanted = [m["id"] for m in listing.get("messages", []) if not skip(f"gmail:{m['id']}")]
        wanted = wanted[:limit]
        if not wanted:
            return []

        fetched: dict[str, dict] = {}

        def collect(request_id, response, exception):
            if exception is not None:
                log.warning("Gmail get %s failed: %s", request_id, exception)
            else:
                fetched[request_id] = response

        # One HTTP round trip for the whole batch (Gmail allows up to 100 per batch).
        batch = svc.new_batch_http_request(callback=collect)
        for mid in wanted:
            batch.add(svc.users().messages().get(userId="me", id=mid, format="raw"), request_id=mid)
        try:
            batch.execute()
        except Exception as e:  # noqa: BLE001
            raise SourceError(f"Gmail batch get failed: {e}") from e

        out: list[RawEmail] = []
        for mid in wanted:
            msg = fetched.get(mid)
            if not msg:
                continue
            ts = int(msg.get("internalDate", 0)) / 1000
            received = datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")
            if since and received < since:
                continue
            out.append(
                RawEmail(
                    source=self.name,
                    message_id=f"gmail:{mid}",
                    received_at=received,
                    raw=base64.urlsafe_b64decode(msg["raw"]),
                )
            )
        return out
