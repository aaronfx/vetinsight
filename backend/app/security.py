"""Account administration and revocable, server-side cookie sessions."""
from datetime import datetime, timezone
import hashlib
import hmac
import os
import secrets
import sqlite3
from .database import IntegrityError
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

COOKIE = 'vetinsight_session'
SESSION_SECONDS = 8 * 60 * 60
PASSWORD_ROUNDS = 600_000


def stamp():
    return datetime.now(timezone.utc).isoformat()


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), PASSWORD_ROUNDS).hex()
    return f'pbkdf2_sha256${PASSWORD_ROUNDS}${salt}${digest}'


def verify_password(password, stored):
    try:
        algorithm, rounds, salt, expected = stored.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','member')),
            active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_limits (
            bucket TEXT PRIMARY KEY,
            attempts INTEGER NOT NULL,
            started_at REAL NOT NULL
        );
    ''')


def audit(db, actor_id, action, target):
    db.execute('INSERT INTO audit_events(actor_id,action,target,created_at) VALUES (?,?,?,?)',
               (actor_id, action, str(target), stamp()))


def public_user(row):
    return {key: (bool(row[key]) if key in ('active', 'must_change_password') else row[key])
            for key in ('id', 'username', 'display_name', 'role', 'active', 'must_change_password', 'created_at')}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Credentials(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class NewUser(StrictModel):
    username: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,79}$')
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=256)
    role: Literal['admin', 'member'] = 'member'

    @field_validator('username')
    @classmethod
    def normalize_username(cls, value):
        return value.lower()

    @field_validator('display_name')
    @classmethod
    def meaningful_name(cls, value):
        if not value.strip():
            raise ValueError('Enter a display name.')
        return value.strip()


class UserUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal['admin', 'member']
    active: bool = Field(strict=True)

    @field_validator('display_name')
    @classmethod
    def meaningful_name(cls, value):
        return NewUser.meaningful_name(value)


class PasswordReset(StrictModel):
    password: str = Field(min_length=12, max_length=256)


class PasswordChange(PasswordReset):
    current_password: str = Field(min_length=1, max_length=256)


def create_first_admin(db, payload: NewUser):
    db.execute('BEGIN IMMEDIATE')
    if db.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
        raise ValueError('Accounts already exist. Use an administrator account to manage users.')
    cursor = db.execute('''INSERT INTO users(username,display_name,password_hash,role,created_at)
                           VALUES (?,?,?,?,?)''',
                        (payload.username, payload.display_name, hash_password(payload.password), 'admin', stamp()))
    audit(db, cursor.lastrowid, 'admin.bootstrap', cursor.lastrowid)
    return cursor.lastrowid


def local_setup_request(request):
    # This is a local bootstrap flow, never a registration endpoint behind a proxy.
    return (request.client is not None and request.client.host in ('127.0.0.1', '::1')
            and request.url.hostname in ('localhost', '127.0.0.1', '::1')
            and not any(name in request.headers for name in ('forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto')))


def install(app, database, allowed_origins):
    router = APIRouter()
    dummy_hash = hash_password(secrets.token_urlsafe(24))

    def authenticated(request):
        token = request.cookies.get(COOKIE, '')
        if not token or len(token) > 128:
            raise HTTPException(401, 'Please sign in.')
        with database() as db:
            row = db.execute('''SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id
                WHERE sessions.token_hash=? AND sessions.expires_at>? AND users.active=1''',
                             (token_hash(token), time.time())).fetchone()
            if not row:
                raise HTTPException(401, 'Your session has ended. Please sign in again.')
            return public_user(row)

    def new_session(db, user_id, response):
        token = secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
        db.execute('INSERT INTO sessions VALUES (?,?,?)', (token_hash(token), user_id, time.time() + SESSION_SECONDS))
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=os.environ.get('VETINSIGHT_SECURE_COOKIES') == '1', samesite='lax', path='/')

    @app.middleware('http')
    async def access_control(request: Request, call_next):
        path = request.url.path
        public = path in ('/health', '/auth/status', '/auth/login', '/auth/setup')
        if request.method != 'OPTIONS':
            if request.method not in ('GET', 'HEAD'):
                origin = request.headers.get('origin')
                if request.headers.get('x-vetinsight-request') != '1' or (origin is not None and origin not in allowed_origins):
                    return JSONResponse({'detail': 'Request origin or security header is invalid.'}, status_code=403)
            if not public:
                try:
                    user = authenticated(request)
                    request.state.user = user
                    if user['must_change_password'] and path not in ('/auth/me', '/auth/password', '/auth/logout'):
                        raise HTTPException(403, 'Change your temporary password before continuing.')
                    if (path.startswith('/admin') or path in ('/docs', '/redoc', '/openapi.json', '/docs/oauth2-redirect')) and user['role'] != 'admin':
                        raise HTTPException(403, 'Administrator access is required.')
                except HTTPException as exc:
                    return JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers={'Cache-Control': 'no-store'})
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @router.get('/auth/status')
    def status(request: Request):
        with database() as db:
            needs_setup = db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0
            return {'service': 'VetInsight Case API', 'needs_setup': needs_setup,
                    'web_setup_available': needs_setup and local_setup_request(request)}

    @router.post('/auth/setup', status_code=201)
    def first_administrator(payload: NewUser, request: Request, response: Response):
        if not local_setup_request(request):
            raise HTTPException(403, 'First administrator setup is only available directly on the local computer. Use terminal setup on the server.')
        with database() as db:
            try:
                user_id = create_first_admin(db, payload)
            except ValueError:
                raise HTTPException(409, 'An account already exists. Sign in instead.')
            new_session(db, user_id, response)
            return public_user(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone())

    @router.post('/auth/login')
    def login(payload: Credentials, request: Request, response: Response):
        username = payload.username.strip().lower()
        ip = request.client.host if request.client else 'unknown'
        # Persist throttling across restarts. Never trust user-supplied forwarded IPs here.
        limited = False
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM login_limits WHERE started_at<?', (time.time() - 900,))
            for bucket, maximum in ((f'user:{token_hash(username)}', 10), (f'ip:{ip}', 50)):
                row = db.execute('SELECT attempts FROM login_limits WHERE bucket=?', (bucket,)).fetchone()
                if row and row[0] >= maximum:
                    limited = True
                db.execute('''INSERT INTO login_limits VALUES (?,1,?) ON CONFLICT(bucket)
                    DO UPDATE SET attempts=attempts+1''', (bucket, time.time()))
        if limited:
            raise HTTPException(429, 'Too many sign-in attempts. Try again in 15 minutes.', headers={'Retry-After': '900'})
        with database() as db:
            row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        valid = verify_password(payload.password, row['password_hash'] if row else dummy_hash)
        if not valid or not row or not row['active']:
            with database() as db:
                audit(db, None, 'auth.login_failed', 'account')
            raise HTTPException(401, 'Username or password is incorrect.')
        with database() as db:
            # Recheck after hashing: disable/reset may have happened concurrently.
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM users WHERE id=?', (row['id'],)).fetchone()
            if not current['active'] or current['password_hash'] != row['password_hash']:
                raise HTTPException(401, 'Username or password is incorrect.')
            old_token = request.cookies.get(COOKIE, '')
            db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(old_token),))
            new_session(db, row['id'], response)
            audit(db, row['id'], 'auth.login', row['id'])
            return public_user(current)

    @router.get('/auth/me')
    def me(request: Request):
        return request.state.user

    @router.post('/auth/logout')
    def logout(request: Request, response: Response):
        with database() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(request.cookies.get(COOKIE, '')),))
            audit(db, request.state.user['id'], 'auth.logout', request.state.user['id'])
        response.delete_cookie(COOKIE, path='/')
        return {'ok': True}

    @router.post('/auth/password')
    def change_password(payload: PasswordChange, request: Request, response: Response):
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            user_id = request.state.user['id']
            row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if not verify_password(payload.current_password, row['password_hash']):
                raise HTTPException(400, 'Current password is incorrect.')
            if payload.current_password == payload.password:
                raise HTTPException(422, 'Choose a different password.')
            db.execute('UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?', (hash_password(payload.password), user_id))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            new_session(db, user_id, response)
            audit(db, user_id, 'auth.password_changed', user_id)
            return public_user(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone())

    @router.get('/admin/overview')
    def overview():
        with database() as db:
            return {'users': db.execute('SELECT COUNT(*) FROM users').fetchone()[0],
                    'active_users': db.execute('SELECT COUNT(*) FROM users WHERE active=1').fetchone()[0],
                    'administrators': db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0],
                    'cases': db.execute('SELECT COUNT(*) FROM cases').fetchone()[0],
                    'uploads': db.execute('SELECT COUNT(*) FROM uploads').fetchone()[0],
                    'upload_bytes': db.execute('SELECT COALESCE(SUM(size_bytes),0) FROM uploads').fetchone()[0]}

    @router.get('/admin/users')
    def users(limit: int = 50, offset: int = 0):
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(422, 'Invalid pagination.')
        with database() as db:
            return {'items': [public_user(row) for row in db.execute('SELECT * FROM users ORDER BY id LIMIT ? OFFSET ?', (limit, offset))],
                    'total': db.execute('SELECT COUNT(*) FROM users').fetchone()[0]}

    @router.post('/admin/users', status_code=201)
    def add_user(payload: NewUser, request: Request):
        password_hash = hash_password(payload.password)
        with database() as db:
            try:
                cursor = db.execute('''INSERT INTO users(username,display_name,password_hash,role,must_change_password,created_at)
                    VALUES (?,?,?,?,1,?)''', (payload.username, payload.display_name, password_hash, payload.role, stamp()))
            except (sqlite3.IntegrityError, IntegrityError):
                raise HTTPException(409, 'This username already exists.')
            audit(db, request.state.user['id'], 'user.created', cursor.lastrowid)
            return public_user(db.execute('SELECT * FROM users WHERE id=?', (cursor.lastrowid,)).fetchone())

    @router.put('/admin/users/{user_id}')
    def update_user(user_id: int, payload: UserUpdate, request: Request):
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'User not found.')
            if row['role'] == 'admin' and row['active'] and (not payload.active or payload.role != 'admin'):
                if db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
                    raise HTTPException(409, 'Keep at least one active administrator.')
            db.execute('UPDATE users SET display_name=?,role=?,active=? WHERE id=?',
                       (payload.display_name, payload.role, payload.active, user_id))
            if not payload.active or row['role'] != payload.role:
                db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            audit(db, request.state.user['id'], f'user.updated:{payload.role}:{"active" if payload.active else "disabled"}', user_id)
            return public_user(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone())

    @router.post('/admin/users/{user_id}/password')
    def reset_password(user_id: int, payload: PasswordReset, request: Request):
        if user_id == request.state.user['id']:
            raise HTTPException(422, 'Use Change password for your own account.')
        with database() as db:
            if not db.execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone():
                raise HTTPException(404, 'User not found.')
            db.execute('UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?', (hash_password(payload.password), user_id))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            audit(db, request.state.user['id'], 'user.password_reset', user_id)
        return {'ok': True}

    @router.get('/admin/audit')
    def events(limit: int = 50, offset: int = 0):
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(422, 'Invalid pagination.')
        with database() as db:
            return {'items': [dict(row) for row in db.execute('''SELECT audit_events.*, users.username AS actor
                FROM audit_events LEFT JOIN users ON users.id=audit_events.actor_id
                ORDER BY audit_events.id DESC LIMIT ? OFFSET ?''', (limit, offset))],
                    'total': db.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0]}

    app.include_router(router)
