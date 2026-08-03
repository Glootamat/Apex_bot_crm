"""Prepare a safe, read-only preview for importing Google Contacts into Apex CRM.

The preview never changes the CRM database.  It extracts only data that can be
identified conservatively and leaves ambiguous source text for manual review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from backup import create_backup, verify_backup
from database import Database


PLATE_LETTERS = "ABEKMHOPCTYXАВЕКМНОРСТУХ"
PLATE_RE = re.compile(
    rf"(?<![A-ZА-Я0-9])([{PLATE_LETTERS}])\s*(\d{{3}})\s*([{PLATE_LETTERS}]{{2}})(?:\s*(\d{{2,3}}))?(?![A-ZА-Я0-9])",
    re.IGNORECASE,
)

# Longer aliases must be checked first.  Model-only aliases cover the common
# shorthand used in the supplied phone book (for example, "Приора" or "Солярис").
VEHICLE_ALIASES: tuple[tuple[str, str, str | None], ...] = (
    ("шевроле трэилблейзер", "Chevrolet", "TrailBlazer"),
    ("шевроле нива", "Chevrolet", "Niva"),
    ("митсубиси оутлендер", "Mitsubishi", "Outlander"),
    ("ниссан quashkai", "Nissan", "Qashqai"),
    ("хендай", "Hyundai", None), ("hyundai", "Hyundai", None),
    ("фольксваген", "Volkswagen", None), ("volkswagen", "Volkswagen", None),
    ("мерседес", "Mercedes-Benz", None), ("mercedes", "Mercedes-Benz", None),
    ("шевроле", "Chevrolet", None), ("chevrolet", "Chevrolet", None),
    ("ситроен", "Citroen", None), ("citroen", "Citroen", None),
    ("митсубиси", "Mitsubishi", None), ("mitsubishi", "Mitsubishi", None),
    ("инфинити", "Infiniti", None), ("infiniti", "Infiniti", None),
    ("субару", "Subaru", None), ("subaru", "Subaru", None),
    ("тойота", "Toyota", None), ("toyota", "Toyota", None),
    ("ниссан", "Nissan", None), ("nissan", "Nissan", None),
    ("хонда", "Honda", None), ("honda", "Honda", None),
    ("шкода", "Skoda", None), ("skoda", "Skoda", None),
    ("рено", "Renault", None), ("renault", "Renault", None),
    ("пежо", "Peugeot", None), ("peugeot", "Peugeot", None),
    ("опель", "Opel", None), ("opel", "Opel", None),
    ("форд", "Ford", None), ("ford", "Ford", None),
    ("ауди", "Audi", None), ("audi", "Audi", None),
    ("вольво", "Volvo", None), ("volvo", "Volvo", None),
    ("мазда", "Mazda", None), ("mazda", "Mazda", None),
    ("датсун", "Datsun", None), ("datsun", "Datsun", None),
    ("дэо", "Daewoo", None), ("деу", "Daewoo", None), ("daewoo", "Daewoo", None),
    ("черри", "Chery", None), ("chery", "Chery", None), ("cherry", "Chery", None),
    ("киа", "Kia", None), ("kia", "Kia", None),
    ("vw", "Volkswagen", None),
    ("солярис", "Hyundai", "Solaris"),
    ("акцент", "Hyundai", "Accent"),
    ("круз", "Chevrolet", "Cruze"),
    ("приора", "Lada", "Priora"),
    ("гранта", "Lada", "Granta"),
    ("калина", "Lada", "Kalina"),
    ("веста", "Lada", "Vesta"),
    ("ларгус", "Lada", "Largus"),
    ("нива", "Lada", "Niva"),
    ("ваз", "Lada", None), ("лада", "Lada", None),
    ("пассат", "Volkswagen", "Passat"),
    ("гольф", "Volkswagen", "Golf"),
    ("матиз", "Daewoo", "Matiz"),
)

WORK_WORDS = {
    "замена", "ремонт", "диагностика", "установка", "не", "троит", "течь",
    "ошибки", "прокладка", "сцепление", "масло", "колодки", "выезд", "ходовка",
    "капиталка", "прошивка", "магнитола", "сигнализация", "осмотр", "скрип",
}


@dataclass(frozen=True)
class VCardContact:
    source_index: int
    display_name: str
    phones: list[str]
    notes: list[str]


@dataclass(frozen=True)
class ImportCandidate:
    source_index: int
    source_name: str
    customer_name: str | None
    phones: list[str]
    brand: str | None
    model: str | None
    plate_number: str | None
    imported_note: str | None
    action: str
    existing_customer_id: int | None
    review_reasons: list[str]


def _unescape(value: str) -> str:
    return (value.replace("\\n", "\n").replace("\\N", "\n")
            .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip())


def _normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits if len(digits) >= 10 else None


def format_phone(value: str) -> str:
    digits = _normalize_phone(value) or re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("7"):
        return f"+7 {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:]}"
    return "+" + digits if digits else value


def parse_vcards(path: str | Path) -> list[VCardContact]:
    text = Path(path).read_text(encoding="utf-8-sig")
    unfolded: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)

    cards: list[VCardContact] = []
    current: list[str] | None = None
    for line in unfolded:
        if line.upper() == "BEGIN:VCARD":
            current = []
        elif line.upper() == "END:VCARD" and current is not None:
            fields: dict[str, list[str]] = {}
            for raw in current:
                if ":" not in raw:
                    continue
                key, value = raw.split(":", 1)
                fields.setdefault(key.split(";", 1)[0].upper(), []).append(_unescape(value))
            display_name = (fields.get("FN") or [""])[0].strip()
            phones = []
            for raw_phone in fields.get("TEL", []):
                normalized = _normalize_phone(raw_phone)
                if normalized and normalized not in phones:
                    phones.append(normalized)
            notes = [item for item in fields.get("NOTE", []) + fields.get("TITLE", []) if item]
            cards.append(VCardContact(len(cards) + 1, display_name, phones, notes))
            current = None
        elif current is not None:
            current.append(line)
    return cards


def _word_boundary_find(text: str, alias: str) -> int:
    match = re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", text, re.IGNORECASE)
    return match.start() if match else -1


def _vehicles(text: str) -> list[tuple[int, str, str | None, str]]:
    found: list[tuple[int, str, str | None, str]] = []
    occupied: list[tuple[int, int]] = []
    for alias, brand, default_model in VEHICLE_ALIASES:
        start = _word_boundary_find(text, alias)
        if start < 0:
            continue
        end = start + len(alias)
        if any(not (end <= left or start >= right) for left, right in occupied):
            continue
        occupied.append((start, end))
        found.append((start, brand, default_model, alias))
    found.sort()
    combined: list[tuple[int, str, str | None, str]] = []
    for item in found:
        same_brand_at = next((i for i, existing in enumerate(combined) if existing[1] == item[1]), None)
        if same_brand_at is None:
            combined.append(item)
            continue
        existing = combined[same_brand_at]
        # A brand plus its model-only alias is one car ("Дэо Матиз",
        # "Hyundai Solaris"), not two different vehicles.
        if existing[2] is None and item[2] is not None:
            combined[same_brand_at] = (existing[0], existing[1], item[2], existing[3])
    return sorted(combined)


def _extract_plate(text: str) -> str | None:
    match = PLATE_RE.search(text)
    if not match:
        return None
    return "".join(part or "" for part in match.groups()).upper()


def _extract_model(text: str, vehicle: tuple[int, str, str | None, str]) -> str | None:
    start, _brand, default_model, alias = vehicle
    if default_model:
        return default_model
    tail = text[start + len(alias):].strip(" ,.-")
    if not tail:
        return None
    words = tail.split()
    model_words: list[str] = []
    for word in words:
        clean = re.sub(r"[^0-9A-Za-zА-Яа-я.-]", "", word)
        if not clean or clean.casefold() in WORK_WORDS or PLATE_RE.fullmatch(clean):
            break
        if not model_words:
            model_words.append(clean)
            continue
        # Generations and engine/model indexes belong to the first model word
        # (Tiggo 7, Focus 2, Passat B5).  Free text after it is usually a work
        # description and must not leak into the model field.
        if re.search(r"\d", clean):
            model_words.append(clean)
        break
    return " ".join(model_words) or None


def _extract_customer_name(text: str, first_vehicle_at: int | None) -> str | None:
    if first_vehicle_at is None or first_vehicle_at == 0:
        return None
    prefix = PLATE_RE.sub(" ", text[:first_vehicle_at]).strip(" ,.-")
    prefix = re.sub(r"\s+", " ", prefix)
    words = [word for word in prefix.split() if word.casefold() != "клиент"]
    if not words or any(word.casefold() in WORK_WORDS for word in words):
        return None
    # Relationship/location hints are kept because they are useful identifiers
    # in the original phone book (for example, "Колёк Верхнерусское").
    return " ".join(words)


def analyze_contact(contact: VCardContact, existing_by_phone: dict[str, tuple[int, str]]) -> ImportCandidate:
    text = re.sub(r"\s+", " ", contact.display_name).strip()
    vehicles = _vehicles(text)
    plate = _extract_plate(text)
    review: list[str] = []

    if not contact.phones:
        review.append("нет телефона")
    if len(contact.phones) > 1:
        review.append("несколько телефонов")
    if len(vehicles) > 1:
        review.append("в одном контакте возможно несколько автомобилей")
    if not vehicles:
        review.append("автомобиль не распознан")

    primary_vehicle = vehicles[0] if vehicles else None
    customer_name = _extract_customer_name(text, primary_vehicle[0] if primary_vehicle else None)
    brand = primary_vehicle[1] if primary_vehicle else None
    model = _extract_model(text, primary_vehicle) if primary_vehicle else None
    if primary_vehicle and not model:
        review.append("модель автомобиля не определена")

    existing_id = None
    existing_name = None
    for phone in contact.phones:
        if phone in existing_by_phone:
            existing_id, existing_name = existing_by_phone[phone]
            break
    if existing_name:
        customer_name = existing_name

    imported_note_parts = list(contact.notes)
    if text and (not customer_name or brand):
        imported_note_parts.append(f"Исходное имя контакта: {text}")
    imported_note = "\n".join(dict.fromkeys(imported_note_parts)) or None

    if review:
        action = "review"
    elif existing_id is not None:
        action = "merge_existing"
    else:
        action = "create"
    return ImportCandidate(
        source_index=contact.source_index,
        source_name=text,
        customer_name=customer_name,
        phones=[format_phone(phone) for phone in contact.phones],
        brand=brand,
        model=model,
        plate_number=plate,
        imported_note=imported_note,
        action=action,
        existing_customer_id=existing_id,
        review_reasons=review,
    )


def load_existing_customers(db_path: str | Path, telegram_id: int) -> dict[str, tuple[int, str]]:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            """SELECT c.id, c.full_name, c.phone_normalized, c.phone
               FROM customers c JOIN users u ON u.id = c.user_id
               WHERE u.telegram_id = ? AND c.archived_at IS NULL""",
            (telegram_id,),
        ).fetchall()
        result: dict[str, tuple[int, str]] = {}
        for customer_id, name, normalized, phone in rows:
            key = normalized or _normalize_phone(phone or "")
            if key:
                result[str(key)] = (int(customer_id), str(name))
        return result
    finally:
        connection.close()


def build_preview(vcf_path: str | Path, db_path: str | Path, telegram_id: int) -> dict[str, object]:
    contacts = parse_vcards(vcf_path)
    existing = load_existing_customers(db_path, telegram_id)
    candidates = [analyze_contact(contact, existing) for contact in contacts]
    summary = {
        "total": len(candidates),
        "ready_to_create": sum(item.action == "create" for item in candidates),
        "ready_to_merge": sum(item.action == "merge_existing" for item in candidates),
        "existing_phone_matches": sum(item.existing_customer_id is not None for item in candidates),
        "needs_review": sum(item.action == "review" for item in candidates),
        "without_phone": sum(not item.phones for item in candidates),
        "with_multiple_phones": sum(len(item.phones) > 1 for item in candidates),
    }
    return {"summary": summary, "contacts": [asdict(item) for item in candidates]}


def apply_preview(
    preview: dict[str, object], db_path: str | Path, telegram_id: int,
    source_fingerprint: str,
) -> dict[str, int]:
    """Atomically import only new, review-free candidates.

    Existing phone numbers are intentionally skipped without updating their
    customer or car records.  A second run of the same source is idempotent.
    """
    connection = sqlite3.connect(Path(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    counts = {
        "imported_customers": 0,
        "imported_cars": 0,
        "skipped_existing": 0,
        "skipped_review": 0,
        "skipped_already_imported": 0,
    }
    try:
        connection.execute("BEGIN IMMEDIATE")
        owner = connection.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if owner is None:
            raise RuntimeError(f"CRM user for Telegram ID {telegram_id} was not found")
        user_id = int(owner["id"])

        for raw in preview["contacts"]:  # type: ignore[index]
            item = dict(raw)
            if item["action"] == "review":
                counts["skipped_review"] += 1
                continue
            if item["action"] != "create":
                counts["skipped_existing"] += 1
                continue
            already = connection.execute(
                """SELECT 1 FROM contact_imports
                   WHERE user_id = ? AND source_fingerprint = ? AND source_index = ?""",
                (user_id, source_fingerprint, int(item["source_index"])),
            ).fetchone()
            if already is not None:
                counts["skipped_already_imported"] += 1
                continue

            phones = list(item["phones"])
            phone = str(phones[0]) if phones else None
            normalized = _normalize_phone(phone or "")
            existing = connection.execute(
                """SELECT id FROM customers
                   WHERE user_id = ? AND phone_normalized = ? ORDER BY id LIMIT 1""",
                (user_id, normalized),
            ).fetchone()
            if existing is not None:
                counts["skipped_existing"] += 1
                continue

            full_name = str(item["customer_name"] or f"Клиент {phone}")
            customer_cursor = connection.execute(
                """INSERT INTO customers (user_id, full_name, phone, phone_normalized)
                   VALUES (?, ?, ?, ?)""",
                (user_id, full_name, phone, normalized),
            )
            customer_id = int(customer_cursor.lastrowid)
            counts["imported_customers"] += 1

            car_id = None
            if item.get("brand") and item.get("model"):
                plate = item.get("plate_number")
                plate_normalized = re.sub(r"[^0-9A-ZА-Я]", "", str(plate).upper()) if plate else None
                car_cursor = connection.execute(
                    """INSERT INTO cars
                       (user_id, customer_id, brand, model, plate_number, plate_normalized)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (user_id, customer_id, item["brand"], item["model"], plate, plate_normalized),
                )
                car_id = int(car_cursor.lastrowid)
                counts["imported_cars"] += 1
                connection.execute(
                    """INSERT INTO audit_log (user_id, entity_type, entity_id, action, details)
                       VALUES (?, 'car', ?, 'imported', 'source=google_contacts')""",
                    (user_id, car_id),
                )

            note = item.get("imported_note")
            if note:
                connection.execute(
                    """INSERT OR IGNORE INTO customer_notes (customer_id, note_text, source)
                       VALUES (?, ?, 'google_contacts')""",
                    (customer_id, note),
                )
            connection.execute(
                """INSERT INTO contact_imports
                   (user_id, source_fingerprint, source_index, customer_id, car_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, source_fingerprint, int(item["source_index"]), customer_id, car_id),
            )
            connection.execute(
                """INSERT INTO audit_log (user_id, entity_type, entity_id, action, details)
                   VALUES (?, 'customer', ?, 'imported', 'source=google_contacts')""",
                (user_id, customer_id),
            )
        connection.commit()
        return counts
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def apply_manual_decisions(
    decisions: list[dict[str, object]], db_path: str | Path, telegram_id: int,
    source_fingerprint: str,
) -> dict[str, int]:
    """Apply user-reviewed contacts, including extra phones and multiple cars."""
    connection = sqlite3.connect(Path(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    counts = {
        "imported_customers": 0,
        "imported_cars": 0,
        "imported_extra_phones": 0,
        "skipped_existing": 0,
        "skipped_already_imported": 0,
    }
    try:
        connection.execute("BEGIN IMMEDIATE")
        owner = connection.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if owner is None:
            raise RuntimeError(f"CRM user for Telegram ID {telegram_id} was not found")
        user_id = int(owner["id"])

        for decision in decisions:
            source_indices = [int(value) for value in decision["source_indices"]]  # type: ignore[index]
            imported_count = connection.execute(
                f"""SELECT COUNT(*) FROM contact_imports
                    WHERE user_id = ? AND source_fingerprint = ?
                      AND source_index IN ({','.join('?' for _ in source_indices)})""",
                (user_id, source_fingerprint, *source_indices),
            ).fetchone()[0]
            if imported_count:
                counts["skipped_already_imported"] += 1
                continue

            phones = [str(value) for value in decision.get("phones", [])]
            normalized_phones = [_normalize_phone(phone) for phone in phones]
            normalized_phones = [value for value in normalized_phones if value]
            existing = None
            if normalized_phones:
                placeholders = ",".join("?" for _ in normalized_phones)
                existing = connection.execute(
                    f"""SELECT c.id FROM customers c
                        WHERE c.user_id = ? AND (
                            c.phone_normalized IN ({placeholders}) OR EXISTS (
                                SELECT 1 FROM customer_phones cp WHERE cp.customer_id = c.id
                                AND cp.phone_normalized IN ({placeholders})
                            )
                        ) LIMIT 1""",
                    (user_id, *normalized_phones, *normalized_phones),
                ).fetchone()
            if existing is not None:
                counts["skipped_existing"] += 1
                continue

            primary_phone = phones[0] if phones else None
            full_name = str(decision.get("customer_name") or f"Клиент {primary_phone}")
            cursor = connection.execute(
                """INSERT INTO customers (user_id, full_name, phone, phone_normalized)
                   VALUES (?, ?, ?, ?)""",
                (user_id, full_name, primary_phone, _normalize_phone(primary_phone or "")),
            )
            customer_id = int(cursor.lastrowid)
            counts["imported_customers"] += 1

            for phone, normalized in zip(phones[1:], normalized_phones[1:]):
                connection.execute(
                    """INSERT INTO customer_phones (customer_id, phone, phone_normalized)
                       VALUES (?, ?, ?)""",
                    (customer_id, phone, normalized),
                )
                counts["imported_extra_phones"] += 1

            car_ids: list[int] = []
            for car in decision.get("cars", []):  # type: ignore[assignment]
                car = dict(car)
                plate = car.get("plate_number")
                plate_normalized = re.sub(r"[^0-9A-ZА-Я]", "", str(plate).upper()) if plate else None
                car_cursor = connection.execute(
                    """INSERT INTO cars
                       (user_id, customer_id, brand, model, plate_number, plate_normalized)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (user_id, customer_id, car["brand"], car["model"], plate, plate_normalized),
                )
                car_id = int(car_cursor.lastrowid)
                car_ids.append(car_id)
                counts["imported_cars"] += 1
                connection.execute(
                    """INSERT INTO audit_log (user_id, entity_type, entity_id, action, details)
                       VALUES (?, 'car', ?, 'imported_reviewed', 'source=google_contacts')""",
                    (user_id, car_id),
                )

            note = decision.get("note")
            if note:
                connection.execute(
                    """INSERT INTO customer_notes (customer_id, note_text, source)
                       VALUES (?, ?, 'google_contacts_reviewed')""",
                    (customer_id, str(note)),
                )
            for offset, source_index in enumerate(source_indices):
                connection.execute(
                    """INSERT INTO contact_imports
                       (user_id, source_fingerprint, source_index, customer_id, car_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (user_id, source_fingerprint, source_index, customer_id,
                     car_ids[min(offset, len(car_ids) - 1)] if car_ids else None),
                )
            connection.execute(
                """INSERT INTO audit_log (user_id, entity_type, entity_id, action, details)
                   VALUES (?, 'customer', ?, 'imported_reviewed', 'source=google_contacts')""",
                (user_id, customer_id),
            )
        connection.commit()
        return counts
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a read-only Apex CRM contact import preview")
    parser.add_argument("vcf", type=Path)
    parser.add_argument("--db", type=Path, default=Path("workshop.sqlite3"))
    parser.add_argument("--telegram-id", type=int, required=True)
    parser.add_argument("--output", type=Path, default=Path("contact_import_preview.json"))
    parser.add_argument("--apply", action="store_true", help="Back up the DB and import safe new contacts")
    parser.add_argument("--backup-dir", type=Path, default=Path("backups"))
    args = parser.parse_args()
    preview = build_preview(args.vcf, args.db, args.telegram_id)
    args.output.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(preview["summary"], ensure_ascii=False, indent=2))
    print(f"Preview written to {args.output.resolve()}")
    if args.apply:
        backup = create_backup(args.db, args.backup_dir)
        verify_backup(backup)
        Database(args.db).initialize()
        fingerprint = hashlib.sha256(args.vcf.read_bytes()).hexdigest()
        result = apply_preview(preview, args.db, args.telegram_id, fingerprint)
        print(f"Verified backup: {backup.resolve()}")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
