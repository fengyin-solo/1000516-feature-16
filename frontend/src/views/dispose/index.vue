<template>
  <section class="page" data-module="dispose">
    <header class="page-head">
      <div>
        <h2>故障处置管理</h2>
        <p class="page-desc">维护处置单，围绕处置单号、关联故障、处置措施、更换器材做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记处置单</button>
        <button class="btn" type="button" @click="exportRows">导出故障处置清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="String(row.id)">
          <tr>
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="toggleEditor(row)">
                {{ expandedId === Number(row.id) ? '收起过程' : '处置过程' }}
              </button>
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="expandedId === Number(row.id)">
            <td :colspan="columns.length + 1">
              <div class="process-editor">
                <div class="process-head">
                  <strong>处置过程 · {{ row['处置单号'] }}</strong>
                  <span v-if="isVerified(row)" class="verified-hint">已验收，仅供查看，不能再改</span>
                </div>
                <label class="process-field">
                  <span>处置措施</span>
                  <textarea
                    v-model="drafts[String(row.id)].measure"
                    rows="3"
                    :disabled="isVerified(row)"
                    placeholder="记录本次处置采取的措施"
                  ></textarea>
                </label>
                <label v-if="!isVerified(row)" class="process-field">
                  <span>从往期单据带出</span>
                  <select @change="applyHistory(row, ($event.target as HTMLSelectElement).value)">
                    <option value="">选择一条往期处置措施…</option>
                    <option v-for="item in historyOptions" :key="item" :value="item">{{ item }}</option>
                  </select>
                </label>
                <div class="process-field">
                  <span>更换器材（按领用记录核对）</span>
                  <table class="parts-table">
                    <thead>
                      <tr><th>器材名称</th><th>器材规格</th><th>数量</th><th v-if="!isVerified(row)"></th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="(part, index) in drafts[String(row.id)].parts" :key="index">
                        <td>
                          <select
                            v-model="part.器材名称"
                            :disabled="isVerified(row)"
                            @change="part.器材规格 = ''"
                          >
                            <option value="">选择器材</option>
                            <option v-for="name in spareNames" :key="name" :value="name">{{ name }}</option>
                          </select>
                        </td>
                        <td>
                          <select v-model="part.器材规格" :disabled="isVerified(row)">
                            <option value="">选择规格</option>
                            <option v-for="spec in specsFor(part.器材名称)" :key="spec" :value="spec">{{ spec }}</option>
                          </select>
                        </td>
                        <td>
                          <input
                            v-model.number="part.数量"
                            type="number"
                            min="0"
                            :disabled="isVerified(row)"
                          />
                        </td>
                        <td v-if="!isVerified(row)">
                          <button class="link" type="button" @click="drafts[String(row.id)].parts.splice(index, 1)">移除</button>
                        </td>
                      </tr>
                      <tr v-if="!drafts[String(row.id)].parts.length">
                        <td :colspan="isVerified(row) ? 3 : 4" class="empty-state">本次处置未更换器材</td>
                      </tr>
                    </tbody>
                  </table>
                  <button v-if="!isVerified(row)" class="btn ghost" type="button" @click="addPart(row)">添加器材</button>
                </div>
                <div v-if="!isVerified(row)" class="process-actions">
                  <button class="btn primary" type="button" @click="saveProcess(row)">保存处置过程</button>
                  <span class="draft-hint">草稿已自动保留，切换到其他处置单不会丢</span>
                </div>
              </div>
            </td>
          </tr>
        </template>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无故障处置数据，可先登记处置单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条故障处置记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>
type PartRow = { 器材名称: string; 器材规格: string; 数量: number }
type Draft = { measure: string; parts: PartRow[] }

const ENDPOINT = '/api/dispose'
const DRAFT_KEY = 'dispose-process-drafts'
const columns = ["处置单号", "关联故障", "处置措施", "更换器材", "处置人员", "完成时间", "验收人员", "处置状态"]
const actions = ["受理处置", "提交验收", "确认验收"]
const statuses = ["待受理", "处置中", "待验收", "已验收"]
const stats = [{"label": "待受理处置", "value": 0}, {"label": "处置中单据", "value": 0}, {"label": "本月验收单数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const expandedId = ref<number | null>(null)
const historyOptions = ref<string[]>([])
const spareRows = ref<Row[]>([])
const spareNames = ref<string[]>([])

// 每张处置单一稿：切到别的单据再回来，填了一半的内容还在；会话内刷新也不丢
const drafts = reactive<Record<string, Draft>>(loadDrafts())
watch(drafts, () => sessionStorage.setItem(DRAFT_KEY, JSON.stringify(drafts)), { deep: true })

function loadDrafts(): Record<string, Draft> {
  try {
    return JSON.parse(sessionStorage.getItem(DRAFT_KEY) ?? '{}') as Record<string, Draft>
  } catch {
    return {}
  }
}

function isVerified(row: Row) {
  return row.status === '已验收'
}

function ensureDraft(row: Row): Draft {
  const key = String(row.id)
  if (!drafts[key]) {
    const parts = Array.isArray(row['更换器材明细']) ? row['更换器材明细'] : []
    drafts[key] = {
      measure: String(row['处置措施'] ?? ''),
      parts: parts.map((part: any) => ({
        器材名称: String(part?.器材名称 ?? ''),
        器材规格: String(part?.器材规格 ?? ''),
        数量: Number(part?.数量 ?? 0),
      })),
    }
  }
  return drafts[key]
}

function specsFor(name: string): string[] {
  const specs = spareRows.value
    .filter((spare) => spare['器材名称'] === name && spare.status !== '已退回')
    .map((spare) => String(spare['器材规格'] ?? ''))
  return [...new Set(specs)].filter(Boolean)
}

function addPart(row: Row) {
  ensureDraft(row).parts.push({ 器材名称: '', 器材规格: '', 数量: 1 })
}

function applyHistory(row: Row, measure: string) {
  if (measure) {
    ensureDraft(row).measure = measure
  }
}

async function toggleEditor(row: Row) {
  if (expandedId.value === Number(row.id)) {
    expandedId.value = null
    return
  }
  ensureDraft(row)
  expandedId.value = Number(row.id)
  const query = new URLSearchParams({ keyword: String(row['关联故障'] ?? '') }).toString()
  try {
    const response = await request(`${ENDPOINT}/measure-history?${query}`)
    if (response.ok) {
      const payload = await response.json()
      historyOptions.value = payload.items ?? []
    }
  } catch {
    historyOptions.value = []
  }
}

async function saveProcess(row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  const draft = ensureDraft(row)
  try {
    const response = await request(`${ENDPOINT}/${row.id}/process`, {
      method: 'POST',
      body: JSON.stringify({ 处置措施: draft.measure, 更换器材明细: draft.parts }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message ?? payload.detail ?? '处置过程保存未生效，请稍后重试')
    }
    noticeMessage.value = payload.message ?? '处置过程已保存'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '处置过程保存失败'
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '处置单登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message ?? payload.detail ?? '故障处置动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message ?? `处置单已${action}`
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '故障处置操作失败'
  }
}

async function loadSpares() {
  try {
    const response = await request('/api/spare?size=200')
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    spareRows.value = payload.items ?? []
    spareNames.value = [...new Set(spareRows.value
      .filter((spare) => spare.status !== '已退回')
      .map((spare) => String(spare['器材名称'] ?? ''))
      .filter(Boolean))]
  } catch {
    spareRows.value = []
    spareNames.value = []
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('处置单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '故障处置列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSpares()
})
</script>

<style scoped>
.process-editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}
.process-head {
  display: flex;
  gap: 12px;
  align-items: baseline;
}
.verified-hint {
  color: var(--muted);
  font-size: 12px;
}
.process-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
}
.process-field > span {
  color: var(--muted);
  font-size: 12px;
}
.process-field textarea,
.process-field select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font: inherit;
  max-width: 640px;
}
.parts-table {
  border-collapse: collapse;
  max-width: 640px;
}
.parts-table th,
.parts-table td {
  border: 1px solid var(--border);
  padding: 4px 8px;
  font-size: 13px;
}
.parts-table select,
.parts-table input {
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 6px;
  font: inherit;
}
.parts-table input {
  width: 72px;
}
.process-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.draft-hint {
  color: var(--muted);
  font-size: 12px;
}
.notice-text {
  color: #067647;
}
</style>
