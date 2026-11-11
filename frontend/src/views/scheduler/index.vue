<template>
  <section class="page" data-module="scheduler">
    <header class="page-head">
      <div>
        <h2>定时调度管理</h2>
        <p class="page-desc">维护调度计划的输入、执行约束与结果记录，为定时调度提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记调度计划</button>
        <button class="btn" type="button" @click="exportRows">导出定时调度清单</button>
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
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="isPending(row.id, action)"
              @click="runAction(action, row)"
            >
              {{ isPending(row.id, action) ? '执行中…' : action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无定时调度数据，可先登记调度计划</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条定时调度记录</span>
      <span v-if="notice" :class="noticeKind === 'error' ? 'error-text' : 'success-text'">{{ notice }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { createActionToken, postAction, request, type ActionResult } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/scheduler'
const columns = ["计划编号", "Cron表达式", "关联任务", "时区设置", "最大执行时长", "并发上限", "错过补偿策略", "有效日期范围"]
const actions = ["提交校验", "启用计划", "停用计划"]
const stats = [{"label": "调度计划总数", "value": 0}, {"label": "已启用计划", "value": 0}, {"label": "待校验计划", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const notice = ref('')
const noticeKind = ref<'error' | 'success'>('error')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
// 正在执行的「记录-动作」键 -> 操作令牌；每次增删都整体替换对象，保证 Vue 可靠刷新禁用态。
const pending = ref<Record<string, string>>({})

function pendingKey(id: Row[keyof Row], action: string): string {
  return `${String(id)}::${action}`
}

function isPending(id: Row[keyof Row], action: string): boolean {
  return pendingKey(id, action) in pending.value
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  noticeKind.value = 'error'
  notice.value = '调度计划登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  const key = pendingKey(row.id, action)
  // 同一按钮重复点击：复用同一操作令牌，由后端保证只执行一次；不同按钮互不影响。
  const token = pending.value[key] ?? createActionToken()
  pending.value = { ...pending.value, [key]: token }
  notice.value = ''
  try {
    const result: ActionResult = await postAction(
      `${ENDPOINT}/${row.id}/actions`,
      { action, token },
      '定时调度动作未生效',
    )
    noticeKind.value = 'success'
    notice.value = result.duplicate ? `${result.message}（重复请求已确认，未重复执行）` : result.message
    // 以后端返回的最终记录为准刷新列表，不用前端本地改数据掩盖服务端结果。
    await reload()
  } catch (error) {
    // 业务拒绝（HTTP 200 但 ok=false，或 4xx）：展示后端原因，绝不假装完成、不本地改行状态。
    noticeKind.value = 'error'
    notice.value = error instanceof Error ? error.message : '定时调度操作失败'
  } finally {
    const { [key]: _removed, ...rest } = pending.value
    pending.value = rest
  }
}

async function reload() {
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('调度计划列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    noticeKind.value = 'error'
    notice.value = error instanceof Error ? error.message : '定时调度列表读取失败'
  }
}

onMounted(reload)
</script>
