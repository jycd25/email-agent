"""Outlook / Microsoft 365 via the Graph API.

Auth is MSAL's device-code flow (works for school and work accounts without a
redirect URI); the token cache is stored as JSON with mode 0600, like Gmail.
Fetching mirrors the Gmail source: one list call, then one JSON batch for the
MIME bodies.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from ..core.errors import ConfigurationError, SourceError
from .base import RawEmail

log = logging.getLogger(__name__)

SCOPES = ["Mail.Read"]
GRAPH = "https://graph.microsoft.com/v1.0"
BATCH_LIMIT = 20  # Graph caps JSON batches at 20 requests


def _graph_time(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")


class OutlookSource:
    name = "outlook"

    def __init__(
        self,
        token_path: Path,
        *,
        client_id: str | None,
        tenant: str = "common",
        unread_only: bool = True,
    ) -> None:
        self.token_path = token_path
        self.client_id = client_id
        self.tenant = tenant
        self.unread_only = unread_only
        self._session = None  # requests.Session with auth header set, or a test double

    # -- auth -------------------------------------------------------------

    def _app(self):
        import msal

        if not self.client_id:
            raise ConfigurationError(
                "EMAIL_AGENT_OUTLOOK_CLIENT_ID is not set. Register a public client app in "
                "Microsoft Entra and put its Application (client) ID in that variable; "
                "see docs/outlook-setup.md."
            )
        cache = msal.SerializableTokenCache()
        if self.token_path.exists():
            cache.deserialize(self.token_path.read_text())
        app = msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant}",
            token_cache=cache,
        )
        return app, cache

    def _save(self, cache) -> None:
        if cache.has_state_changed:
            self.token_path.write_text(cache.serialize())
            self.token_path.chmod(0o600)

    def authorize(self, *, interactive: bool = True, prompt=print) -> str:
        """Return a valid access token. Interactive mode runs the device-code flow
        and prints the URL and code via `prompt`."""
        app, cache = self._app()
        accounts = app.get_accounts()
        result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
        if not result and interactive:
            flow = app.initiate_device_flow(scopes=SCOPES)
            if "user_code" not in flow:
                raise ConfigurationError(
                    f"Could not start device sign-in: {flow.get('error_description', flow)}"
                )
            prompt(flow["message"])
            result = app.acquire_token_by_device_flow(flow)
        if not result:
            raise ConfigurationError("Outlook is not authorized. Run `email-agent auth outlook`.")
        if "access_token" not in result:
            raise ConfigurationError(
                f"Outlook sign-in failed: {result.get('error_description') or result.get('error')}"
            )
        self._save(cache)
        return result["access_token"]

    def is_authorized(self) -> bool:
        return bool(self.client_id) and self.token_path.exists()

    def _http(self):
        """A requests.Session carrying a fresh bearer token."""
        if self._session is None:
            import requests

            self._session = requests.Session()
        # Cheap: MSAL serves from cache until the token is near expiry.
        token = self.authorize(interactive=False)
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                # Ids that survive a move between folders, so a filed message is not re-queued.
                "Prefer": 'IdType="ImmutableId"',
            }
        )
        return self._session

    # -- fetch ------------------------------------------------------------

    def fetch(self, *, since: str | None, limit: int, skip=lambda _id: False) -> list[RawEmail]:
        """Return up to `limit` new messages. `skip` receives store-form ids ("outlook:<id>")."""
        filters = []
        if self.unread_only:
            filters.append("isRead eq false")
        if since:
            filters.append(f"receivedDateTime ge {_graph_time(since)}")
        params = {
            "$select": "id,receivedDateTime",
            "$top": str(min(limit * 3, 100)),
        }
        if filters:
            params["$filter"] = " and ".join(filters)
        try:
            http = self._http()
            r = http.get(f"{GRAPH}/me/messages", params=params, timeout=30)
            r.raise_for_status()
            listing = r.json()
        except ConfigurationError:
            raise
        except Exception as e:  # noqa: BLE001
            raise SourceError(f"Outlook list failed: {e}") from e

        meta = {
            m["id"]: m.get("receivedDateTime")
            for m in listing.get("value", [])
            if not skip(f"outlook:{m['id']}")
        }
        wanted = list(meta)[:limit]
        if not wanted:
            return []

        out: list[RawEmail] = []
        for start in range(0, len(wanted), BATCH_LIMIT):
            chunk = wanted[start : start + BATCH_LIMIT]
            for mid, raw in self._batch_mime(http, chunk).items():
                received = self._iso(meta.get(mid))
                if since and received < since:
                    continue
                out.append(
                    RawEmail(
                        source=self.name,
                        message_id=f"outlook:{mid}",
                        received_at=received,
                        raw=raw,
                    )
                )
        return out

    @staticmethod
    def _iso(graph_time: str | None) -> str:
        if not graph_time:
            return datetime.now(UTC).isoformat(timespec="seconds")
        dt = datetime.fromisoformat(graph_time.replace("Z", "+00:00"))
        return dt.astimezone(UTC).isoformat(timespec="seconds")

    @staticmethod
    def _batch_mime(http, ids: list[str]) -> dict[str, bytes]:
        """One HTTP round trip for up to 20 MIME bodies via Graph's JSON batch endpoint."""
        body = {
            "requests": [
                {"id": mid, "method": "GET", "url": f"/me/messages/{mid}/$value"} for mid in ids
            ]
        }
        try:
            r = http.post(f"{GRAPH}/$batch", json=body, timeout=60)
            r.raise_for_status()
            responses = r.json().get("responses", [])
        except Exception as e:  # noqa: BLE001
            raise SourceError(f"Outlook batch get failed: {e}") from e

        out: dict[str, bytes] = {}
        for resp in responses:
            mid, status, payload = resp.get("id"), resp.get("status"), resp.get("body")
            if status != 200 or payload is None:
                log.warning("Outlook get %s failed: %s %s", mid, status, payload)
                continue
            out[mid] = OutlookSource._decode_body(payload)
        return out

    @staticmethod
    def _decode_body(payload) -> bytes:
        # Graph base64-encodes non-JSON bodies inside a batch response; be tolerant
        # of the plain-text form too.
        if isinstance(payload, dict | list):
            return json.dumps(payload).encode()
        text = str(payload)
        try:
            return base64.b64decode(text, validate=True)
        except Exception:  # noqa: BLE001
            return text.encode()
