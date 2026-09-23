from __future__ import annotations

import json
from datetime import datetime, timezone

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
