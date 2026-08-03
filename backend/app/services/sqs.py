import json
import os
import uuid

import boto3

from app.core.config import get_settings

settings = get_settings()


def get_sqs_client():
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return boto3.client(
            "sqs",
            region_name=settings.aws_region,
        )

    session = boto3.Session(
        profile_name=settings.aws_profile,
        region_name=settings.aws_region,
    )

    return session.client("sqs")


def send_processing_message(
    document_id: uuid.UUID,
) -> str:
    sqs_client = get_sqs_client()

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