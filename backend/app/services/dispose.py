"""故障处置业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import threading
from typing import Any

from app.store import store

MODULE = "dispose"
REQUIRED_FIELDS = ["处置单号", "关联故障", "处置措施"]
STATUS_ORDER = ["待受理", "处置中", "待验收", "已验收"]
ACTION_RULES = {"受理处置": "处置中", "提交验收": "待验收", "确认验收": "已验收"}
NEGATIVE_ACTIONS = []

# 保存处置过程、提交验收都是“读-改-写”同一张单据，加锁保证两个人同时提交也不会写出重复记录
PROCESS_LOCK = threading.Lock()


def _normalize_parts(raw: Any) -> list[dict[str, Any]]:
    """把前端提交的更换器材整理成统一结构，完全空白的行直接丢掉。"""
    parts: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return parts
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("器材名称") or "").strip()
        spec = str(item.get("器材规格") or "").strip()
        qty_raw = item.get("数量")
        if not name and not spec and qty_raw in (None, ""):
            continue
        try:
            qty = int(qty_raw)
        except (TypeError, ValueError):
            qty = 0
        parts.append({"器材名称": name, "器材规格": spec, "数量": max(qty, 0)})
    return parts


def _parts_summary(parts: list[dict[str, Any]]) -> str:
    if not parts:
        return "无"
    return "；".join(f"{part['器材名称']}（{part['器材规格'] or '规格未填'}）×{part['数量']}" for part in parts)


class DisposeService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("处置单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def measure_history(self, *, keyword: str | None = None) -> list[str]:
        """往期单据里出现过的处置措施，去重后供新单直接带出。"""
        measures: list[str] = []
        for row in store.rows(MODULE):
            text = str(row.get("处置措施") or "").strip()
            if not text or text in measures:
                continue
            if keyword and keyword not in str(row.get("关联故障") or "") and keyword not in text:
                continue
            measures.append(text)
        return measures

    def save_process(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """保存处置过程（处置措施 + 更换器材明细），保存前按领用记录核对器材规格。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"处置单 {entry_id} 不存在或已归档"
        if entry.get("status") == STATUS_ORDER[-1]:
            return None, f"处置单 {entry_id} 已验收，处置过程不能再改"
        measure = str(values.get("处置措施") or "").strip()
        parts = _normalize_parts(values.get("更换器材明细"))
        problem = self._check_parts(parts)
        if problem:
            return None, problem
        with PROCESS_LOCK:
            entry["处置措施"] = measure
            entry["更换器材明细"] = parts
            entry["更换器材"] = _parts_summary(parts)
        return entry, "处置过程已保存"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"处置单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于故障处置可执行范围"
        if entry.get("status") == STATUS_ORDER[-1]:
            return None, f"处置单 {entry_id} 已验收，不能再执行「{action}」"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if action == "提交验收":
            problem = self._submit_for_verify(entry)
            if problem:
                return None, problem
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"处置单已{action}"

    def _submit_for_verify(self, entry: dict[str, Any]) -> str | None:
        """提交验收前核对器材并把处置措施、更换器材同步到故障登记；返回 None 表示放行。"""
        with PROCESS_LOCK:
            if entry.get("已同步故障"):
                # 并发或重复提交：已经同步过，直接放行，不会在故障登记侧写出第二条
                return None
            measure = str(entry.get("处置措施") or "").strip()
            if not measure:
                return "提交验收前请先填写处置措施"
            parts = _normalize_parts(entry.get("更换器材明细"))
            problem = self._check_parts(parts)
            if problem:
                return problem
            fault = self._find_fault(entry.get("关联故障"))
            if fault is not None:
                records = [
                    record for record in fault.get("处置记录", [])
                    if record.get("处置单号") != entry.get("处置单号")
                ]
                records.append({
                    "处置单号": entry.get("处置单号"),
                    "处置措施": measure,
                    "更换器材": _parts_summary(parts),
                })
                fault["处置记录"] = records
                fault["处置措施"] = measure
                fault["更换器材"] = _parts_summary(parts)
            entry["已同步故障"] = True
            return None

    @staticmethod
    def _find_fault(fault_no: Any) -> dict[str, Any] | None:
        key = str(fault_no or "").strip()
        if not key:
            return None
        for row in store.rows("fault"):
            if str(row.get("故障编号") or "").strip() == key:
                return row
        return None

    @staticmethod
    def _check_parts(parts: list[dict[str, Any]]) -> str | None:
        """更换器材逐行对照领用记录：名称要有领用单，规格要和领用规格一致。"""
        spares = [row for row in store.rows("spare") if row.get("status") != "已退回"]
        for part in parts:
            name = part["器材名称"]
            if not name:
                return "更换器材里有没填器材名称的行，请补全后再保存"
            matched = [row for row in spares if str(row.get("器材名称") or "").strip() == name]
            if not matched:
                return f"器材「{name}」找不到领用记录，请先在器材领用中登记"
            specs = sorted({str(row.get("器材规格") or "").strip() for row in matched})
            if part["器材规格"] not in specs:
                return f"器材「{name}」的更换规格「{part['器材规格'] or '空'}」与领用记录对不上，可核对规格：{'、'.join(specs)}"
        return None
