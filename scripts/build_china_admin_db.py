#!/usr/bin/env python3
"""Build nationwide province/city/county SQLite from modood pcas-code.json."""

from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "china_admin_divisions.sqlite"
DEFAULT_CSV = ROOT / "data" / "china_admin_divisions.csv"
DEFAULT_URL = "https://raw.githubusercontent.com/modood/Administrative-divisions-of-China/master/dist/pcas-code.json"

DIVISION_FIELDS = [
    "code",
    "name",
    "full_name",
    "level",
    "parent_code",
    "parent_name",
    "city_name",
    "county_name",
    "township_name",
    "village_name",
    "entity_type",
    "urban_rural_code",
    "source",
    "source_year",
    "is_active",
]

MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}


def main() -> int:
    parser = argparse.ArgumentParser(description="构建全国省/市/区县三级行政区划 SQLite")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--json", default="", help="本地 pcas-code.json 路径")
    args = parser.parse_args()

    payload = _load_json(Path(args.json) if args.json else None, args.url)
    divisions = list(_flatten_divisions(payload))
    aliases = list(_generate_aliases(divisions))
    _write_sqlite(Path(args.db), divisions, aliases)
    _write_csv(Path(args.csv), divisions)
    print(f"wrote: {args.db}")
    print(f"divisions: {len(divisions)}")
    print(f"aliases: {len(aliases)}")
    return 0


def _load_json(local_path: Path | None, url: str) -> list[dict]:
    if local_path and local_path.exists():
        return json.loads(local_path.read_text(encoding="utf-8"))
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _flatten_divisions(nodes: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def walk(
        items: list[dict],
        *,
        province: dict | None = None,
        city: dict | None = None,
        depth: int = 0,
    ) -> None:
        for item in items:
            name = str(item.get("name", "")).strip()
            code = str(item.get("code", "")).strip()
            children = item.get("children") or []
            if not name or not code:
                continue

            if depth == 0:
                province = {"code": code, "name": name}
                rows.append(_division_row(province, None, None, "province"))
                walk(children, province=province, city=None, depth=1)
                continue

            if depth == 1:
                if province and province["name"] in MUNICIPALITIES and name == "市辖区":
                    walk(children, province=province, city=province, depth=2)
                    continue
                city = {"code": code, "name": name}
                rows.append(_division_row(province, city, None, "city"))
                walk(children, province=province, city=city, depth=2)
                continue

            if depth == 2:
                county = {"code": code, "name": name}
                level = "county_city" if name.endswith("市") and province and province["name"] not in MUNICIPALITIES else "county"
                rows.append(_division_row(province, city, county, level))
                continue

    walk(nodes)
    return _dedupe_divisions(rows)


def _division_row(
    province: dict | None,
    city: dict | None,
    county: dict | None,
    level: str,
) -> dict[str, str]:
    if level == "province":
        assert province is not None
        return {
            "code": province["code"],
            "name": province["name"],
            "full_name": province["name"],
            "level": "province",
            "parent_code": "",
            "parent_name": "",
            "city_name": "",
            "county_name": "",
            "township_name": "",
            "village_name": "",
            "entity_type": "location",
            "urban_rural_code": "",
            "source": "modood/pcas-code",
            "source_year": "2024",
            "is_active": "1",
        }

    if level == "city":
        assert province is not None and city is not None
        full_name = f"{province['name']}{city['name']}"
        return {
            "code": city["code"],
            "name": city["name"],
            "full_name": full_name,
            "level": "city",
            "parent_code": province["code"],
            "parent_name": province["name"],
            "city_name": city["name"],
            "county_name": "",
            "township_name": "",
            "village_name": "",
            "entity_type": "location",
            "urban_rural_code": "",
            "source": "modood/pcas-code",
            "source_year": "2024",
            "is_active": "1",
        }

    assert province is not None and city is not None and county is not None
    if province["name"] in MUNICIPALITIES:
        full_name = f"{province['name']}{county['name']}"
        parent_code = province["code"]
        parent_name = province["name"]
        city_name = province["name"]
    else:
        full_name = f"{province['name']}{city['name']}{county['name']}"
        parent_code = city["code"]
        parent_name = city["name"]
        city_name = city["name"]
    return {
        "code": county["code"],
        "name": county["name"],
        "full_name": full_name,
        "level": level,
        "parent_code": parent_code,
        "parent_name": parent_name,
        "city_name": city_name,
        "county_name": county["name"],
        "township_name": "",
        "village_name": "",
        "entity_type": "location",
        "urban_rural_code": "",
        "source": "modood/pcas-code",
        "source_year": "2024",
        "is_active": "1",
    }


def _generate_aliases(divisions: list[dict[str, str]]) -> list[dict[str, str]]:
    aliases: list[dict[str, str]] = []
    for row in divisions:
        name = row["name"]
        full_name = row["full_name"]
        code = row["code"]
        level = row["level"]
        if level == "province" and name.endswith("省"):
            aliases.append(_alias_row(name[:-1], full_name, code, "province_short"))
        if level == "city" and name.endswith("市"):
            aliases.append(_alias_row(name[:-1], full_name, code, "city_short"))
        if level in {"county", "county_city"} and name.endswith(("区", "县", "市", "旗")):
            aliases.append(_alias_row(name[:-1], full_name, code, "county_short"))
        if level == "city" and full_name.startswith(tuple(MUNICIPALITIES)):
            stripped = full_name.removeprefix(row.get("parent_name", ""))
            if stripped and stripped != name:
                aliases.append(_alias_row(stripped, full_name, code, "municipality_combo"))
    return _dedupe_aliases(aliases)


def _alias_row(alias: str, canonical: str, code: str, alias_type: str) -> dict[str, str]:
    return {
        "alias": alias,
        "canonical_name": canonical,
        "division_code": code,
        "alias_type": alias_type,
        "source": "generated",
        "confidence": "0.9",
    }


def _dedupe_divisions(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for row in rows:
        code = row["code"]
        if code in seen:
            continue
        seen.add(code)
        unique.append(row)
    return unique


def _dedupe_aliases(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for row in rows:
        key = (row["alias"], row["division_code"])
        if key in seen or len(row["alias"]) < 2:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _write_sqlite(path: Path, divisions: list[dict[str, str]], aliases: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE IF EXISTS admin_divisions")
        conn.execute("DROP TABLE IF EXISTS admin_aliases")
        conn.execute(
            """
            CREATE TABLE admin_divisions (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                full_name TEXT NOT NULL,
                level TEXT NOT NULL,
                parent_code TEXT,
                parent_name TEXT,
                city_name TEXT,
                county_name TEXT,
                township_name TEXT,
                village_name TEXT,
                entity_type TEXT NOT NULL,
                urban_rural_code TEXT,
                source TEXT,
                source_year TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE admin_aliases (
                alias TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                division_code TEXT NOT NULL,
                alias_type TEXT,
                source TEXT,
                confidence REAL,
                UNIQUE(alias, division_code)
            )
            """
        )
        conn.executemany(
            f"INSERT OR REPLACE INTO admin_divisions ({','.join(DIVISION_FIELDS)}) VALUES ({','.join('?' for _ in DIVISION_FIELDS)})",
            [[row.get(field, "") for field in DIVISION_FIELDS] for row in divisions],
        )
        alias_fields = ["alias", "canonical_name", "division_code", "alias_type", "source", "confidence"]
        conn.executemany(
            f"INSERT OR REPLACE INTO admin_aliases ({','.join(alias_fields)}) VALUES ({','.join('?' for _ in alias_fields)})",
            [[row.get(field, "") for field in alias_fields] for row in aliases],
        )


def _write_csv(path: Path, divisions: list[dict[str, str]]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DIVISION_FIELDS)
        writer.writeheader()
        for row in divisions:
            writer.writerow({field: row.get(field, "") for field in DIVISION_FIELDS})


if __name__ == "__main__":
    raise SystemExit(main())