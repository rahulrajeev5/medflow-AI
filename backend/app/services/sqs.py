import json
import uuid

import boto3

from app.core.config import get_settings

settings = get_settings()


session = boto3.Session(
    profile_name=settings.aws_profile,
    region_name=settings.aws_region,
)

sqs_client = session.client("sqs")


def send_processing_message(document_id: uuid.UUID):
    response = sqs_client.send_message(
        QueueUrl=settings.sqs_queue_url,
        MessageBody=json.dumps(
            {
                "event_type": "DOCUMENT_UPLOADED",
                "document_id": str(document_id),
            }
        ),
    )

    return response["MessageId"]