"""故障处置业务规则：状态流转、字段校验、领用核对与跨单同步都收在这里。

并发口径：FastAPI 的同步端点跑在线程池里，写操作用模块级锁串行化；
再叠加单据 version 乐观锁与状态流转守卫，保证两个人同时提交验收时
只有一个请求生效，处置措施与更换器材不会写出两份。
"""
from __future__ import annotations

import threading
from typing import Any

from app.store import store

MODULE = "dispose"
SPARE_MODULE = "spare"
FAULT_MODULE = "fault"
# 建单只需单号与关联故障；处置措施在处置阶段补录，不再要求建单时就填。
REQUIRED_FIELDS = ["处置单号", "关联故障"]
PROGRESS_FIELDS = ["处置措施", "更换器材", "处置人员", "完成时间", "验收人员"]
STATUS_ORDER = ["待受理", "处置中", "待验收", "已验收"]
FINAL_STATUS = "已验收"
# 只有这些状态的领用单可以作为更换器材的核对依据。
SPARE_USABLE_STATUS = ("已批准", "已领用")
# 每个动作允许的出发状态：越线流转（含重复提交）一律拦下。
ACTION_RULES: dict[str, dict[str, Any]] = {
    "受理处置": {"from": ("待受理",), "to": "处置中"},
    "提交验收": {"from": ("处置中",), "to": "待验收"},
    "确认验收": {"from": ("待验收",), "to": "已验收"},
}

_lock = threading.RLock()


def _ensure_meta(entry: dict[str, Any]) -> None:
    """老数据可能没有版本号与更换明细，读到时补齐。"""
    entry.setdefault("version", 0)
    entry.setdefault("更换明细", [])


def _as_int(value: Any, default: int = 1) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(number, 1)


def _normalize_items(raw: Any) -> list[dict[str, Any]]:
    """把前端提交的更换器材明细清洗成统一结构；空值行直接丢掉。"""
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        name = str(row.get("器材名称") or "").strip()
        spec = str(row.get("器材规格") or "").strip()
        order_no = str(row.get("领用单号") or "").strip()
        if not name and not spec and not order_no:
            continue
        items.append({
            "领用单号": order_no,
            "器材名称": name,
            "器材规格": spec,
            "数量": _as_int(row.get("数量"), 1),
        })
    return items


def _summarize_items(items: list[dict[str, Any]]) -> str:
    return "；".join(
        f"{item['器材名称']}/{item['器材规格']}×{item['数量']}" if item["器材规格"]
        else f"{item['器材名称']}×{item['数量']}"
        for item in items
    )


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
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            _ensure_meta(entry)
        return entry

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        with _lock:
            rows = store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
            entry["处置措施"] = ""
            entry["更换器材"] = ""
            entry["更换明细"] = []
            entry["status"] = STATUS_ORDER[0]
            entry["处置状态"] = STATUS_ORDER[0]
            entry["version"] = 0
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
        return entry, []

    # ---- 处置过程辅助数据 -------------------------------------------------

    def measure_history(self, keyword: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """往期处置措施去重列表：越近录入的排越前，供录入时直接带出。"""
        seen: dict[str, dict[str, Any]] = {}
        with _lock:
            rows = sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)), reverse=True)
            for row in rows:
                measure = str(row.get("处置措施") or "").strip()
                if not measure:
                    continue
                if keyword and keyword not in measure:
                    continue
                item = seen.get(measure)
                if item is None:
                    seen[measure] = {
                        "处置措施": measure,
                        "处置单号": row.get("处置单号", ""),
                        "完成时间": row.get("完成时间", ""),
                        "使用次数": 1,
                    }
                else:
                    item["使用次数"] = int(item["使用次数"]) + 1
        return list(seen.values())[:limit]

    def spare_candidates(self, keyword: str | None = None) -> list[dict[str, Any]]:
        """可用于核对的领用记录：只取已批准、已领用的单据。"""
        result: list[dict[str, Any]] = []
        with _lock:
            for row in store.rows(SPARE_MODULE):
                if row.get("status") not in SPARE_USABLE_STATUS:
                    continue
                order_no = str(row.get("领用单号", ""))
                name = str(row.get("器材名称", ""))
                if keyword and keyword not in order_no and keyword not in name:
                    continue
                result.append({
                    "领用单号": order_no,
                    "器材名称": name,
                    "器材规格": row.get("器材规格", ""),
                    "领用数量": row.get("领用数量", ""),
                    "领用人员": row.get("领用人员", ""),
                    "领用日期": row.get("领用日期", ""),
                    "领用状态": row.get("status", ""),
                })
        return result

    def _find_spare(self, name: str, spec: str) -> dict[str, Any] | None:
        for row in store.rows(SPARE_MODULE):
            if row.get("status") not in SPARE_USABLE_STATUS:
                continue
            if str(row.get("器材名称") or "").strip() == name \
                    and str(row.get("器材规格") or "").strip() == spec:
                return row
        return None

    # ---- 进度暂存 ---------------------------------------------------------

    def save_progress(
        self,
        entry_id: int,
        values: dict[str, Any],
        expected_version: int | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """暂存处置过程。草稿不做领用核对，保证填了一半也存得住。"""
        with _lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"处置单 {entry_id} 不存在或已归档"
            _ensure_meta(entry)
            if entry["status"] == FINAL_STATUS:
                return None, "处置单已验收，处置措施与更换器材不允许再修改"
            conflict = self._version_conflict(entry, expected_version)
            if conflict:
                return None, conflict
            self._apply_progress(entry, values)
            entry["version"] = int(entry["version"]) + 1
            return entry, ""

    def _apply_progress(self, entry: dict[str, Any], values: dict[str, Any]) -> None:
        for field in PROGRESS_FIELDS:
            if field in values:
                entry[field] = str(values.get(field) or "").strip()
        if "更换明细" in values:
            items = _normalize_items(values.get("更换明细"))
            entry["更换明细"] = items
            entry["更换器材"] = _summarize_items(items)

    @staticmethod
    def _version_conflict(entry: dict[str, Any], expected_version: int | None) -> str:
        if expected_version is None:
            return ""
        if int(expected_version) != int(entry.get("version", 0)):
            return "该处置单已被他人更新，请刷新后查看最新内容再提交"
        return ""

    def _check_replacements(self, entry: dict[str, Any]) -> list[str]:
        """更换器材逐条与领用记录核对名称+规格，返回对不上的说明列表。"""
        problems: list[str] = []
        items = _normalize_items(entry.get("更换明细"))
        for item in items:
            label = f"{item['器材名称']}／{item['器材规格'] or '未填规格'}"
            if not item["器材名称"] or not item["器材规格"]:
                problems.append(f"{label}：器材名称和规格必须填写完整")
                continue
            spare = self._find_spare(item["器材名称"], item["器材规格"])
            if spare is None:
                problems.append(f"{label}：领用记录中没有名称与规格一致的已批准/已领用器材")
        return problems

    def _sync_to_fault(self, entry: dict[str, Any]) -> None:
        """提交验收后把处置措施与更换器材同步到关联故障登记侧。"""
        fault_no = str(entry.get("关联故障") or "").strip()
        if not fault_no:
            return
        for fault in store.rows(FAULT_MODULE):
            if str(fault.get("故障编号") or "").strip() != fault_no:
                continue
            fault["处置措施"] = entry.get("处置措施", "")
            fault["更换器材"] = entry.get("更换器材", "")
            fault["关联处置单"] = entry.get("处置单号", "")
            break

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        with _lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"处置单 {entry_id} 不存在或已归档"
            _ensure_meta(entry)
            if action not in ACTION_RULES:
                return None, f"动作「{action}」不属于故障处置可执行范围"

            rule = ACTION_RULES[action]
            current = str(entry.get("status"))
            # 已验收是终态：任何动作（含再点一次确认验收）都拒绝，老单据只读。
            if current == FINAL_STATUS:
                return None, "处置单已验收，不能再执行任何处置动作"
            if current not in rule["from"]:
                return None, f"处置单当前为「{current}」，不能执行「{action}」，请刷新后查看最新状态"

            conflict = self._version_conflict(entry, expected_version)
            if conflict:
                return None, conflict

            # 弹窗里可能边受理边录入：任何动作都先把带过来的进度落库，
            # 但只有提交验收做措施必填与领用核对。
            self._apply_progress(entry, values)

            if action == "提交验收":
                if not str(entry.get("处置措施") or "").strip():
                    return None, "处置措施尚未填写，不能提交验收"
                problems = self._check_replacements(entry)
                if problems:
                    return None, "更换器材与领用记录核对不一致：" + "；".join(problems)

            if action == "确认验收":
                verifier = str(values.get("验收人员") or "").strip()
                if verifier:
                    entry["验收人员"] = verifier

            target = rule["to"]
            entry["status"] = target
            entry["处置状态"] = target
            entry["pending"] = target != FINAL_STATUS
            entry["abnormal"] = False
            entry["version"] = int(entry["version"]) + 1

            if action == "提交验收":
                # 同步在锁内完成：并发双提交只有一个请求能走到这里，故障侧只写一次。
                self._sync_to_fault(entry)
            return entry, f"处置单已{action}"
