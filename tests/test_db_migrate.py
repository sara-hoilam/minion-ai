"""Test database migration for legacy schemas."""

import sqlite3
from pathlib import Path

from backend.app import create_app
from backend.services.db_migrate import migrate_db


def test_migrate_legacy_db_without_resume_columns(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            created_at DATETIME,
            stripe_customer_id VARCHAR(255),
            subscription_status VARCHAR(50)
        );
        CREATE TABLE user_profiles (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            full_name VARCHAR(255),
            field VARCHAR(100),
            skillset TEXT,
            current_job VARCHAR(255),
            years_experience INTEGER,
            industry VARCHAR(100),
            completed_background BOOLEAN,
            updated_at DATETIME
        );
    """)
    conn.close()

    app = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        "DISABLE_AUTH": False,
    })
    with app.app_context():
        migrate_db()

    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)")}
    conn.close()

    assert "resume_file_path" in cols
    assert "resume_original_name" in cols
    assert "resume_uploaded_at" in cols

    client = app.test_client()
    r = client.post("/api/auth/register", json={"email": "legacy@test.com", "password": "securepass1"})
    assert r.status_code == 201
