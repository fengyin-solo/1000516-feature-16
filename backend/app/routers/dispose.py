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


@router.get("/suggestions/measures")
def measure_suggestions(
    keyword: str | None = Query(default=None, description="按措施关键字过滤往期记录"),
    limit: int = Query(default=20, le=100),
) -> dict[str, Any]:
    """往期已录入处置措施的去重列表，供处置录入时直接带出，免去重复敲字。"""
    return {"items": service.measure_history(keyword=keyword, limit=limit)}


@router.get("/suggestions/spares")
def spare_suggestions(
    keyword: str | None = Query(default=None, description="按领用单号或器材名称过滤"),
) -> dict[str, Any]:
    """可核对的领用记录（已批准/已领用），更换器材按此清单核对名称与规格。"""
    return {"items": service.spare_candidates(keyword=keyword)}


@router.put("/{entry_id}/progress", response_model=ActionResult)
def save_progress(entry_id: int, payload: EntryPayload) -> ActionResult:
    """暂存处置措施与更换器材草稿；已验收单据只读，版本过期会被拦下。"""
    version = payload.values.pop("version", None) if payload.values else None
    expected_version = None if version is None or version == "" else int(version)
    entry, message = service.save_progress(entry_id, payload.values, expected_version)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="处置过程已暂存", entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出故障处置清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "dispose", "total": total, "items": items}


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


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条处置单执行受理处置、提交验收、确认验收。

    提交验收可随动作带上处置措施与更换器材；后端按领用记录核对规格、
    校验状态流转与版本，并在成功后同步到关联故障登记。
    """
    values = dict(payload.values)
    action = str(values.pop("action", "") or "").strip()
    version = values.pop("version", None)
    expected_version = None if version is None or version == "" else int(version)
    entry, message = service.run_action(entry_id, action, values, expected_version)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
