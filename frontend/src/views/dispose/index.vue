<template>
  <section class="page" data-module="dispose">
    <header class="page-head">
      <div>
        <h2>故障处置管理</h2>
        <p class="page-desc">维护处置单，处置措施可从往期单据带出，更换器材按领用记录核对；提交验收后同步到故障登记。</p>
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
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openEditor(row)">
              {{ row.status === '已验收' ? '查看处置' : '处置录入' }}
            </button>
            <template v-if="row.status === '待受理'">
              <button class="link" type="button" @click="runAction('受理处置', row)">受理处置</button>
            </template>
            <template v-else-if="row.status === '待验收'">
              <button class="link" type="button" @click="runAction('确认验收', row)">确认验收</button>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无故障处置数据，可先登记处置单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条故障处置记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 处置录入弹窗：中途切换处置单再回来，本地草稿仍在 -->
    <div v-if="editorVisible" class="modal-mask" @click.self="closeEditor">
      <div class="modal">
        <header class="modal-head">
          <div>
            <h3>{{ form.status === '已验收' ? '处置详情（已验收，只读）' : `处置录入 · ${form.处置单号}` }}</h3>
            <p class="page-desc">关联故障：{{ form.关联故障 }}　当前状态：{{ form.status }}</p>
          </div>
          <button class="btn ghost" type="button" @click="closeEditor">关闭</button>
        </header>

        <div v-if="draftHint" class="draft-banner">
          <span>{{ draftHint }}</span>
          <button class="link" type="button" @click="discardDraft">放弃未提交草稿</button>
        </div>

        <div class="form-block">
          <label class="form-label">
            <span>处置措施</span>
            <textarea
              v-model="form.处置措施"
              rows="3"
              :readonly="form.status === '已验收'"
              placeholder="可从下方往期措施直接带出，或自行填写"
            ></textarea>
          </label>

          <div v-if="form.status !== '已验收'" class="suggest-box">
            <div class="suggest-head">
              <strong>往期处置措施</strong>
              <input v-model="measureKeyword" placeholder="按关键字过滤往期措施" @input="loadMeasures" />
            </div>
            <div class="suggest-list">
              <button
                v-for="item in measureOptions"
                :key="item.处置措施"
                class="suggest-chip"
                type="button"
                :title="`来源 ${item.处置单号}`"
                @click="applyMeasure(item.处置措施)"
              >
                <span>{{ item.处置措施 }}</span>
                <em>{{ item.处置单号 }} · 用过 {{ item.使用次数 }} 次</em>
              </button>
              <span v-if="!measureOptions.length" class="empty-inline">暂无匹配的往期措施</span>
            </div>
          </div>
        </div>

        <div class="form-block">
          <div class="form-row-head">
            <strong>更换器材（按领用记录核对名称与规格）</strong>
            <button v-if="form.status !== '已验收'" class="btn" type="button" @click="addItem">添加器材</button>
          </div>
          <table class="item-table">
            <thead>
              <tr>
                <th>领用单号</th>
                <th>器材名称</th>
                <th>器材规格</th>
                <th>数量</th>
                <th v-if="form.status !== '已验收'"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in form.更换明细" :key="index">
                <td>
                  <select
                    v-if="form.status !== '已验收'"
                    :value="item.领用单号"
                    @change="bindSpare(index, ($event.target as HTMLSelectElement).value)"
                  >
                    <option value="">手动录入或选择领用单</option>
                    <option
                      v-for="spare in spareOptions"
                      :key="spare.领用单号"
                      :value="spare.领用单号"
                    >
                      {{ spare.领用单号 }}｜{{ spare.器材名称 }}｜{{ spare.器材规格 }}（{{ spare.领用状态 }}）
                    </option>
                  </select>
                  <span v-else>{{ item.领用单号 || '—' }}</span>
                </td>
                <td><input v-model="item.器材名称" :readonly="form.status === '已验收'" placeholder="器材名称" /></td>
                <td><input v-model="item.器材规格" :readonly="form.status === '已验收'" placeholder="必须与领用规格一致" /></td>
                <td>
                  <input
                    v-model.number="item.数量"
                    type="number"
                    min="1"
                    :readonly="form.status === '已验收'"
                    class="qty-input"
                  />
                </td>
                <td v-if="form.status !== '已验收'">
                  <button class="link danger" type="button" @click="removeItem(index)">移除</button>
                </td>
              </tr>
              <tr v-if="!form.更换明细.length">
                <td :colspan="form.status === '已验收' ? 4 : 5" class="empty-state">未登记更换器材</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="form-grid">
          <label class="form-label">
            <span>处置人员</span>
            <input v-model="form.处置人员" :readonly="form.status === '已验收'" placeholder="处置人员" />
          </label>
          <label class="form-label">
            <span>完成时间</span>
            <input v-model="form.完成时间" :readonly="form.status === '已验收'" placeholder="如 2026-09-25 10:30" />
          </label>
          <label class="form-label">
            <span>验收人员</span>
            <input v-model="form.验收人员" :readonly="form.status !== '待验收'" placeholder="确认验收时填写" />
          </label>
        </div>

        <p v-if="formError" class="error-text form-error">{{ formError }}</p>

        <footer v-if="form.status !== '已验收'" class="modal-foot">
          <button class="btn" type="button" :disabled="saving" @click="saveDraft">{{ saving ? '保存中…' : '暂存草稿' }}</button>
          <div class="modal-foot-right">
            <button
              v-if="form.status === '待受理'"
              class="btn primary"
              type="button"
              :disabled="saving"
              @click="submitForm('受理处置')"
            >受理处置</button>
            <button
              v-else-if="form.status === '处置中'"
              class="btn primary"
              type="button"
              :disabled="saving"
              @click="submitForm('提交验收')"
            >提交验收</button>
            <button
              v-else-if="form.status === '待验收'"
              class="btn primary"
              type="button"
              :disabled="saving"
              @click="submitForm('确认验收')"
            >确认验收</button>
          </div>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

interface ReplaceItem {
  领用单号: string
  器材名称: string
  器材规格: string
  数量: number
}

interface EditorForm {
  id: number
  status: string
  处置单号: string
  关联故障: string
  处置措施: string
  更换器材: string
  更换明细: ReplaceItem[]
  处置人员: string
  完成时间: string
  验收人员: string
}

interface MeasureOption {
  处置措施: string
  处置单号: string
  完成时间: string
  使用次数: number
}

interface SpareOption {
  领用单号: string
  器材名称: string
  器材规格: string
  领用数量: number | string
  领用人员: string
  领用日期: string
  领用状态: string
}

interface DraftPayload {
  form: EditorForm
  version: number
  savedAt: string
}

const ENDPOINT = '/api/dispose'
const DRAFT_PREFIX = 'dispose-draft:'
const columns = ["处置单号", "关联故障", "处置措施", "更换器材", "处置人员", "完成时间", "验收人员", "处置状态"]
const stats = [{"label": "待受理处置", "value": 0}, {"label": "处置中单据", "value": 0}, {"label": "本月验收单数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const editorVisible = ref(false)
const saving = ref(false)
const formError = ref('')
const form = ref<EditorForm>(emptyForm(0))
const serverVersion = ref<number | null>(null)
const measureOptions = ref<MeasureOption[]>([])
const spareOptions = ref<SpareOption[]>([])
const measureKeyword = ref('')
const draftHint = ref('')
let draftTimer: ReturnType<typeof setTimeout> | undefined

function emptyForm(id: number): EditorForm {
  return {
    id,
    status: '',
    处置单号: '',
    关联故障: '',
    处置措施: '',
    更换器材: '',
    更换明细: [],
    处置人员: '',
    完成时间: '',
    验收人员: '',
  }
}

function draftKey(id: number): string {
  return `${DRAFT_PREFIX}${id}`
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

async function readBody(response: Response): Promise<{ ok: boolean; message: string; entry?: Row }> {
  const body = (await response.json().catch(() => null)) as
    { ok?: boolean; message?: string; entry?: Row } | null
  return {
    ok: response.ok && body?.ok !== false,
    message: body?.message ?? '操作未生效，请稍后重试',
    entry: body?.entry,
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const result = await readBody(response)
    if (!result.ok) {
      throw new Error(result.message)
    }
    localStorage.removeItem(draftKey(Number(row.id)))
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '故障处置操作失败'
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

function payloadValues(): Record<string, unknown> {
  return {
    处置措施: form.value.处置措施,
    更换明细: form.value.更换明细,
    处置人员: form.value.处置人员,
    完成时间: form.value.完成时间,
    验收人员: form.value.验收人员,
  }
}

function scheduleLocalDraft() {
  if (form.value.status === '已验收') {
    return
  }
  if (draftTimer) {
    clearTimeout(draftTimer)
  }
  draftTimer = setTimeout(() => {
    const draft: DraftPayload = {
      form: form.value,
      version: serverVersion.value ?? 0,
      savedAt: new Date().toISOString(),
    }
    localStorage.setItem(draftKey(form.value.id), JSON.stringify(draft))
    refreshDraftHint(draft)
  }, 400)
}

function refreshDraftHint(draft?: DraftPayload) {
  const raw = draft ?? readLocalDraft(form.value.id)
  if (!raw) {
    draftHint.value = ''
    return
  }
  const time = new Date(raw.savedAt).toLocaleString()
  draftHint.value = `本机留有未提交草稿（${time} 暂存），已自动恢复。`
}

function readLocalDraft(id: number): DraftPayload | undefined {
  const raw = localStorage.getItem(draftKey(id))
  if (!raw) {
    return undefined
  }
  try {
    return JSON.parse(raw) as DraftPayload
  } catch {
    return undefined
  }
}

async function discardDraft() {
  localStorage.removeItem(draftKey(form.value.id))
  draftHint.value = ''
  // 恢复成服务端当前内容，保证放弃后不会再被本地草稿覆盖。
  try {
    const response = await request(`${ENDPOINT}/${form.value.id}`)
    const detail = (await response.json()) as Row
    form.value = toForm(detail)
    serverVersion.value = Number(detail.version ?? 0)
  } catch {
    formError.value = '服务端内容读取失败，请稍后重试'
  }
}

function toForm(entry: Row): EditorForm {
  const items = Array.isArray(entry['更换明细']) ? (entry['更换明细'] as unknown as ReplaceItem[]) : []
  return {
    id: Number(entry.id),
    status: String(entry.status ?? ''),
    处置单号: String(entry['处置单号'] ?? ''),
    关联故障: String(entry['关联故障'] ?? ''),
    处置措施: String(entry['处置措施'] ?? ''),
    更换器材: String(entry['更换器材'] ?? ''),
    更换明细: items.map((item) => ({
      领用单号: String(item.领用单号 ?? ''),
      器材名称: String(item.器材名称 ?? ''),
      器材规格: String(item.器材规格 ?? ''),
      数量: Number(item.数量 ?? 1),
    })),
    处置人员: String(entry['处置人员'] ?? ''),
    完成时间: String(entry['完成时间'] ?? ''),
    验收人员: String(entry['验收人员'] ?? ''),
  }
}

async function openEditor(row: Row) {
  formError.value = ''
  measureKeyword.value = ''
  editorVisible.value = true
  const [detail] = await Promise.all([
    request(`${ENDPOINT}/${row.id}`).then((r) => r.json()),
    loadMeasures(),
    loadSpares(),
  ])
  form.value = toForm(detail as Row)
  serverVersion.value = Number((detail as Row).version ?? 0)

  // 服务端数据为准；本机草稿只在仍有内容时恢复，避免把刚同步的正式内容盖掉。
  const draft = readLocalDraft(form.value.id)
  if (draft?.form && draft.version === serverVersion.value && draft.form.status !== '已验收') {
    const hasDraft = draft.form.处置措施.trim()
      || draft.form.更换明细.length
      || draft.form.处置人员.trim()
      || draft.form.完成时间.trim()
    if (hasDraft) {
      form.value = draft.form
      refreshDraftHint(draft)
    }
  }
}

// 表单内容一变就防抖写入本地草稿：中途切到别的处置单再回来不会丢。
watch(
  [
    () => form.value.处置措施,
    () => form.value.更换明细,
    () => form.value.处置人员,
    () => form.value.完成时间,
    () => form.value.验收人员,
  ],
  () => {
    if (editorVisible.value && form.value.status !== '已验收') {
      scheduleLocalDraft()
    }
  },
  { deep: true },
)

function closeEditor() {
  if (draftTimer) {
    clearTimeout(draftTimer)
    draftTimer = undefined
  }
  editorVisible.value = false
}

async function loadMeasures(): Promise<MeasureOption[]> {
  const keyword = measureKeyword.value.trim()
  const query = keyword ? `?keyword=${encodeURIComponent(keyword)}` : ''
  const response = await request(`${ENDPOINT}/suggestions/measures${query}`)
  const payload = (await response.json()) as { items: MeasureOption[] }
  measureOptions.value = payload.items ?? []
  return measureOptions.value
}

async function loadSpares(): Promise<SpareOption[]> {
  const response = await request(`${ENDPOINT}/suggestions/spares`)
  const payload = (await response.json()) as { items: SpareOption[] }
  spareOptions.value = payload.items ?? []
  return spareOptions.value
}

function applyMeasure(measure: string) {
  const current = form.value.处置措施.trim()
  form.value.处置措施 = current ? `${current}\n${measure}` : measure
  scheduleLocalDraft()
}

function bindSpare(index: number, orderNo: string) {
  const spare = spareOptions.value.find((item) => item.领用单号 === orderNo)
  const target = form.value.更换明细[index]
  if (!target) {
    return
  }
  if (spare) {
    target.领用单号 = spare.领用单号
    target.器材名称 = spare.器材名称
    target.器材规格 = spare.器材规格
  } else {
    target.领用单号 = ''
  }
  scheduleLocalDraft()
}

function addItem() {
  form.value.更换明细.push({ 领用单号: '', 器材名称: '', 器材规格: '', 数量: 1 })
  scheduleLocalDraft()
}

function removeItem(index: number) {
  form.value.更换明细.splice(index, 1)
  scheduleLocalDraft()
}

async function saveDraft() {
  formError.value = ''
  saving.value = true
  try {
    const response = await request(`${ENDPOINT}/${form.value.id}/progress`, {
      method: 'PUT',
      body: JSON.stringify({ values: { ...payloadValues(), version: serverVersion.value } }),
    })
    const result = await readBody(response)
    if (!result.ok) {
      throw new Error(result.message)
    }
    if (result.entry) {
      serverVersion.value = Number(result.entry.version ?? serverVersion.value)
    }
    const draft: DraftPayload = { form: form.value, version: serverVersion.value ?? 0, savedAt: new Date().toISOString() }
    localStorage.setItem(draftKey(form.value.id), JSON.stringify(draft))
    refreshDraftHint(draft)
    errorMessage.value = '处置过程已暂存'
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '草稿暂存失败'
  } finally {
    saving.value = false
  }
}

async function submitForm(action: string) {
  formError.value = ''
  saving.value = true
  try {
    const response = await request(`${ENDPOINT}/${form.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        values: { action, ...payloadValues(), version: serverVersion.value },
      }),
    })
    const result = await readBody(response)
    if (!result.ok) {
      throw new Error(result.message)
    }
    localStorage.removeItem(draftKey(form.value.id))
    closeEditor()
    await reload()
    await loadMeasures()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '提交失败'
  } finally {
    saving.value = false
  }
}

onMounted(reload)
</script>
