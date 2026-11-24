"""闸口放行：岸桥禁放第12号（甲路径）。

无岸桥计划泊位行时，放行写口原子拒收并记 `crane_release_deviation`
（岸桥禁放偏航），正式册零增。有泊位行时占闸口锁并钉住 `crane_job_id`，
正式册行因此有晋升凭证；票态由账实口径独立推断，不再以“票已放行”兜底。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from crane_gate import (
    BAN_CODE,
    annotate_releases,
    annotate_tickets,
    crane_plan_ready,
)
from db import connect, now_iso, write_audit
from locks import claim_lock, release
from models import GateReleaseIn
from validators import validate_no_open_overload, validate_ticket_mutable

router = APIRouter(tags=["gate"])


@router.get("/api/gate/releases")
def list_releases(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT g.*, t.ticket_code, t.vehicle_plate, l.lane_code,
                      j.id AS crane_job_found, j.berth_slot AS release_berth_slot,
                      j.status AS release_job_status
               FROM gate_releases g
               JOIN weigh_tickets t ON t.id=g.ticket_id
               JOIN weigh_lanes l ON l.id=g.lane_id
               LEFT JOIN crane_plan_jobs j ON j.id=g.crane_job_id
               ORDER BY g.id DESC"""
        ).fetchall()
        items = annotate_releases(conn, [dict(r) for r in rows])
        return {"items": items, "ban_code": BAN_CODE}


@router.get("/api/gate/releasable")
def list_releasable(authorization: AuthHeader = None):
    """放行页下拉与车道页共用：只有泊位计划齐套的票才可抬杆。"""
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT t.*, l.lane_code FROM weigh_tickets t
               JOIN weigh_lanes l ON l.id=t.lane_id
               WHERE t.status='已裁定' ORDER BY t.id DESC"""
        ).fetchall()
        items = annotate_tickets(conn, [dict(r) for r in rows])
        return {
            "items": [x for x in items if x["releasable"]],
            # 只列“票态已裁定却被泊位计划挡住”的票，封闸/挂起票不在此列。
            "blocked": [
                x
                for x in items
                if x["status"] == "已裁定" and not x["releasable"]
            ],
            "ban_code": BAN_CODE,
        }


@router.post("/api/gate/release")
def release_gate(body: GateReleaseIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    lock_key = f"gate:{body.ticket_id}"
    with connect() as conn:
        ticket = conn.execute(
            """SELECT t.*, l.id lane_id FROM weigh_tickets t
               JOIN weigh_lanes l ON l.id=t.lane_id WHERE t.id=?""",
            (body.ticket_id,),
        ).fetchone()
        if not ticket:
            raise HTTPException(404, "过磅票不存在")

        plan = crane_plan_ready(conn, body.ticket_id)
        if not plan["ready"]:
            # 甲路径：原子拒收，正式册零增。只记偏离纪要的审计，不占争用痕。
            write_audit(
                conn,
                user,
                "crane_release_deviation",
                ticket["ticket_code"],
                {
                    "ban_code": BAN_CODE,
                    "ticket_id": body.ticket_id,
                    "reason": plan["reason"],
                    "official_release_delta": 0,
                    "path": "甲：放行写口原子拒收",
                },
            )
            conn.commit()
            raise HTTPException(
                409,
                f"{BAN_CODE}：无岸桥计划泊位行，放行拒收；正式册零增",
            )

        if not claim_lock(conn, lock_key, user):
            write_audit(
                conn,
                user,
                "gate_release_contention",
                ticket["ticket_code"],
                {"lock_key": lock_key, "ban_code": BAN_CODE},
            )
            conn.commit()
            raise HTTPException(
                409, "争用：同票已有会话占闸口锁，后到只记争用痕，不增放行"
            )

        try:
            validate_ticket_mutable(dict(ticket))
            if ticket["status"] not in ("已裁定", "旁路挂起"):
                raise HTTPException(409, "票态不允许放行")
            if ticket["status"] == "旁路挂起":
                raise HTTPException(409, "旁路挂起须先闭环")
            validate_no_open_overload(conn, body.ticket_id)
            exists = conn.execute(
                "SELECT id FROM gate_releases WHERE ticket_id=? AND status='已放行'",
                (body.ticket_id,),
            ).fetchone()
            if exists:
                raise HTTPException(409, "已放行")
            now = now_iso()
            ref = f"PL-{ticket['ticket_code']}-{now[:10]}"
            cur = conn.execute(
                """INSERT INTO gate_releases(ticket_id,lane_id,release_ref,status,
                   officer,released_at,crane_job_id,crane_berth_slot)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    body.ticket_id,
                    ticket["lane_id"],
                    ref,
                    "已放行",
                    body.officer,
                    now,
                    plan["job_id"],
                    plan["berth_slot"],
                ),
            )
            conn.execute(
                "UPDATE weigh_tickets SET status='已放行' WHERE id=?",
                (body.ticket_id,),
            )
            write_audit(
                conn,
                user,
                "gate_release",
                ref,
                {
                    "release_id": cur.lastrowid,
                    "ticket_id": body.ticket_id,
                    "crane_job_id": plan["job_id"],
                    "berth_slot": plan["berth_slot"],
                    "ban_code": BAN_CODE,
                },
            )
            conn.commit()
            return {
                "id": cur.lastrowid,
                "release_ref": ref,
                "status": "已放行",
                "crane_job_id": plan["job_id"],
                "berth_slot": plan["berth_slot"],
            }
        except HTTPException:
            # 业务拒收也释放占用锁，只有真正落册的放行长期占闸。
            release(conn, lock_key, user)
            conn.commit()
            raise
