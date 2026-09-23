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


class OrderHistory(Base):
    __tablename__ = 'order_history'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(20))
    final_quantity: Mapped[float] = mapped_column(Float)
    calculation_metadata: Mapped[str] = mapped_column(Text)
    archived_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class EditorDraft(Base):
    __tablename__ = 'editor_draft'

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    datasets_json: Mapped[str] = mapped_column(Text, default='{}')
    buffer_json: Mapped[str] = mapped_column(Text, default='{}')
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class InventoryMovement(Base):
    __tablename__ = 'inventory_movement'

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    occurred_at: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ProductCatalog(Base):
    __tablename__ = 'product_catalog'

    sku: Mapped[str] = mapped_column(String(180), primary_key=True)
    product_name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(180), default='Other')
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    active: Mapped[bool] = mapped_column(default=True)


engine = create_engine('sqlite:///./stockpilot.db', connect_args={'check_same_thread': False})


def init_db() -> None:
    Base.metadata.create_all(engine)


def save_recommendations(rows: list[dict]) -> None:
    with Session(engine) as session:
        for row in rows:
            audit = session.get(OrderAudit, row['id']) or OrderAudit(id=row['id'])
            prior_metadata = json.loads(audit.calculation_metadata or '{}')
            same_dataset = prior_metadata.get('dataset_signature') == row['metadata'].get('dataset_signature')
            if audit.status in {'ADJUSTED', 'APPROVED'} and same_dataset:
                row['status'] = audit.status
                row['final_quantity'] = audit.final_quantity
                row['total_cost_kzt'] = round(audit.final_quantity * row['unit_cost'], 2)
                continue
            if audit.status in {'ADJUSTED', 'APPROVED'} and not same_dataset:
                session.add(OrderHistory(order_id=audit.id, status=audit.status, final_quantity=audit.final_quantity, calculation_metadata=audit.calculation_metadata))
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


def read_order_history() -> list[dict]:
    with Session(engine) as session:
        entries = session.scalars(select(OrderHistory).order_by(OrderHistory.archived_at.desc())).all()
        return [{'id': entry.id, 'order_id': entry.order_id, 'status': entry.status,
                 'final_quantity': entry.final_quantity, 'metadata': json.loads(entry.calculation_metadata),
                 'archived_at': entry.archived_at.isoformat()} for entry in entries]


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient='records', date_format='iso'))


def _upsert_catalog(session: Session, products: pd.DataFrame) -> None:
    for row in _frame_records(products):
        sku = str(row.get('sku') or '').strip()
        if not sku:
            continue
        item = session.get(ProductCatalog, sku) or ProductCatalog(sku=sku)
        item.product_name = str(row.get('product_name') or sku)
        item.category = str(row.get('category') or 'Other')
        item.unit_price = float(row.get('unit_price') or 0)
        item.active = bool(row.get('active', True))
        session.add(item)


def load_product_catalog() -> pd.DataFrame:
    with Session(engine) as session:
        rows = session.scalars(select(ProductCatalog).order_by(ProductCatalog.sku)).all()
        return pd.DataFrame([{'sku': row.sku, 'product_name': row.product_name,
                              'category': row.category, 'unit_price': row.unit_price,
                              'active': row.active} for row in rows],
                            columns=['sku', 'product_name', 'category', 'unit_price', 'active'])


def save_datasets_draft(datasets: dict[str, pd.DataFrame]) -> None:
    payload = {name: _frame_records(frame) for name, frame in datasets.items()}
    with Session(engine) as session:
        draft = session.get(EditorDraft, 'current') or EditorDraft(id='current')
        draft.datasets_json = json.dumps(payload, ensure_ascii=False)
        session.add(draft)
        _upsert_catalog(session, datasets.get('products', pd.DataFrame()))
        session.commit()


def save_inventory_movement(datasets: dict[str, pd.DataFrame], movement: dict[str, Any]) -> None:
    payload = {name: _frame_records(frame) for name, frame in datasets.items()}
    with Session(engine) as session:
        if session.get(InventoryMovement, movement['id']):
            raise ValueError('Movement already exists')
        draft = session.get(EditorDraft, 'current') or EditorDraft(id='current')
        draft.datasets_json = json.dumps(payload, ensure_ascii=False)
        session.add(draft)
        _upsert_catalog(session, datasets.get('products', pd.DataFrame()))
        session.add(InventoryMovement(id=movement['id'], kind=movement['kind'],
                                      occurred_at=movement['date'],
                                      payload_json=json.dumps(movement, ensure_ascii=False)))
        session.commit()


def read_inventory_movement(movement_id: str) -> dict[str, Any] | None:
    with Session(engine) as session:
        row = session.get(InventoryMovement, movement_id)
        return json.loads(row.payload_json) if row else None


def read_inventory_movements(limit: int | None = 100) -> list[dict[str, Any]]:
    with Session(engine) as session:
        query = select(InventoryMovement).order_by(InventoryMovement.created_at.desc())
        rows = session.scalars(query.limit(limit) if limit is not None else query).all()
        return [json.loads(row.payload_json) for row in rows]


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
