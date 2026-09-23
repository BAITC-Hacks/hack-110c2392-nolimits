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


engine = create_engine('sqlite:///./stockpilot.db', connect_args={'check_same_thread': False})


def init_db() -> None:
    Base.metadata.create_all(engine)


def save_recommendations(rows: list[dict]) -> None:
    with Session(engine) as session:
        for row in rows:
            audit = session.get(OrderAudit, row['id']) or OrderAudit(id=row['id'])
            if audit.status in {'ADJUSTED', 'APPROVED'}:
                row['status'] = audit.status
                row['final_quantity'] = audit.final_quantity
                row['total_cost_kzt'] = round(audit.final_quantity * row['unit_cost'], 2)
                continue
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
