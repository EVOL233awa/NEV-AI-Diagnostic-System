<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchDtc, searchDtc, type DtcDetail, type DtcEntry } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import StatusChip from '../components/StatusChip.vue'

const keyword = ref('')
const results = ref<DtcEntry[]>([])
const searched = ref(false)
const searching = ref(false)
const detailLoading = ref(false)
const detail = ref<DtcDetail | null>(null)

const QUICK_CODES = ['P0A80', 'P0300', 'P0011', 'P0420', 'U0100']

async function search(): Promise<void> {
  const q = keyword.value.trim()
  if (!q) {
    ElMessage.warning('请输入故障码或中文描述')
    return
  }
  searching.value = true
  try {
    results.value = await searchDtc(q)
    searched.value = true
    if (results.value.length === 1) {
      await open(results.value[0].code)
    }
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    searching.value = false
  }
}

async function open(code: string): Promise<void> {
  detailLoading.value = true
  try {
    detail.value = await fetchDtc(code)
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    detailLoading.value = false
  }
}

function useQuick(code: string): void {
  keyword.value = code
  void search()
}

function extractError(e: unknown): string {
  const resp = (e as { response?: { data?: { detail?: string } } }).response
  return resp?.data?.detail ?? '查询失败'
}
</script>

<template>
  <div class="page">
    <PageHeader title="故障码速查" subtitle="OBD-II 通用码表 + 知识库原文 + 门店案例；不替代厂家维修手册">
      <template #actions>
        <StatusChip label="内置通用码表" tone="neutral" />
      </template>
    </PageHeader>

    <section class="search-panel hmi-card">
      <div class="search-bar">
        <el-input
          v-model="keyword"
          placeholder="故障码（P0A80）或中文描述（电池组、失火）"
          clearable
          size="large"
          aria-label="输入故障码或中文描述"
          @keyup.enter="search"
        />
        <el-button type="primary" size="large" :loading="searching" @click="search">查询</el-button>
      </div>
      <div class="quick-row">
        <span class="hmi-sub">常用：</span>
        <button v-for="code in QUICK_CODES" :key="code" type="button" class="quick-chip" @click="useQuick(code)">
          {{ code }}
        </button>
      </div>
    </section>

    <div class="layout">
      <section class="results-pane">
        <div class="pane-head">
          <h3>匹配结果</h3>
          <span class="hmi-sub">{{ results.length }} 条</span>
        </div>
        <EmptyState
          v-if="searched && results.length === 0 && !searching"
          title="未收录该故障码或描述"
          description="可尝试码前缀（P0A）或中文关键词（绝缘、失火）。"
          compact
        />
        <div v-else class="result-list">
          <button
            v-for="item in results"
            :key="item.code"
            type="button"
            class="result-row"
            :class="{ active: detail?.code === item.code }"
            :aria-current="detail?.code === item.code ? 'true' : undefined"
            @click="open(item.code)"
          >
            <span class="code hmi-mono">{{ item.code }}</span>
            <span class="zh">{{ item.zh || '未命名故障' }}</span>
            <span class="note">{{ item.note }}</span>
          </button>
          <p v-if="!searched" class="hint">输入故障码或中文描述开始查询；也可点击上方常用码。</p>
        </div>
      </section>

      <section v-loading="detailLoading" class="detail-pane hmi-card">
        <EmptyState v-if="!detail && !detailLoading" title="选择左侧故障码查看详情" description="详情包含码表解释、知识库原文与相关门店案例。" />
        <template v-if="detail">
          <header class="detail-head">
            <div>
              <span class="code-lg hmi-mono">{{ detail.code }}</span>
              <h2>{{ detail.zh || '未命名故障' }}</h2>
            </div>
            <StatusChip v-if="detail.chunks.length" :label="`知识库 ${detail.chunks.length} 条`" tone="info" />
          </header>
          <p class="detail-note">{{ detail.note || '码表暂未提供详细说明。' }}</p>
          <p v-if="detail.doc_title" class="source-line">来源：{{ detail.doc_title }}<span v-if="detail.source_note"> · {{ detail.source_note }}</span></p>

          <div v-if="detail.chunks.length" class="block">
            <h3>知识库原文</h3>
            <article v-for="(chunk, i) in detail.chunks" :key="i" class="chunk">
              <p class="chunk-head">{{ chunk.document }}<span v-if="chunk.section_path"> · {{ chunk.section_path }}</span></p>
              <p class="chunk-body">{{ chunk.snippet }}</p>
              <p v-if="chunk.source_note" class="source-line">来源：{{ chunk.source_note }}</p>
            </article>
          </div>

          <div v-if="detail.cases.length" class="block">
            <h3>相关门店案例</h3>
            <article v-for="item in detail.cases" :key="item.id" class="case">
              <p class="case-title">
                {{ item.title }}
                <span class="source-line">{{ item.created_at?.replace('T', ' ').slice(0, 16) }}</span>
              </p>
              <p v-if="item.symptoms" class="case-line"><b>症状</b>{{ item.symptoms }}</p>
              <p v-if="item.diagnosis" class="case-line"><b>诊断</b>{{ item.diagnosis }}</p>
              <p v-if="item.repair_result" class="case-line"><b>维修</b>{{ item.repair_result }}</p>
            </article>
          </div>

          <p v-if="!detail.chunks.length && !detail.cases.length" class="hint">
            该码目前只有码表解释；可到案例库沉淀维修结果，或在诊断台结合车辆档案进一步判断。
          </p>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.search-panel {
  padding: 0.85rem 0.9rem;
}

.search-bar {
  display: flex;
  gap: 0.5rem;
}

.quick-row {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  margin-block-start: 0.45rem;
  flex-wrap: wrap;
}

.quick-chip {
  border: 1px solid var(--hmi-line);
  border-radius: 999px;
  background: transparent;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
  padding: 0.15rem 0.55rem;
  cursor: pointer;
  font-family: var(--hmi-font-mono);
}

.quick-chip:hover {
  border-color: var(--hmi-accent-line);
  color: var(--hmi-accent);
}

.layout {
  display: grid;
  grid-template-columns: minmax(240px, 0.8fr) minmax(0, 1.6fr);
  gap: 0.75rem;
  align-items: start;
}

.results-pane {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.pane-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.pane-head h3 {
  font-size: var(--hmi-fs-3);
  font-weight: 650;
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.result-row {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.1rem;
  inline-size: 100%;
  text-align: start;
  background: var(--hmi-surface);
  border: 1px solid var(--hmi-line);
  border-radius: var(--hmi-radius);
  padding: 0.55rem 0.65rem;
  color: inherit;
  cursor: pointer;
}

.result-row:hover,
.result-row.active {
  border-color: var(--hmi-accent-line);
  background: var(--hmi-surface-2);
}

.code {
  color: var(--hmi-accent);
  font-weight: 650;
  font-size: var(--hmi-fs-3);
}

.zh {
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text);
}

.note {
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.hint {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-2);
  padding: 0.7rem 0.2rem;
  line-height: 1.6;
}

.detail-pane {
  padding: 1rem 1.1rem;
  min-block-size: 260px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.6rem;
}

.code-lg {
  color: var(--hmi-accent);
  font-size: var(--hmi-fs-3);
  letter-spacing: 0.08em;
}

.detail-head h2 {
  font-size: 1.1rem;
  font-weight: 650;
  margin-block-start: 0.1rem;
}

.detail-note {
  margin-block-start: 0.65rem;
  font-size: var(--hmi-fs-3);
  line-height: 1.7;
  color: var(--hmi-text-2);
}

.source-line {
  margin-block-start: 0.25rem;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.block {
  margin-block-start: 1rem;
}

.block h3 {
  font-size: var(--hmi-fs-3);
  font-weight: 650;
  margin-block-end: 0.4rem;
}

.chunk,
.case {
  border-block-start: 1px dashed var(--hmi-line);
  padding-block: 0.5rem;
}

.chunk-head,
.case-title {
  margin: 0 0 0.2rem;
  font-size: var(--hmi-fs-2);
  font-weight: 600;
}

.chunk-body {
  margin: 0;
  font-size: var(--hmi-fs-2);
  line-height: 1.65;
  color: var(--hmi-text-3);
  white-space: pre-wrap;
}

.case-line {
  margin: 0.15rem 0;
  font-size: var(--hmi-fs-2);
  line-height: 1.55;
  color: var(--hmi-text-2);
}

.case-line b {
  display: inline-block;
  min-inline-size: 2.6em;
  color: var(--hmi-text-3);
  font-weight: 500;
}

@media (max-width: 820px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .search-bar {
    flex-direction: column;
  }
}
</style>
