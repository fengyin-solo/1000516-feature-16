"""故障处置接口：维护处置单，覆盖受理处置、提交验收、确认验收等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.dispose import DisposeService

router = APIRouter(prefix="/api/dispose", tags=["故障处置"])

service = DisposeService()

LIST_FIELDS = ["处置单号", "关联故障", "处置措施", "更换器材", "处置人员", "完成时间", "验收人员", "处置状态"]
STATUSES = ["待受理", "处置中", "待验收", "已验收"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按处置单号检索"),
    status: str | None = Query(default=None, description="待受理、处置中、待验收、已验收"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按处置单号与状态过滤故障处置列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/measure-history")
def measure_history(
    keyword: str | None = Query(default=None, description="按关联故障或措施内容检索"),
) -> dict[str, Any]:
    """往期处置措施清单：新单据可以直接带出，不用每次重敲。"""
    return {"items": service.measure_history(keyword=keyword)}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条处置单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"处置单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条处置单，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="处置单已登记", entry=entry)


@router.post("/{entry_id}/process", response_model=ActionResult)
def save_process(entry_id: int, payload: EntryPayload) -> ActionResult:
    """保存处置过程（处置措施 + 更换器材明细）；规格与领用记录对不上、单据已验收都会被拦下。"""
    entry, message = service.save_process(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条处置单执行受理处置、提交验收、确认验收；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出故障处置清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "dispose", "total": total, "items": items}
