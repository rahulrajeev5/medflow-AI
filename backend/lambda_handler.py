import json
import logging
import uuid

from app.processor import process_document

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context: object) -> dict:
    failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        message_id = record["messageId"]

        try:
            body = json.loads(record["body"])

            if body.get("event_type") != "DOCUMENT_UPLOADED":
                raise ValueError(
                    f"Unsupported event type: {body.get('event_type')}"
                )

            document_id = uuid.UUID(body["document_id"])

            logger.info(
                "Processing document %s from message %s",
                document_id,
                message_id,
            )

            process_document(document_id)

        except Exception:
            logger.exception(
                "Failed to process SQS message %s",
                message_id,
            )

            failures.append(
                {
                    "itemIdentifier": message_id,
                }
            )

    return {
        "batchItemFailures": failures,
    }