from db import APP_DB, connect_sqlite


def category_stats() -> list[dict]:
    con = connect_sqlite(APP_DB)
    rows = con.execute(
        """
        SELECT
            category AS name,
            COUNT(*) AS total,
            SUM(CASE WHEN status IN ('mastered', 'known') THEN 1 ELSE 0 END) AS mastered
        FROM words
        GROUP BY category
        ORDER BY total DESC, category COLLATE NOCASE
        """
    ).fetchall()
    con.close()
    result = []
    for row in rows:
        total = int(row["total"] or 0)
        mastered = int(row["mastered"] or 0)
        percent = round(mastered * 100 / total) if total else 0
        result.append({"name": row["name"] or "Imported", "total": total, "mastered": mastered, "percent": percent})
    return result
