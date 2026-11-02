"""Interactive local configuration. Secrets are masked and never printed."""
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import quote

from dotenv import set_key
from .cloud_config import CloudSettings, PENDING_FILE

PROJECT_URL = 'https://gsdvtjvefwzkzumnxltc.supabase.co'
POOLER_HOST = 'aws-0-eu-west-1.pooler.supabase.com'
POOLER_USER = 'postgres.gsdvtjvefwzkzumnxltc'


def main():
    root = tk.Tk()
    root.title('VetInsight — connect Supabase locally')
    root.geometry('640x390')
    root.resizable(False, False)
    panel = ttk.Frame(root, padding=24); panel.pack(fill='both', expand=True)
    ttk.Label(panel, text='Connect the VetInsight Supabase project', font=('Segoe UI', 15, 'bold')).pack(anchor='w')
    ttk.Label(panel, text='Enter these here, not in chat. The values stay in a backend-only file.\nSaving does not switch the running app or migrate any data.', wraplength=580).pack(anchor='w', pady=(12, 20))
    ttk.Label(panel, text='Database password (the one chosen when creating this Supabase project)').pack(anchor='w')
    password = ttk.Entry(panel, show='*', width=76); password.pack(fill='x', pady=(5, 16))
    ttk.Label(panel, text='Supabase secret API key (sb_secret_… from Project Settings → API Keys)').pack(anchor='w')
    secret = ttk.Entry(panel, show='*', width=76); secret.pack(fill='x', pady=(5, 12))
    ttk.Label(panel, text=f'Project: {PROJECT_URL}\nPrivate bucket: vetinsight-records', wraplength=580).pack(anchor='w', pady=(0, 12))

    def save():
        try:
            if not password.get():
                raise ValueError('Enter the project database password.')
            dsn = f'postgresql://{POOLER_USER}:{quote(password.get(), safe="")}@{POOLER_HOST}:5432/postgres?sslmode=require'
            settings = CloudSettings(dsn, 'supabase', PROJECT_URL, secret.get().strip())
            settings.validate(require_cloud=True)
            temporary = Path(str(PENDING_FILE) + '.tmp')
            temporary.write_text('', encoding='utf-8')
            values = {'VETINSIGHT_DATABASE_URL': dsn, 'VETINSIGHT_STORAGE_PROVIDER': 'supabase',
                      'SUPABASE_URL': PROJECT_URL, 'SUPABASE_SECRET_KEY': settings.secret_key, 'SUPABASE_BUCKET': settings.bucket}
            for name, value in values.items():
                set_key(temporary, name, value)
            os.replace(temporary, PENDING_FILE)
            password.delete(0, 'end'); secret.delete(0, 'end')
            messagebox.showinfo('Saved locally', 'Pending credentials saved. Tell Codex that configuration is saved so migration can be verified. The running app is unchanged.')
            root.destroy()
        except ValueError as exc:
            messagebox.showerror('Check configuration', str(exc))
        except OSError:
            messagebox.showerror('Could not save', 'The backend configuration file could not be saved. No credentials were printed.')
    ttk.Button(panel, text='Save pending configuration', command=save).pack(anchor='e')
    password.focus_set()
    root.mainloop()


if __name__ == '__main__':
    main()
