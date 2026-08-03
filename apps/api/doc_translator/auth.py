from datetime import datetime, timedelta, timezone
import hashlib
import logging

import jwt
import redis
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from doc_translator.core.config import get_settings
from doc_translator.db import get_db
from doc_translator.models import User
from doc_translator.queueing import get_redis_client


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
logger = logging.getLogger(__name__)
_DUMMY_PASSWORD_HASH = pwd_context.hash("not-a-real-user-password")
_LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300
_LOGIN_EMAIL_FAILURE_LIMIT = 5
_LOGIN_IP_FAILURE_LIMIT = 30


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user: User) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": user.id,
        "role": user.role.value,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm="HS256")


def authenticate_user(session: Session, email: str, password: str) -> User | None:
    user = session.query(User).filter(User.email == email.lower()).first()
    password_matches = verify_password(password, user.password_hash if user is not None else _DUMMY_PASSWORD_HASH)
    if user is None or not user.is_active or not password_matches:
        return None
    return user


def _login_failure_key(scope: str, value: str) -> str:
    digest = hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()
    return f"auth:login-failures:{scope}:{digest}"


def is_login_rate_limited(email: str, ip_address: str | None) -> bool:
    email_key = _login_failure_key("email", email)
    ip_key = _login_failure_key("ip", ip_address or "unknown")
    try:
        email_failures, ip_failures = get_redis_client().mget(email_key, ip_key)
    except redis.RedisError:
        logger.exception("Could not inspect login rate limit")
        return False
    return int(email_failures or 0) >= _LOGIN_EMAIL_FAILURE_LIMIT or int(ip_failures or 0) >= _LOGIN_IP_FAILURE_LIMIT


def record_login_failure(email: str, ip_address: str | None) -> bool:
    email_key = _login_failure_key("email", email)
    ip_key = _login_failure_key("ip", ip_address or "unknown")
    try:
        pipeline = get_redis_client().pipeline(transaction=True)
        pipeline.incr(email_key)
        pipeline.expire(email_key, _LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        pipeline.incr(ip_key)
        pipeline.expire(ip_key, _LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        email_failures, _, ip_failures, _ = pipeline.execute()
    except redis.RedisError:
        logger.exception("Could not record login rate limit")
        return False
    return email_failures >= _LOGIN_EMAIL_FAILURE_LIMIT or ip_failures >= _LOGIN_IP_FAILURE_LIMIT


def clear_login_failures(email: str) -> None:
    try:
        get_redis_client().delete(_login_failure_key("email", email))
    except redis.RedisError:
        logger.exception("Could not clear login rate limit")


def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_db)) -> User:
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=["HS256"])
        user_id = payload.get("sub")
    except jwt.PyJWTError as exc:
        raise credentials_exception from exc
    if not user_id:
        raise credentials_exception

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role.value != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
