"""Generate the deterministic messy order exports used by the examples.

Run from the repository root:

    python examples/generate_orders.py

It rewrites examples/orders.csv (200 rows, the "good" batch) and
examples/orders_drift.csv (120 rows, a producer that silently changed types).
Both files are committed so the README screenshots are reproducible without
running this script.
"""

from __future__ import annotations

import csv
import pathlib
import random

HEADER = [
    "order_id",
    "customer_name",
    "email",
    "country",
    "status",
    "amount",
    "tax",
    "quantity",
    "created_at",
    "updated_at",
    "card_number",
    "phone",
    "is_gift",
    "sku",
    "website",
    "notes",
]

FIRST_NAMES = [
    "Ada",
    "Grace",
    "Alan",
    "Barbara",
    "Edsger",
    "Frances",
    "Guido",
    "Hedy",
    "Ivan",
    "Julia",
    "Ken",
    "Linus",
    "Margaret",
    "Niklaus",
    "Olga",
    "Peter",
    "Radia",
    "Sergey",
    "Tina",
    "Vint",
    "Wei",
    "Xia",
    "Yann",
    "Zora",
]
LAST_NAMES = [
    "Lovelace",
    "Hopper",
    "Turing",
    "Liskov",
    "Dijkstra",
    "Allen",
    "Rossum",
    "Lamarr",
    "Sutherland",
    "Robinson",
    "Thompson",
    "Torvalds",
    "Hamilton",
    "Wirth",
    "Kovalenko",
    "Naur",
]

COUNTRIES = ["US", "DE", "FR", "GB", "JP", "BR", "IN"]
STATUSES = ["pending", "shipped", "delivered", "cancelled", "refunded"]

CARD_BINS = ["4242", "5555", "4000", "6011"]


def luhn_complete(payload: str) -> str:
    """Return payload plus the check digit that makes it pass Luhn."""
    total = 0
    for index, char in enumerate(reversed(payload)):
        digit = int(char)
        if index % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return payload + str((10 - total % 10) % 10)


def make_email(first: str, last: str) -> str:
    domain = random.choice(["example.com", "example.org", "mail.example.net"])
    separator = random.choice([".", "_", ""])
    return (first + separator + last).lower() + "@" + domain


def make_date(rng: random.Random) -> str:
    day = rng.randint(1, 28)
    month = rng.randint(1, 12)
    year = 2026
    style = rng.choice([0, 0, 1, 2])
    if style == 0:
        return "%04d-%02d-%02d" % (year, month, day)
    if style == 1:
        return "%02d/%02d/%04d" % (day, month, year)
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return "%s %02d, %d" % (months[month - 1], day, year)


def make_amount(rng: random.Random) -> str:
    amount = rng.randint(500, 480000) / 100.0
    return "$" + format(amount, ",.2f")


def make_sku(rng: random.Random) -> str:
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    prefix = "".join(rng.choice(letters) for _ in range(2))
    return "SKU-%s-%04d" % (prefix, rng.randint(1, 9999))


def make_notes(rng: random.Random) -> str:
    return rng.choice(
        [
            "",
            "",
            "leave at door",
            "gift wrap requested",
            "call before delivery",
            "second attempt",
            "fragile",
            "deliver after 6pm",
            "buzzer is broken",
            "post to neighbour",
        ]
    )


def make_phone(rng: random.Random) -> str:
    return "+1 %03d 555 %04d" % (rng.randint(200, 989), rng.randint(1, 9999))


def make_card(rng: random.Random) -> str:
    body = random.choice(CARD_BINS) + "".join(str(rng.randint(0, 9)) for _ in range(11))
    digits = luhn_complete(body)
    return " ".join(digits[i : i + 4] for i in range(0, 16, 4))


def build_rows(count: int, *, drift: bool, seed: int = 7) -> list[list[str]]:
    """Return count rows; drift=True silently changes three column types."""
    rng = random.Random(seed)
    random.seed(seed)
    rows: list[list[str]] = []
    for index in range(1, count + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        status = rng.choice(STATUSES)
        if index % 37 == 0:
            status = "shiped"
        email = make_email(first, last)
        if index in (14, 91):
            email = ""
        amount = make_amount(rng)
        if drift and index % 3 == 0:
            amount = amount.replace("$", "").replace(",", "")
        country = rng.choice(COUNTRIES)
        if drift and index % 11 == 0:
            country = country.lower()
        row = [
            "ORD-%05d" % (10000 + index),
            first + " " + last,
            email,
            country,
            status,
            amount,
            "%.2f" % (rng.randint(50, 4000) / 100.0),
            str(rng.randint(1, 12)),
            make_date(rng),
            "2026-%02d-%02dT%02d:%02d:00Z"
            % (rng.randint(1, 12), rng.randint(1, 28), rng.randint(0, 23), rng.randint(0, 59)),
            make_card(rng),
            make_phone(rng),
            rng.choice(["true", "false"]),
            make_sku(rng),
            "https://shop.example.com/item/%04d" % rng.randint(1, 9999),
            make_notes(rng),
        ]
        if drift and index % 17 == 0:
            row[8] = "Q1 2026"
        if drift and index % 5 == 0:
            row[7] = "n/a"
        if drift and index % 13 == 0:
            row[12] = "maybe"
        if drift and index % 7 == 0:
            row[6] = "12,50"
        rows.append(row)
    return rows


def write_csv(path: pathlib.Path, rows: list[list[str]], header: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def main() -> int:
    """Write both example files next to this script."""
    here = pathlib.Path(__file__).resolve().parent
    write_csv(here / "orders.csv", build_rows(200, drift=False), HEADER)
    drift_header = HEADER[:-1] + ["loyalty_tier", "notes"]
    drift_rows = [
        row[:15] + ["bronze" if index % 2 else "silver"] + [row[15]]
        for index, row in enumerate(build_rows(120, drift=True, seed=21))
    ]
    write_csv(here / "orders_drift.csv", drift_rows, drift_header)
    print("wrote " + str(here / "orders.csv") + " (200 rows)")
    print("wrote " + str(here / "orders_drift.csv") + " (120 rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
