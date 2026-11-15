"""
Freshworks-inspired support-ticket API.

Request path:  Client -> API Gateway HTTP API -> this Lambda function -> DynamoDB

Routes
------
GET  /health              -> simple "I am alive" answer, never touches DynamoDB
POST /tickets             -> validate JSON, store a ticket, return its ID
GET  /tickets/{ticketId}  -> read one ticket back (optional extra)

Beginner notes
--------------
* Everything outside `lambda_handler` runs ONCE per execution environment
  (the "INIT" phase). That is where a cold start spends its time, so keep the
  top of this file small.
* `lambda_handler` runs once per request (the "INVOKE" phase).
* We never log ticket text (subject, description, email). Only IDs and status
  codes go to CloudWatch Logs.
"""

import base64
import binascii
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- INIT phase: runs once per execution environment ------------------------
# DYNAMODB_ENDPOINT_URL is empty when deployed to AWS. It is only set when you
# test against a local DynamoDB container (see README, "Local API testing").
dynamodb = boto3.resource(
    "dynamodb", endpoint_url=os.environ.get("DYNAMODB_ENDPOINT_URL") or None
)

MAX_SUBJECT_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000
MAX_EMAIL_LENGTH = 254
MAX_BODY_CHARACTERS = 10_000
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ValidationError(Exception):
    """Raised when the client sent something we cannot accept (HTTP 400)."""


def get_table():
    """Return the DynamoDB table object. The table name comes from the environment."""
    return dynamodb.Table(os.environ["TABLE_NAME"])


def _json_default(value):
    """DynamoDB returns numbers as Decimal; json.dumps cannot handle them."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def _response(status_code, body):
    """Build the response format that API Gateway HTTP APIs expect."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_json_default),
    }


def _parse_json_body(event):
    """Turn the raw request body into a Python dict, or raise ValidationError."""
    raw = event.get("body")
    if raw is None or raw == "":
        raise ValidationError("Request body is required.")

    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            raise ValidationError("Request body could not be decoded.")

    if len(raw) > MAX_BODY_CHARACTERS:
        raise ValidationError("Request body is too large.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise ValidationError("Request body must be valid JSON.")

    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    return payload


def _required_text(payload, field, max_length):
    value = payload.get(field)
    if value is None:
        raise ValidationError(f"'{field}' is required.")
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"'{field}' must be a non-empty string.")
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(f"'{field}' must be at most {max_length} characters.")
    return value


def _validate_ticket(payload):
    """Check the payload and return only the fields we store."""
    ticket = {
        "subject": _required_text(payload, "subject", MAX_SUBJECT_LENGTH),
        "description": _required_text(payload, "description", MAX_DESCRIPTION_LENGTH),
    }
    email = payload.get("customerEmail")
    if email is not None:
        if not isinstance(email, str) or len(email) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.match(email):
            raise ValidationError("'customerEmail' must be a valid email address.")
        ticket["customerEmail"] = email
    return ticket


def create_ticket(event):
    ticket = _validate_ticket(_parse_json_body(event))

    ticket_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    ttl_days = int(os.environ.get("TICKET_TTL_DAYS", "7"))

    item = {
        "ticketId": ticket_id,
        "status": "OPEN",
        "createdAt": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        # DynamoDB TTL deletes the item automatically (free) after this time.
        "expiresAt": int(time.time()) + ttl_days * 24 * 60 * 60,
        **ticket,
    }

    # The condition makes the write fail instead of overwriting an existing ID.
    get_table().put_item(Item=item, ConditionExpression="attribute_not_exists(ticketId)")

    logger.info("ticket created ticketId=%s", ticket_id)
    return _response(201, {"ticketId": ticket_id, "status": "OPEN"})


def get_ticket(event):
    ticket_id = (event.get("pathParameters") or {}).get("ticketId", "")
    try:
        uuid.UUID(ticket_id)
    except (ValueError, AttributeError, TypeError):
        raise ValidationError("'ticketId' must be a valid UUID.")

    result = get_table().get_item(Key={"ticketId": ticket_id})
    item = result.get("Item")
    if not item:
        return _response(404, {"message": "Ticket not found."})

    item.pop("expiresAt", None)
    return _response(200, item)


def _method_and_path(event):
    http = (event.get("requestContext") or {}).get("http") or {}
    method = (http.get("method") or "").upper()
    path = http.get("path") or event.get("rawPath") or ""
    return method, path


def lambda_handler(event, context):
    """Entry point. API Gateway calls this once per HTTP request."""
    method, path = _method_and_path(event)

    try:
        if method == "GET" and path.rstrip("/").endswith("/health"):
            response = _response(200, {"status": "ok", "service": "freshworks-serverless-poc"})
        elif method == "POST" and path.rstrip("/").endswith("/tickets"):
            response = create_ticket(event)
        elif method == "GET" and "/tickets/" in path:
            response = get_ticket(event)
        else:
            response = _response(404, {"message": "Route not found."})
    except ValidationError as error:
        # Our own messages are safe to show to the client.
        response = _response(400, {"message": str(error)})
    except (ClientError, BotoCoreError) as error:
        # Never send AWS error details to the client; log only the error code.
        code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
        logger.error("database error code=%s", code)
        response = _response(500, {"message": "Internal server error."})
    except Exception:  # noqa: BLE001 - last-resort safety net
        logger.exception("unexpected error")
        response = _response(500, {"message": "Internal server error."})

    logger.info("request method=%s path=%s status=%s", method, path, response["statusCode"])
    return response
