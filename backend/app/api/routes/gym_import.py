"""Owner-only initial member + historical subscription migration.

Preview and commit validate the same payload; no payment records are fabricated.
The upload is JSON carrying base64 CSV/XLSX to avoid multipart dependencies.
"""
from __future__ import annotations

import base64
import csv
import io
import re
import secrets
import zipfile
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath
from uuid import uuid4
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.auth import require_owner
from backend.app.db.session import get_db
from backend.app.models.audit_log import AuditLog
from backend.app.models.member import Member, MemberStatus
from backend.app.models.membership import MembershipPlan, Subscription, SubscriptionStatus
from backend.app.models.staff_user import StaffUser
from backend.app.schemas.operations import MemberInput
from backend.app.services.operations import gym_now

router = APIRouter(prefix='/setup/import', tags=['gym-import'])
MAX_BYTES = 2_000_000
MAX_ROWS = 2000
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
HEADERS = {
    'full_name': {'full_name', 'member_name', 'name', 'full name', 'member name'},
    'phone': {'phone', 'phone_number', 'mobile', 'mobile_number', 'phone number'},
    'email': {'email', 'email_address', 'email address'},
    'plan': {'plan', 'plan_name', 'membership_plan', 'current_plan', 'membership plan', 'current plan'},
    'starts_on': {'starts_on', 'start_date', 'subscription_start', 'start date', 'subscription start'},
    'expires_on': {'expires_on', 'expiry_date', 'end_date', 'subscription_expiry', 'expiry date', 'end date', 'subscription expiry'},
}

class ImportFile(BaseModel):
    filename: str = Field(max_length=160)
    content_base64: str = Field(max_length=2_800_000)


def err(code: str, message: str, status: int = 422):
    raise HTTPException(status_code=status, detail={'code': code, 'error': message})


def parse_date(raw: str) -> date:
    s = raw.strip()
    if not s:
        raise ValueError('Missing subscription date')
    if re.fullmatch(r'\d+(?:\.0+)?', s):
        value = int(float(s))
        if 1 <= value <= 100000:
            return date(1899, 12, 30) + timedelta(days=value)
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError('Use YYYY-MM-DD dates (or Excel date cells)')


def xlsx_rows(data: bytes) -> list[dict[str, str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = z.namelist()
            if len(members) > 400 or sum(i.file_size for i in z.infolist()) > 20_000_000:
                err('invalid_spreadsheet', 'Spreadsheet is too large')
            strings = []
            if 'xl/sharedStrings.xml' in members:
                root = ET.fromstring(z.read('xl/sharedStrings.xml'))
                strings = [''.join(t.text or '' for t in item.iter(NS+'t')) for item in root.findall(NS+'si')]
            sheet = 'xl/worksheets/sheet1.xml'
            if sheet not in members:
                sheets = sorted(p for p in members if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', p))
                if not sheets: err('invalid_spreadsheet', 'No worksheet found')
                sheet = sheets[0]
            root = ET.fromstring(z.read(sheet))
            matrix: list[list[str]] = []
            for row in root.iter(NS+'row'):
                result = {}
                for cell in row.findall(NS+'c'):
                    ref = cell.get('r', '')
                    col = re.match('[A-Z]+', ref)
                    if not col: continue
                    idx = 0
                    for char in col.group(): idx = idx * 26 + ord(char) - 64
                    v = cell.find(NS+'v')
                    inline = cell.find(NS+'is')
                    text = (v.text or '') if v is not None else ''.join(t.text or '' for t in inline.iter(NS+'t')) if inline is not None else ''
                    if cell.get('t') == 's' and text:
                        text = strings[int(text)]
                    result[idx-1] = text
                if result:
                    if max(result) > 50: err('invalid_spreadsheet', 'Too many columns')
                    matrix.append([result.get(i, '') for i in range(max(result)+1)])
                if len(matrix) > MAX_ROWS+1: err('too_many_rows', 'Maximum 2,000 rows per import')
            if not matrix: return []
            width = len(matrix[0]); headers = matrix[0]
            return [dict(zip(headers, row+[''] * max(0, width-len(row)))) for row in matrix[1:] if any(s.strip() for s in row)]
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, IndexError) as exc:
        err('invalid_spreadsheet', 'Unable to read XLSX file. Use a normal single-sheet Excel workbook or CSV.')


def read_rows(payload: ImportFile) -> list[dict[str, str]]:
    try:
        raw = base64.b64decode(payload.content_base64, validate=True)
    except Exception:
        err('invalid_file', 'File encoding is invalid')
    if len(raw) > MAX_BYTES: err('file_too_large', 'Maximum upload size is 2 MB')
    lower = payload.filename.lower()
    if lower.endswith('.csv'):
        try:
            data = raw.decode('utf-8-sig')
            if '\x00' in data: raise UnicodeError()
            rows = list(csv.DictReader(io.StringIO(data, newline='')))
        except (UnicodeError, csv.Error):
            err('invalid_csv', 'Use a UTF-8 CSV file')
    elif lower.endswith('.xlsx'):
        rows = xlsx_rows(raw)
    else:
        err('unsupported_file', 'Upload a .csv or .xlsx file')
    if not rows: err('empty_file', 'File has no member rows')
    if len(rows) > MAX_ROWS: err('too_many_rows', 'Maximum 2,000 members per import')
    canonical = {}
    for header in rows[0]:
        key = header.strip().casefold().replace('-', '_')
        for field, aliases in HEADERS.items():
            if key in aliases or key.replace('_',' ') in aliases:
                if field in canonical: err('duplicate_column', f'Duplicate {field} column')
                canonical[field] = header
    if not {'full_name', 'phone'}.issubset(canonical):
        err('missing_columns', 'File must contain Full Name and Phone columns')
    return [{field: str(row.get(header) or '').strip() for field,header in canonical.items()} for row in rows]


def analyze(payload: ImportFile, db: Session):
    rows = read_rows(payload)
    plans = {p.name.strip().casefold(): p for p in db.scalars(select(MembershipPlan)).all()}
    # Normalize first: existing rows may use +254, spaces or 07... formatting.
    normalized_phones = set()
    for row in rows:
        try:
            normalized_phones.add(MemberInput(full_name=row.get('full_name', ''), phone=row.get('phone', ''), email=row.get('email') or None).phone)
        except Exception:
            pass
    known = {m.phone: m for m in db.scalars(select(Member).where(Member.phone.in_(normalized_phones))).all()}
    today = gym_now(db).date()
    validated = []
    seen = set()
    for number, row in enumerate(rows, 2):
        errors = []
        try:
            member = MemberInput(full_name=row.get('full_name', ''), phone=row.get('phone', ''), email=row.get('email') or None)
        except Exception:
            member = None
            errors.append('Invalid name, Kenyan phone number or email')
        phone = member.phone if member else row.get('phone', '')
        if phone in seen: errors.append('Repeated phone number within file')
        seen.add(phone)
        existing = known.get(phone)
        if existing and member and existing.full_name.casefold() != member.full_name.casefold():
            errors.append('Phone already belongs to another member name')
        plan_label = row.get('plan', '')
        start_raw, end_raw = row.get('starts_on', ''), row.get('expires_on', '')
        plan = plans.get(plan_label.casefold()) if plan_label else None
        if plan_label and plan is None: errors.append('Unknown membership plan; create it in Plans first')
        starts = expires = None
        if plan_label or start_raw or end_raw:
            if not (plan_label and start_raw and end_raw):
                errors.append('Plan, start date and expiry date must all be supplied')
            else:
                try:
                    starts, expires = parse_date(start_raw), parse_date(end_raw)
                    if starts > expires: errors.append('Expiry date is before start date')
                except ValueError as ex:
                    errors.append(str(ex))
        if existing and starts and expires:
            overlap = db.scalar(select(Subscription.id).where(
                Subscription.member_id == existing.id,
                Subscription.status != SubscriptionStatus.CANCELLED.value,
                Subscription.starts_on <= expires,
                Subscription.expires_on >= starts).limit(1))
            if overlap: errors.append('Subscription overlaps an existing membership')
        validated.append({'row': number, 'name': row.get('full_name', ''), 'phone': phone,
            'plan': plan.name if plan else plan_label or None,
            'startsOn': starts.isoformat() if starts else None,
            'expiresOn': expires.isoformat() if expires else None,
            'action': 'update_subscription' if existing else 'create_member',
            'errors': errors, '_member': member, '_plan': plan, '_start': starts, '_expiry': expires, '_existing': existing})
    return validated, today


def public(results):
    return {'total': len(results), 'ready': sum(not r['errors'] for r in results),
            'invalid': sum(bool(r['errors']) for r in results),
            'rows': [{k:v for k,v in r.items() if not k.startswith('_')} for r in results]}


@router.post('/preview')
def preview(payload: ImportFile, _staff: StaffUser = Depends(require_owner), db: Session = Depends(get_db)):
    results, _ = analyze(payload, db)
    return public(results)


@router.post('/commit')
def commit(payload: ImportFile, staff: StaffUser = Depends(require_owner), db: Session = Depends(get_db)):
    # Locking prevents concurrent imports from silently double-creating subscriptions.
    db.execute(select(Member.id).limit(1).with_for_update()).all()
    results, today = analyze(payload, db)
    invalid = sum(bool(r['errors']) for r in results)
    if invalid:
        err('import_has_errors', f'{invalid} row(s) need correction before import')
    new_members = new_subscriptions = 0
    try:
        for row in results:
            member = row['_existing']
            if member is None:
                member_id = uuid4()
                details = row['_member']
                member = Member(id=member_id, member_number=f'MG-{member_id.hex[:12].upper()}',
                    full_name=details.full_name, phone=details.phone, email=details.email,
                    status=MemberStatus.ACTIVE.value, qr_token=secrets.token_urlsafe(32))
                db.add(member)
                db.flush()
                new_members += 1
            if row['_plan']:
                plan = row['_plan']
                db.add(Subscription(id=uuid4(), member_id=member.id, plan_id=plan.id,
                    plan_name=plan.name, monthly_price_kes=plan.monthly_price_kes,
                    starts_on=row['_start'], expires_on=row['_expiry'],
                    status=SubscriptionStatus.SCHEDULED.value if row['_start'] > today else SubscriptionStatus.ACTIVE.value,
                    created_by_staff_id=staff.id))
                new_subscriptions += 1
        db.add(AuditLog(actor_staff_id=staff.id, action='gym_import.completed', entity_type='gym_import',
            details={'rows': len(results), 'new_members': new_members, 'subscriptions': new_subscriptions,
                     'filename_extension': PurePosixPath(payload.filename).suffix.lower()}))
        db.commit()
    except IntegrityError:
        db.rollback()
        err('import_conflict', 'Records changed during import. Preview again and retry.', 409)
    except Exception:
        db.rollback()
        raise
    return {'importedMembers': new_members, 'importedSubscriptions': new_subscriptions, 'processedRows': len(results)}
