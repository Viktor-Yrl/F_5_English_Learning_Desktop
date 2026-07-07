import json

from db import APP_DB, connect_sqlite


def setting_value(name: str, default):
    con = connect_sqlite(APP_DB)
    row = con.execute("SELECT value FROM progress WHERE name=?", (f"setting.{name}",)).fetchone()
    con.close()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return default


def save_setting(name: str, value) -> None:
    con = connect_sqlite(APP_DB)
    con.execute(
        "INSERT OR REPLACE INTO progress(name, value) VALUES (?, ?)",
        (f"setting.{name}", json.dumps(value, ensure_ascii=False)),
    )
    con.commit()
    con.close()
