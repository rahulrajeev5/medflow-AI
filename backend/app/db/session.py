import json
import os
from functools import lru_cache
from typing import Generator

import boto3
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


settings = get_settings()


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=1)
def get_database_url() -> str | URL:
    """
    Use Secrets Manager inside Lambda.

    Use DATABASE_URL for local FastAPI development.
    """
    secret_name = settings.db_secret_name
    is_lambda = bool(
        os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    )

    if is_lambda and secret_name:
        client = boto3.client(
            "secretsmanager",
            region_name=settings.aws_region,
        )

        response = client.get_secret_value(
            SecretId=secret_name,
        )

        secret_string = response.get("SecretString")

        if not secret_string:
            raise RuntimeError(
                "The RDS secret does not contain SecretString."
            )

        secret = json.loads(secret_string)

        required_fields = {
            "username",
            "password",
            "host",
            "port",
        }

        missing_fields = required_fields - secret.keys()

        if missing_fields:
            raise RuntimeError(
                "The RDS secret is missing fields: "
                + ", ".join(sorted(missing_fields))
            )

        database_name = (
            secret.get("dbname")
            or secret.get("database")
            or "medflow"
        )

        return URL.create(
            drivername="postgresql+psycopg",
            username=secret["username"],
            password=secret["password"],
            host=secret["host"],
            port=int(secret["port"]),
            database=database_name,
            query={
                "sslmode": "require",
            },
        )

    if settings.database_url:
        return settings.database_url

    raise RuntimeError(
        "No database configuration found. "
        "Set DATABASE_URL locally or DB_SECRET_NAME in Lambda."
    )


engine = create_engine(
    get_database_url(),
    pool_pre_ping=True,
    pool_recycle=300,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()