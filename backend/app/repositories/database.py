from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import DateTime, Float, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class OrderAudit(Base):
    __tablename__ = 'order_audit'

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default='DRAFT')
    final_quantity: Mapped[float] = mapped_column(Float, default=0)
    calculation_metadata: Mapped[str] = mapped_column(Text, default='{}')
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class EditorDraft(Base):
    __tablename__ = 'editor_draft'

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    datasets_json: Mapped[str] = mapped_column(Text, default='{}')
    buffer_json: Mapped[str] = mapped_column(Text, default='{}')
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


engine = create_engine('sqlite:///./stockpilot.db', connect_args={'check_same_thread': False})


def init_db() -> None:
    Base.metadata.create_all(engine)


def save_recommendations(rows: list[dict]) -> None:
    with Session(engine) as session:
        for row in rows:
            audit = session.get(OrderAudit, row['id']) or OrderAudit(id=row['id'])
            audit.status = row['status']
            audit.final_quantity = row['final_quantity']
            audit.calculation_metadata = json.dumps(row['metadata'], default=str)
            session.add(audit)
        session.commit()


def update_order(order_id: str, *, status: str | None = None, final_quantity: float | None = None) -> None:
    with Session(engine) as session:
        audit = session.get(OrderAudit, order_id)
        if not audit:
            return
        if status:
            audit.status = status
        if final_quantity is not None:
            audit.final_quantity = final_quantity
        session.commit()


def read_order(order_id: str) -> dict | None:
    with Session(engine) as session:
        audit = session.scalar(select(OrderAudit).where(OrderAudit.id == order_id))
        if not audit:
            return None
        return {'id': audit.id, 'status': audit.status, 'final_quantity': audit.final_quantity, 'metadata': json.loads(audit.calculation_metadata)}


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient='records', date_format='iso'))


def save_datasets_draft(datasets: dict[str, pd.DataFrame]) -> None:
    payload = {name: _frame_records(frame) for name, frame in datasets.items()}
    with Session(engine) as session:
        draft = session.get(EditorDraft, 'current') or EditorDraft(id='current')
        draft.datasets_json = json.dumps(payload, ensure_ascii=False)
        session.add(draft)
        session.commit()


def load_datasets_draft() -> dict[str, pd.DataFrame] | None:
    with Session(engine) as session:
        draft = session.get(EditorDraft, 'current')
        if not draft or not draft.datasets_json or draft.datasets_json == '{}':
            return None
        try:
            payload = json.loads(draft.datasets_json)
            return {name: pd.DataFrame(rows) for name, rows in payload.items()}
        except (TypeError, ValueError, json.JSONDecodeError):
            return None


def save_editor_buffer(dataset: str, row: dict[str, Any], row_id: int | None = None) -> None:
    with Session(engine) as session:
        draft = session.get(EditorDraft, 'current') or EditorDraft(id='current')
        draft.buffer_json = json.dumps({'dataset': dataset, 'row': row, 'row_id': row_id}, ensure_ascii=False, default=str)
        session.add(draft)
        session.commit()


def read_editor_buffer() -> dict[str, Any] | None:
    with Session(engine) as session:
        draft = session.get(EditorDraft, 'current')
        if not draft or not draft.buffer_json or draft.buffer_json == '{}':
            return None
        try:
            return json.loads(draft.buffer_json)
        except json.JSONDecodeError:
            return None


def clear_editor_buffer() -> None:
    with Session(engine) as session:
        draft = session.get(EditorDraft, 'current')
        if draft:
            draft.buffer_json = '{}'
            session.add(draft)
            session.commit()


def draft_updated_at() -> str | None:
    with Session(engine) as session:
        draft = session.get(EditorDraft, 'current')
        return draft.updated_at.isoformat() if draft and draft.updated_at else None
