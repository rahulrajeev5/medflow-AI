import json
import signal
import sys
import time
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.api.documents import process_document
from app.core.config import get_settings


settings = get_settings()
running = True


def stop_worker(signum, frame) -> None:
    global running
    print("\nStopping MedFlow worker...")
    running = False


def get_sqs_client():
    session = boto3.Session(
        profile_name=settings.aws_profile,
        region_name=settings.aws_region,
    )
    return session.client("sqs")


def handle_message(sqs_client, message: dict) -> None:
    receipt_handle = message["ReceiptHandle"]
    message_id = message.get("MessageId", "unknown")

    try:
        body = json.loads(message["Body"])

        if body.get("event_type") != "DOCUMENT_UPLOADED":
            raise ValueError(
                f"Unsupported event type: {body.get('event_type')}"
            )

        raw_document_id = body.get("document_id")

        if not raw_document_id:
            raise ValueError("Message does not contain document_id.")

        document_id = uuid.UUID(raw_document_id)

        print(
            f"\nProcessing message {message_id}"
            f"\nDocument ID: {document_id}"
        )

        process_document(document_id)

        # process_document currently catches its own processing errors.
        # We verify success before deleting the SQS message.
        from app.db.session import SessionLocal
        from app.models.document import Document, DocumentStatus

        with SessionLocal() as db:
            document = db.get(Document, document_id)

            if not document:
                raise RuntimeError(
                    f"Document {document_id} does not exist."
                )

            if document.status != DocumentStatus.completed:
                raise RuntimeError(
                    document.error_message
                    or f"Document finished with status {document.status}."
                )

        sqs_client.delete_message(
            QueueUrl=settings.sqs_queue_url,
            ReceiptHandle=receipt_handle,
        )

        print(
            f"Completed document {document_id}. "
            "SQS message deleted."
        )

    except json.JSONDecodeError as exc:
        print(
            f"Message {message_id} contains invalid JSON: {exc}"
        )
        # Leave the message in the queue so it can be retried and
        # eventually transferred to the dead-letter queue.

    except (ValueError, RuntimeError, ClientError, BotoCoreError) as exc:
        print(
            f"Message {message_id} failed: {exc}"
        )
        # Do not delete failed messages. SQS will retry them after
        # the visibility timeout.


def run_worker() -> None:
    sqs_client = get_sqs_client()

    print("MedFlow SQS worker started.")
    print(f"Queue: {settings.sqs_queue_url}")
    print("Press Ctrl+C to stop.")

    while running:
        try:
            response = sqs_client.receive_message(
                QueueUrl=settings.sqs_queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=900,
                AttributeNames=["ApproximateReceiveCount"],
            )

            messages = response.get("Messages", [])

            for message in messages:
                receive_count = message.get(
                    "Attributes",
                    {},
                ).get(
                    "ApproximateReceiveCount",
                    "1",
                )

                print(
                    f"\nReceive attempt: {receive_count}"
                )

                handle_message(
                    sqs_client=sqs_client,
                    message=message,
                )

        except (ClientError, BotoCoreError) as exc:
            print(f"AWS error: {exc}")
            time.sleep(5)

        except Exception as exc:
            print(f"Unexpected worker error: {exc}")
            time.sleep(5)

    print("Worker stopped.")


if __name__ == "__main__":
    signal.signal(
        signal.SIGINT,
        stop_worker,
    )

    if hasattr(signal, "SIGTERM"):
        signal.signal(
            signal.SIGTERM,
            stop_worker,
        )

    try:
        run_worker()
    except KeyboardInterrupt:
        sys.exit(0)