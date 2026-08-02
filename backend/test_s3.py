from pathlib import Path

import boto3

from app.core.config import get_settings


settings = get_settings()

session = boto3.Session(
    profile_name=settings.aws_profile,
    region_name=settings.aws_region,
)

s3_client = session.client("s3")

test_file = Path("s3-test.txt")
test_file.write_text(
    "MedFlow S3 connection works.",
    encoding="utf-8",
)

s3_client.upload_file(
    str(test_file),
    settings.s3_bucket_name,
    "tests/s3-test.txt",
)

print("S3 upload successful.")

test_file.unlink()