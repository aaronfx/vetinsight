"""Run locally: python -m app.manage_admin. Passwords are read without echo."""
import asyncio
from getpass import getpass
from pydantic import ValidationError

from . import main
from .security import NewUser, create_first_admin


async def setup():
    async with main.lifespan(main.app):
        with main.database() as db:
            if db.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
                raise ValueError('Accounts already exist. Sign in to manage them.')
        username = input('Admin username (3-80 letters, numbers, dot, dash or underscore): ').strip()
        name = input('Display name: ').strip()
        password = getpass('Password (at least 12 characters): ')
        if password != getpass('Confirm password: '):
            raise ValueError('Passwords do not match.')
        payload = NewUser(username=username, display_name=name, password=password, role='admin')
        with main.database() as db:
            create_first_admin(db, payload)
        print('Administrator created. Open http://localhost:5173/ and sign in.')


if __name__ == '__main__':
    try:
        asyncio.run(setup())
    except ValidationError as exc:
        # Pydantic's default string includes input values, including passwords.
        print('Setup stopped: ' + '; '.join(f'{".".join(map(str, item["loc"]))}: {item["msg"]}' for item in exc.errors()))
        raise SystemExit(1)
    except (ValueError, KeyboardInterrupt) as exc:
        print(f'Setup stopped: {exc}')
        raise SystemExit(1)
