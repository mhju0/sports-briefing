from __future__ import annotations

import io
import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from sports_briefing.football_data import (
    MAX_RESPONSE_BYTES,
    ProviderError,
    fetch_arsenal_matches,
)


def http_response(body: bytes) -> io.BytesIO:
    response = io.BytesIO(body)
    response.status = 200
    return response


class HttpTransportTests(unittest.TestCase):
    @patch("sports_briefing.football_data.urlopen")
    def test_request_uses_official_team_endpoint_and_header_auth(self, open_url) -> None:
        body = b'{"resultSet":{"count":0},"matches":[]}'
        open_url.return_value = http_response(body)

        response = fetch_arsenal_matches(
            "synthetic-test-token", "2026-09-01", "2026-10-01", timeout=3.5
        )

        request = open_url.call_args.args[0]
        url = urlsplit(request.full_url)
        self.assertEqual((url.scheme, url.netloc, url.path), (
            "https", "api.football-data.org", "/v4/teams/57/matches"
        ))
        self.assertEqual(parse_qs(url.query), {
            "dateFrom": ["2026-09-01"], "dateTo": ["2026-10-01"], "limit": ["500"]
        })
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-auth-token"], "synthetic-test-token")
        self.assertNotIn("synthetic-test-token", request.full_url)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(open_url.call_args.kwargs["timeout"], 3.5)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.payload, json.loads(body))
        self.assertEqual(response.body, body.decode())

    @patch("sports_briefing.football_data.urlopen")
    def test_http_access_quota_and_server_errors_preserve_status(self, open_url) -> None:
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                open_url.side_effect = HTTPError(
                    "https://api.football-data.org/v4/teams/57/matches",
                    status, "Synthetic failure", {}, io.BytesIO(b'{"message":"unavailable"}')
                )
                with self.assertRaises(ProviderError) as raised:
                    fetch_arsenal_matches("test-token", "2026-09-01", "2026-10-01")
                self.assertEqual(raised.exception.status, status)
                self.assertIn("unavailable", raised.exception.body)

    @patch("sports_briefing.football_data.urlopen")
    def test_network_errors_have_a_clear_provider_boundary(self, open_url) -> None:
        for failure in (URLError("synthetic DNS failure"), TimeoutError("synthetic timeout")):
            with self.subTest(failure=type(failure).__name__):
                open_url.side_effect = failure
                with self.assertRaises(ProviderError):
                    fetch_arsenal_matches("test-token", "2026-09-01", "2026-10-01")

    @patch("sports_briefing.football_data.urlopen")
    def test_invalid_json_or_non_object_response_is_rejected(self, open_url) -> None:
        for body in (b"<html>outage</html>", b"[]", b"null", b"\xff"):
            with self.subTest(body=body):
                open_url.return_value = http_response(body)
                with self.assertRaises(ProviderError):
                    fetch_arsenal_matches("test-token", "2026-09-01", "2026-10-01")

    @patch("sports_briefing.football_data.urlopen")
    def test_oversized_response_is_rejected_with_bounded_diagnostics(self, open_url) -> None:
        open_url.return_value = http_response(b"x" * (MAX_RESPONSE_BYTES + 1))
        with self.assertRaises(ProviderError) as raised:
            fetch_arsenal_matches("test-token", "2026-09-01", "2026-10-01")
        self.assertLessEqual(len(raised.exception.body.encode()), MAX_RESPONSE_BYTES)

    @patch("sports_briefing.football_data.urlopen")
    def test_http_error_body_is_bounded(self, open_url) -> None:
        open_url.side_effect = HTTPError(
            "https://api.football-data.org/v4/teams/57/matches",
            503, "Synthetic failure", {}, io.BytesIO(b"x" * (MAX_RESPONSE_BYTES + 1))
        )
        with self.assertRaises(ProviderError) as raised:
            fetch_arsenal_matches("test-token", "2026-09-01", "2026-10-01")
        self.assertLessEqual(len(raised.exception.body.encode()), MAX_RESPONSE_BYTES)


if __name__ == "__main__":
    unittest.main()
