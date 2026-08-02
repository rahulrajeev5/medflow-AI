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

document_id = str(uuid.uuid4())

response = sqs_client.send_message(
    QueueUrl=settings.sqs_queue_url,
    MessageBody=json.dumps(
        {
            "event_type": "DOCUMENT_UPLOADED",
            "document_id": document_id,
        }
    ),
)

print("SQS message sent successfully")
print("Document ID:", document_id)
print("Message ID:", response["MessageId"])