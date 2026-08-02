import boto3
from botocore.exceptions import BotoCoreError, ClientError


AWS_PROFILE = "medflow"
AWS_REGION = "eu-central-1"
MODEL_ID = "eu.amazon.nova-lite-v1:0"


def main() -> None:
    session = boto3.Session(
        profile_name=AWS_PROFILE,
        region_name=AWS_REGION,
    )

    client = session.client("bedrock-runtime")

    try:
        response = client.converse(
            modelId=MODEL_ID,
            system=[
                {
                    "text": (
                        "You are a document-processing assistant. "
                        "Do not provide medical advice."
                    )
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": (
                                "Summarize this in one sentence:\n\n"
                                "The patient was referred to cardiology "
                                "because of recurring chest discomfort."
                            )
                        }
                    ],
                }
            ],
            inferenceConfig={
                "maxTokens": 200,
                "temperature": 0.1,
                "topP": 0.9,
            },
        )

        result = response["output"]["message"]["content"][0]["text"]

        print("\nBedrock response:\n")
        print(result)

        print("\nUsage:\n")
        print(response.get("usage", {}))

    except (ClientError, BotoCoreError) as exc:
        print(f"\nBedrock request failed:\n{exc}")
        raise


if __name__ == "__main__":
    main()