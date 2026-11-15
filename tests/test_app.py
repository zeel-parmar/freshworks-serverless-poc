"""
Unit tests for src/app.py.

DynamoDB is replaced with a fake (unittest.mock), so these tests need NO AWS
account, NO credentials and NO internet connection.

Run from the project root:
    python -m unittest discover -s tests -v
"""

import base64
import json
import os
import sys
import unittest
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

# Settings that Lambda would normally provide. Set them BEFORE importing app.
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
os.environ["TABLE_NAME"] = "test-SupportTickets"
os.environ["TICKET_TTL_DAYS"] = "7"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import app  # noqa: E402


def make_event(method, path, body=None, path_parameters=None, base64_encode=False):
    """Build a minimal API Gateway HTTP API (payload v2.0) event."""
    event = {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "requestContext": {"http": {"method": method, "path": path}},
        "isBase64Encoded": False,
    }
    if body is not None:
        if base64_encode:
            body = base64.b64encode(body.encode("utf-8")).decode("ascii")
            event["isBase64Encoded"] = True
        event["body"] = body
    if path_parameters:
        event["pathParameters"] = path_parameters
    return event


def post_ticket(payload):
    return make_event("POST", "/tickets", body=json.dumps(payload))


class AppTests(unittest.TestCase):
    def setUp(self):
        # Replace the real DynamoDB table with a fake for every test.
        self.fake_table = MagicMock()
        patcher = patch.object(app, "get_table", return_value=self.fake_table)
        patcher.start()
        self.addCleanup(patcher.stop)

    def body(self, response):
        return json.loads(response["body"])

    # ---- GET /health -------------------------------------------------------
    def test_health_returns_200_and_does_not_touch_database(self):
        response = app.lambda_handler(make_event("GET", "/health"), None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(self.body(response)["status"], "ok")
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.fake_table.put_item.assert_not_called()
        self.fake_table.get_item.assert_not_called()

    # ---- POST /tickets: success --------------------------------------------
    def test_create_ticket_success(self):
        response = app.lambda_handler(
            post_ticket(
                {
                    "subject": "Order delayed",
                    "description": "My order has not arrived yet.",
                    "customerEmail": "student@example.com",
                }
            ),
            None,
        )
        self.assertEqual(response["statusCode"], 201)
        body = self.body(response)
        self.assertEqual(body["status"], "OPEN")
        uuid.UUID(body["ticketId"])  # raises if it is not a valid UUID

        self.fake_table.put_item.assert_called_once()
        kwargs = self.fake_table.put_item.call_args.kwargs
        item = kwargs["Item"]
        self.assertEqual(item["ticketId"], body["ticketId"])
        self.assertEqual(item["subject"], "Order delayed")
        self.assertEqual(item["customerEmail"], "student@example.com")
        self.assertEqual(item["status"], "OPEN")
        self.assertIn("expiresAt", item)
        self.assertEqual(kwargs["ConditionExpression"], "attribute_not_exists(ticketId)")

        # Timestamp must be a UTC ISO-8601 string ending in Z.
        self.assertTrue(item["createdAt"].endswith("Z"))
        datetime.fromisoformat(item["createdAt"].replace("Z", "+00:00"))

    def test_create_ticket_without_optional_email(self):
        response = app.lambda_handler(post_ticket({"subject": "Hi", "description": "Body"}), None)
        self.assertEqual(response["statusCode"], 201)
        self.assertNotIn("customerEmail", self.fake_table.put_item.call_args.kwargs["Item"])

    def test_create_ticket_from_base64_body(self):
        event = make_event(
            "POST", "/tickets", body=json.dumps({"subject": "A", "description": "B"}), base64_encode=True
        )
        self.assertEqual(app.lambda_handler(event, None)["statusCode"], 201)

    # ---- POST /tickets: bad input ------------------------------------------
    def test_missing_subject_returns_400(self):
        response = app.lambda_handler(post_ticket({"description": "No subject"}), None)
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("subject", self.body(response)["message"])
        self.fake_table.put_item.assert_not_called()

    def test_missing_description_returns_400(self):
        response = app.lambda_handler(post_ticket({"subject": "No description"}), None)
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("description", self.body(response)["message"])
        self.fake_table.put_item.assert_not_called()

    def test_blank_subject_returns_400(self):
        response = app.lambda_handler(post_ticket({"subject": "   ", "description": "x"}), None)
        self.assertEqual(response["statusCode"], 400)

    def test_malformed_json_returns_400(self):
        event = make_event("POST", "/tickets", body="{not valid json")
        response = app.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("valid JSON", self.body(response)["message"])
        self.fake_table.put_item.assert_not_called()

    def test_missing_body_returns_400(self):
        response = app.lambda_handler(make_event("POST", "/tickets"), None)
        self.assertEqual(response["statusCode"], 400)

    def test_json_array_instead_of_object_returns_400(self):
        event = make_event("POST", "/tickets", body="[1, 2, 3]")
        self.assertEqual(app.lambda_handler(event, None)["statusCode"], 400)

    def test_invalid_email_returns_400(self):
        response = app.lambda_handler(
            post_ticket({"subject": "A", "description": "B", "customerEmail": "not-an-email"}), None
        )
        self.assertEqual(response["statusCode"], 400)

    def test_too_long_subject_returns_400(self):
        response = app.lambda_handler(post_ticket({"subject": "x" * 201, "description": "B"}), None)
        self.assertEqual(response["statusCode"], 400)

    # ---- DynamoDB failure ----------------------------------------------------
    def test_database_error_returns_generic_500(self):
        self.fake_table.put_item.side_effect = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "secret internal detail"}},
            "PutItem",
        )
        response = app.lambda_handler(post_ticket({"subject": "A", "description": "B"}), None)
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(self.body(response), {"message": "Internal server error."})
        # Nothing internal may leak to the client.
        self.assertNotIn("secret internal detail", response["body"])
        self.assertNotIn("ProvisionedThroughput", response["body"])

    def test_unexpected_error_returns_generic_500(self):
        self.fake_table.put_item.side_effect = RuntimeError("boom with /internal/path")
        response = app.lambda_handler(post_ticket({"subject": "A", "description": "B"}), None)
        self.assertEqual(response["statusCode"], 500)
        self.assertNotIn("boom", response["body"])

    def test_missing_table_name_returns_generic_500(self):
        with patch.object(app, "get_table", side_effect=KeyError("TABLE_NAME")):
            response = app.lambda_handler(post_ticket({"subject": "A", "description": "B"}), None)
        self.assertEqual(response["statusCode"], 500)
        self.assertNotIn("TABLE_NAME", response["body"])

    # ---- GET /tickets/{ticketId} ---------------------------------------------
    def test_get_ticket_found(self):
        ticket_id = str(uuid.uuid4())
        self.fake_table.get_item.return_value = {
            "Item": {
                "ticketId": ticket_id,
                "subject": "A",
                "description": "B",
                "status": "OPEN",
                "createdAt": "2026-01-01T00:00:00Z",
                "expiresAt": 1893456000,
            }
        }
        event = make_event("GET", f"/tickets/{ticket_id}", path_parameters={"ticketId": ticket_id})
        response = app.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        body = self.body(response)
        self.assertEqual(body["ticketId"], ticket_id)
        self.assertNotIn("expiresAt", body)

    def test_get_ticket_not_found(self):
        ticket_id = str(uuid.uuid4())
        self.fake_table.get_item.return_value = {}
        event = make_event("GET", f"/tickets/{ticket_id}", path_parameters={"ticketId": ticket_id})
        self.assertEqual(app.lambda_handler(event, None)["statusCode"], 404)

    def test_get_ticket_with_invalid_id_returns_400(self):
        event = make_event("GET", "/tickets/not-a-uuid", path_parameters={"ticketId": "not-a-uuid"})
        response = app.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)
        self.fake_table.get_item.assert_not_called()

    # ---- Unknown route ---------------------------------------------------------
    def test_unknown_route_returns_404(self):
        self.assertEqual(app.lambda_handler(make_event("GET", "/nope"), None)["statusCode"], 404)

    # ---- Privacy -------------------------------------------------------------------
    def test_ticket_text_is_not_logged(self):
        with self.assertLogs(level="INFO") as captured:
            app.lambda_handler(
                post_ticket({"subject": "SECRET-SUBJECT", "description": "SECRET-DESCRIPTION"}), None
            )
        logs = "\n".join(captured.output)
        self.assertNotIn("SECRET-SUBJECT", logs)
        self.assertNotIn("SECRET-DESCRIPTION", logs)


if __name__ == "__main__":
    unittest.main()
