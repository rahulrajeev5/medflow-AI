from functools import lru_cache
from typing import Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)

ALGORITHMS = ["RS256"]

COGNITO_ISSUER = (
    f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
    f"{settings.cognito_user_pool_id}"
)

COGNITO_JWKS_URL = f"{COGNITO_ISSUER}/.well-known/jwks.json"


@lru_cache(maxsize=1)
def get_cognito_jwks() -> dict[str, Any]:
    try:
        response = httpx.get(
            COGNITO_JWKS_URL,
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to retrieve Cognito signing keys.",
        ) from exc


def get_signing_key(token: str) -> dict[str, Any]:
    try:
        headers = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        ) from exc

    key_id = headers.get("kid")

    if not key_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain a key ID.",
        )

    jwks = get_cognito_jwks()

    for key in jwks.get("keys", []):
        if key.get("kid") == key_id:
            return key

    # Cognito can rotate signing keys.
    get_cognito_jwks.cache_clear()
    refreshed_jwks = get_cognito_jwks()

    for key in refreshed_jwks.get("keys", []):
        if key.get("kid") == key_id:
            return key

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unable to find the token signing key.",
    )


def verify_access_token(token: str) -> dict[str, Any]:
    signing_key = get_signing_key(token)

    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=ALGORITHMS,
            issuer=COGNITO_ISSUER,
            options={
                "verify_aud": False,
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
            },
        )

    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if claims.get("token_use") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="An access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if claims.get("client_id") != settings.cognito_client_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token was issued for a different application.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not claims.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain a user identifier.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return claims


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return verify_access_token(credentials.credentials)