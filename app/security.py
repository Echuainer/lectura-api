"""Authentication with the api-colegio-smart session (same JWT, same cookie) and role checks.

Mirrors api-colegio-smart: JwtService (HMAC-SHA, issuer and audience required), JwtAuthFilter (rejects tokens issued
before the last password change) and RoleGuard (role per endpoint, data scoped to the token's institution).
"""
import logging
import secrets
import time
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app import db
from app.settings import settings

# com.educa.api.security.InstitutionRole
DOCENTE, INSPECTOR, ENCARGADO_CONVIVENCIA, DUPLA_PSICOSOCIAL, DIRECTIVO, EQUIPO_PIE, ESTUDIANTE, APODERADO = range(1, 9)
STAFF = (DOCENTE, DIRECTIVO, EQUIPO_PIE)
NEVER_CHANGED = 0
# Module key in api-colegio-smart (permissions / plan_type_permissions), embedded in the JWT at login
PERMISSION = "lectura"

log = logging.getLogger("lectura.auth")



@dataclass(frozen=True)
class AuthContext:
    user_id: int
    email: str
    institution_id: int
    role_id: int | None
    teacher_id: int | None = None
    platform_role: str | None = None
    permissions: dict = field(default_factory=dict)


class _StampCache:
    """password_changed_at per user, 60 s like UserSecurityStampCache."""

    def __init__(self, ttl=60.0, size=10_000):
        self.ttl, self.size, self._data = ttl, size, {}

    def get(self, user_id: int) -> int | None:
        hit = self._data.get(user_id)
        if hit and time.monotonic() - hit[1] < self.ttl:
            return hit[0]
        with db.engine.connect() as conn:
            row = conn.execute(select(db.cs_users.c.password_changed_at).where(db.cs_users.c.id == user_id)).first()
        stamp = None if row is None else (int(row[0].timestamp()) if row[0] else NEVER_CHANGED)
        if len(self._data) >= self.size:
            self._data.clear()
        self._data[user_id] = (stamp, time.monotonic())
        return stamp

    def clear(self):
        self._data.clear()


stamp_cache = _StampCache()


def _unauthorized(detail="No autorizado"):
    return HTTPException(status_code=401, detail=detail)


def decode_token(token: str) -> dict:
    if len(settings.jwt_secret.encode()) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters (same value as api-colegio-smart)")
    try:
        # jjwt's signWith(key) picks the algorithm from the key length: HS512 for a 64+ byte secret
        return jwt.decode(token, settings.jwt_secret.encode(), algorithms=["HS256", "HS384", "HS512"],
                          issuer=settings.jwt_issuer, audience=settings.jwt_audience,
                          options={"require": ["exp", "iss", "aud"]})
    except jwt.PyJWTError as e:
        # like JwtAuthFilter: the reason, never the token
        log.warning("[AUTH] invalid token: %s: %s", type(e).__name__, e)
        raise _unauthorized() from e


def _is_stale(claims: dict) -> bool:
    user_id = claims.get("userId")
    if user_id is None:
        return False
    db_stamp = stamp_cache.get(int(user_id))
    if db_stamp is None:
        return True  # user deleted
    if db_stamp == NEVER_CHANGED:
        return False
    token_stamp = claims.get("passwordChangedAt")
    return token_stamp is None or int(token_stamp) < db_stamp


def current_user(request: Request) -> AuthContext:
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else None
    if not token:
        log.warning("[AUTH] no auth cookie | %s %s | cookies=%s", request.method, request.url.path,
                    sorted(request.cookies))
        raise _unauthorized()
    claims = decode_token(token)
    if claims.get("mustChangePassword") or claims.get("enabled") is False or _is_stale(claims):
        log.warning("[AUTH] rejected | userId=%s mustChangePassword=%s enabled=%s stale=%s", claims.get("userId"),
                    claims.get("mustChangePassword"), claims.get("enabled"), _is_stale(claims))
        raise _unauthorized()
    if claims.get("institutionId") is None or claims.get("userId") is None:
        raise HTTPException(status_code=403, detail="El usuario no pertenece a una institución")
    return AuthContext(
        user_id=int(claims["userId"]), email=claims.get("sub", ""), institution_id=int(claims["institutionId"]),
        role_id=claims.get("institutionRoleId"), teacher_id=claims.get("teacherId"),
        platform_role=claims.get("platformRole"), permissions=claims.get("permissions") or {})


def require_role(*roles: int):
    """Dependency: the user's plan includes the module (permission `lectura`, Admin bypasses it, as in the
    platform) and they have one of the institution roles (RoleGuard.requireRole)."""

    def dependency(ctx: AuthContext = Depends(current_user)) -> AuthContext:
        if ctx.platform_role != "Admin" and ctx.permissions.get(PERMISSION) is not True:
            raise HTTPException(status_code=403, detail="Su plan no incluye Fluidez Lectora")
        if ctx.role_id not in roles:
            raise HTTPException(status_code=403, detail="No tiene permiso para esta acción")
        return ctx

    return dependency


staff = require_role(*STAFF)
directors = require_role(DIRECTIVO)


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie, like CookieCsrfTokenRepository in api-colegio-smart: every write must echo the
    XSRF-TOKEN cookie in the X-XSRF-TOKEN header. The cookie is written on safe responses when missing."""

    SAFE = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(self, request, call_next):
        cookie = request.cookies.get("XSRF-TOKEN")
        if request.method not in self.SAFE:
            header = request.headers.get("X-XSRF-TOKEN")
            if not cookie or not header or not secrets.compare_digest(cookie, header):
                return JSONResponse({"detail": "Token CSRF inválido"}, status_code=403)
        response = await call_next(request)
        if request.method in self.SAFE and not cookie:
            response.set_cookie("XSRF-TOKEN", secrets.token_urlsafe(32), path="/", samesite="lax",
                                secure=settings.csrf_cookie_secure, httponly=False)
        return response
