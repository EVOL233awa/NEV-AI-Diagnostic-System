<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Upload } from '@element-plus/icons-vue'
import {
  deleteKbDocument,
  kbSearch,
  listKbChunks,
  listKbDocuments,
  uploadKbDocument,
  type KbChunkInfo,
  type KbDocumentInfo,
  type KbSearchHit,
} from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/layout/PageHeader.vue'
import StatusChip from '../components/StatusChip.vue'

const docs = ref<KbDocumentInfo[]>([])
const docQuery = ref('')
const tab = ref<'preview' | 'upload' | 'search'>('preview')

const uploadForm = reactive({
  title: '',
  category: 'general',
  source_url: '',
  source_note: '',
  markdown_text: '',
  file: null as File | null,
})
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const searchForm = reactive({ query: '', category: '', topK: 5 })
const TOP_K_OPTIONS = [3, 5, 8, 10, 15, 20]
const searching = ref(false)
const hits = ref<KbSearchHit[]>([])

const CATEGORIES = ['general', 'dtc', 'battery', 'motor', 'electric_control', 'charging', 'method', 'scenario', 'indicators', 'maintenance', 'case']

const CAT_LABELS: Record<string, string> = {
  general: '通用知识',
  dtc: '故障码',
  battery: '电池',
  motor: '电机',
  electric_control: '电控',
  charging: '充电',
  method: '维修方法',
  scenario: '使用场景',
  indicators: '仪表指示',
  maintenance: '保养',
  case: '沉淀案例',
}

function catLabel(c: string): string {
  return CAT_LABELS[c] ?? c
}

const filteredDocs = computed(() => {
  const q = docQuery.value.trim().toLowerCase()
  const sorted = [...docs.value].sort((a, b) => a.title.localeCompare(b.title, 'zh-CN'))
  if (!q) return sorted
  return sorted.filter((doc) => [doc.title, doc.category, doc.source_note].join(' ').toLowerCase().includes(q))
})

/* ---------- 文档预览 ---------- */

const previewDocId = ref<number | null>(null)
const previewChunks = ref<KbChunkInfo[]>([])
const previewLoading = ref(false)
const expandedChunks = ref<number[]>([])

const previewDoc = computed(() => docs.value.find((d) => d.id === previewDocId.value) ?? null)
const fullText = computed(() => previewChunks.value.map((c) => c.content).join('\n\n'))

function selectDoc(doc: KbDocumentInfo): void {
  previewDocId.value = doc.id
  previewChunks.value = []
  expandedChunks.value = []
  tab.value = 'preview'
  void loadChunks(doc.id)
}

async function loadChunks(id: number): Promise<void> {
  previewLoading.value = true
  try {
    previewChunks.value = await listKbChunks(id)
  } catch {
    ElMessage.error('加载分片失败')
  } finally {
    previewLoading.value = false
  }
}

async function refresh(): Promise<void> {
  try {
    docs.value = await listKbDocuments()
  } catch {
    ElMessage.error('加载文档列表失败')
  }
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  uploadForm.file = input.files?.[0] ?? null
  if (uploadForm.file && !uploadForm.title) {
    uploadForm.title = uploadForm.file.name.replace(/\.[^.]+$/, '')
  }
}

async function doUpload(): Promise<void> {
  if (!uploadForm.file && !uploadForm.markdown_text.trim()) {
    ElMessage.warning('请选择文件或粘贴文本')
    return
  }
  uploading.value = true
  try {
    const form = new FormData()
    if (uploadForm.file) form.append('file', uploadForm.file)
    if (uploadForm.title) form.append('title', uploadForm.title)
    form.append('category', uploadForm.category)
    if (uploadForm.source_url) form.append('source_url', uploadForm.source_url)
    if (uploadForm.source_note) form.append('source_note', uploadForm.source_note)
    if (uploadForm.markdown_text.trim()) form.append('markdown_text', uploadForm.markdown_text)
    const resp = await uploadKbDocument(form)
    ElMessage.success(`已入库：${resp.title}（${resp.chunk_count} 块）`)
    uploadForm.title = ''
    uploadForm.markdown_text = ''
    uploadForm.file = null
    if (fileInput.value) fileInput.value.value = ''
    await refresh()
    const created = docs.value.find((doc) => doc.id === resp.id)
    if (created) selectDoc(created)
  } catch {
    ElMessage.error('入库失败：检查文件类型或联系管理员')
  } finally {
    uploading.value = false
  }
}

async function doDelete(doc: KbDocumentInfo): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除「${doc.title}」及其 ${doc.chunk_count} 个知识块？`, '确认删除', { type: 'warning' })
  } catch {
    return
  }
  await deleteKbDocument(doc.id)
  ElMessage.success('已删除')
  if (previewDocId.value === doc.id) {
    previewDocId.value = null
    previewChunks.value = []
  }
  await refresh()
}

async function doSearch(): Promise<void> {
  if (!searchForm.query.trim()) return
  searching.value = true
  try {
    hits.value = await kbSearch(searchForm.query.trim(), searchForm.category || null, searchForm.topK)
    if (hits.value.length === 0) ElMessage.info('无命中结果')
  } finally {
    searching.value = false
  }
}

function statusTone(status: string): 'ok' | 'warn' | 'danger' | 'neutral' {
  if (status === 'ready' || status === 'ok') return 'ok'
  if (status === 'parsing') return 'warn'
  if (status === 'failed') return 'danger'
  return 'neutral'
}

onMounted(refresh)
</script>

<template>
  <div class="page">
    <PageHeader title="知识库管理" subtitle="上传、分片预览与检索测试；检索结果会带章节路径与来源">
      <template #actions>
        <StatusChip :label="`${docs.length} 篇文档`" tone="neutral" />
        <el-button type="primary" :icon="Upload" @click="tab = 'upload'">上传文档</el-button>
      </template>
    </PageHeader>

    <div class="kb-layout">
      <aside class="doc-pane hmi-card">
        <div class="pane-head">
          <h3>文档清单</h3>
          <span class="hmi-sub">{{ filteredDocs.length }} / {{ docs.length }}</span>
        </div>
        <el-input v-model="docQuery" placeholder="搜索标题 / 类别 / 来源" clearable size="small" class="doc-search" aria-label="搜索知识库文档" />
        <div class="doc-list">
          <button
            v-for="doc in filteredDocs"
            :key="doc.id"
            type="button"
            class="doc-item"
            :class="{ active: previewDocId === doc.id }"
            :aria-current="previewDocId === doc.id ? 'true' : undefined"
            @click="selectDoc(doc)"
          >
            <span class="doc-title">{{ doc.title }}</span>
            <span class="doc-meta">
              <span>{{ catLabel(doc.category) }}</span>
              <span class="hmi-mono">{{ doc.chunk_count }} 块</span>
            </span>
            <span class="doc-status">
              <StatusChip :label="doc.status" :tone="statusTone(doc.status)" />
            </span>
          </button>
          <EmptyState v-if="filteredDocs.length === 0" title="没有匹配文档" compact />
        </div>
      </aside>

      <section class="work-pane hmi-card">
        <el-tabs v-model="tab">
          <el-tab-pane label="文档预览" name="preview">
            <template v-if="previewDoc">
              <div class="preview-head">
                <div>
                  <h3>{{ previewDoc.title }}</h3>
                  <p class="hmi-sub">
                    {{ catLabel(previewDoc.category) }} · {{ previewDoc.chunk_count }} 块 · 状态 {{ previewDoc.status }}
                    <span v-if="previewDoc.source_note"> · 来源：{{ previewDoc.source_note }}</span>
                  </p>
                </div>
                <el-button type="danger" plain size="small" @click="doDelete(previewDoc)">删除</el-button>
              </div>

              <h4 class="sub-title">分片预览 <span class="hmi-sub">（点开查看原文块）</span></h4>
              <div v-loading="previewLoading">
                <el-collapse v-if="previewChunks.length" v-model="expandedChunks" class="chunk-collapse">
                  <el-collapse-item v-for="chunk in previewChunks" :key="chunk.id" :name="chunk.id">
                    <template #title>
                      <span class="chunk-title hmi-mono">
                        #{{ chunk.seq }} · {{ chunk.section_path || '（无章节）' }}<span v-if="chunk.page_no"> · P{{ chunk.page_no }}</span>
                      </span>
                    </template>
                    <p class="chunk-content">{{ chunk.content }}</p>
                  </el-collapse-item>
                </el-collapse>
                <EmptyState v-else-if="!previewLoading" title="暂无分片" description="可能解析失败或文档为空。" compact />
              </div>

              <h4 class="sub-title">整篇预览</h4>
              <div class="full-text">{{ fullText || '（无内容）' }}</div>
            </template>
            <EmptyState
              v-else
              title="从左侧选择一篇文档"
              description="可查看分片章节、来源与整篇内容；也可在「检索测试」里验证召回效果。"
            />
          </el-tab-pane>

          <el-tab-pane label="上传文档" name="upload">
            <el-form label-position="top">
              <div class="form-grid">
                <el-form-item label="文件">
                  <input ref="fileInput" type="file" accept=".pdf,.docx,.md,.markdown,.txt,.csv,.json" @change="onFileChange" />
                  <span class="hint">支持 PDF / Word / MD / TXT / CSV / JSON</span>
                </el-form-item>
                <el-form-item label="类别">
                  <el-select v-model="uploadForm.category">
                    <el-option v-for="c in CATEGORIES" :key="c" :label="catLabel(c)" :value="c" />
                  </el-select>
                </el-form-item>
              </div>
              <el-form-item label="标题">
                <el-input v-model="uploadForm.title" placeholder="留空自动取文件名" />
              </el-form-item>
              <el-form-item label="或粘贴 Markdown">
                <el-input
                  v-model="uploadForm.markdown_text"
                  type="textarea"
                  :rows="7"
                  placeholder="直接粘贴 Markdown 文本（# 标题结构会被识别为章节路径）"
                />
              </el-form-item>
              <div class="form-grid">
                <el-form-item label="来源 URL">
                  <el-input v-model="uploadForm.source_url" placeholder="可选" />
                </el-form-item>
                <el-form-item label="来源说明">
                  <el-input v-model="uploadForm.source_note" placeholder="可溯源要求" />
                </el-form-item>
              </div>
              <el-button type="primary" :icon="Upload" :loading="uploading" @click="doUpload">解析入库</el-button>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="检索测试" name="search">
            <div class="search-row">
              <el-input
                v-model="searchForm.query"
                class="query-input"
                placeholder="输入查询，例如：冬天续航掉得厉害 / P0A7F"
                clearable
                aria-label="检索测试查询"
                @keyup.enter="doSearch"
              />
              <el-select v-model="searchForm.category" placeholder="全部类别" clearable class="cat-select" aria-label="按类别筛选">
                <el-option v-for="c in CATEGORIES" :key="c" :label="catLabel(c)" :value="c" />
              </el-select>
              <el-select v-model="searchForm.topK" class="topk-select" aria-label="返回条数">
                <el-option v-for="n in TOP_K_OPTIONS" :key="n" :label="`${n} 条`" :value="n" />
              </el-select>
              <el-button type="primary" :icon="Search" :loading="searching" @click="doSearch">检索</el-button>
            </div>
            <div v-if="hits.length" class="hits">
              <article v-for="hit in hits" :key="hit.chunk_id" class="hit">
                <header class="hit-head">
                  <span class="hit-doc">{{ hit.document }}</span>
                  <span class="hit-sec">{{ hit.section }}</span>
                  <span class="hit-meta hmi-mono">score {{ hit.score.toFixed(4) }} · {{ hit.legs.join('+') }}</span>
                </header>
                <p class="hit-content">{{ hit.content }}</p>
              </article>
            </div>
            <EmptyState v-else title="检索测试台" description="输入车主口语或故障码，验证 BM25 / 向量 / 重排的召回与分数。" compact />
          </el-tab-pane>
        </el-tabs>
      </section>
    </div>
  </div>
</template>

<style scoped>
.kb-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 0.75rem;
  align-items: start;
}

.doc-pane {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.85rem 0.85rem 0.5rem;
  max-block-size: calc(100vh - var(--hmi-topbar-h) - 8rem);
  max-block-size: calc(100dvh - var(--hmi-topbar-h) - 8rem);
  position: sticky;
  inset-block-start: calc(var(--hmi-topbar-h) + 0.75rem);
}

.pane-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.pane-head h3 {
  font-size: var(--hmi-fs-4);
  font-weight: 650;
}

.doc-search {
  margin-block-end: 0.1rem;
}

.doc-list {
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-block-end: 0.3rem;
}

.doc-item {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-areas:
    'title status'
    'meta status';
  gap: 1px 0.4rem;
  inline-size: 100%;
  text-align: start;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--hmi-radius-sm);
  padding: 0.45rem 0.5rem;
  color: var(--hmi-text-2);
  cursor: pointer;
}

.doc-item:hover {
  background: var(--hmi-surface-2);
}

.doc-item.active {
  background: var(--hmi-accent-soft);
  border-color: var(--hmi-accent-line);
}

.doc-title {
  grid-area: title;
  font-size: var(--hmi-fs-2);
  font-weight: 550;
  color: var(--hmi-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-meta {
  grid-area: meta;
  display: flex;
  gap: 0.5rem;
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

.doc-status {
  grid-area: status;
  align-self: center;
}

.work-pane {
  padding: 0.6rem 1rem 1rem;
  min-inline-size: 0;
}

.preview-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.6rem;
}

.preview-head h3 {
  font-size: var(--hmi-fs-5);
  font-weight: 650;
}

.sub-title {
  font-size: var(--hmi-fs-3);
  font-weight: 650;
  margin-block: 0.9rem 0.4rem;
}

.chunk-collapse {
  border: 1px solid var(--hmi-line);
  border-radius: var(--hmi-radius);
  overflow: hidden;
}

.chunk-title {
  font-size: var(--hmi-fs-2);
  color: var(--hmi-accent);
}

.chunk-content {
  margin: 0;
  font-size: var(--hmi-fs-2);
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--hmi-text-2);
}

.full-text {
  border: 1px solid var(--hmi-line);
  border-radius: var(--hmi-radius);
  padding: 0.7rem 0.85rem;
  max-block-size: 420px;
  overflow-y: auto;
  font-size: var(--hmi-fs-2);
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--hmi-text-2);
  background: var(--hmi-bg-deep);
}

.search-row {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.query-input {
  flex: 1 1 240px;
}

.cat-select {
  inline-size: 130px;
}

.topk-select {
  inline-size: 92px;
}

.hits {
  margin-block-start: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.hit {
  border: 1px solid var(--hmi-line);
  border-radius: var(--hmi-radius);
  padding: 0.55rem 0.7rem;
  background: var(--hmi-surface);
}

.hit-head {
  display: flex;
  gap: 0.6rem;
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
  flex-wrap: wrap;
}

.hit-doc {
  color: var(--hmi-accent);
}

.hit-meta {
  margin-inline-start: auto;
}

.hit-content {
  margin-block-start: 0.35rem;
  font-size: var(--hmi-fs-2);
  line-height: 1.6;
  color: var(--hmi-text-2);
  white-space: pre-wrap;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 0.6rem;
}

.hint {
  color: var(--hmi-text-3);
  font-size: var(--hmi-fs-1);
}

@media (max-width: 900px) {
  .kb-layout {
    grid-template-columns: 1fr;
  }

  .doc-pane {
    position: static;
    max-block-size: 320px;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .search-row > * {
    inline-size: 100%;
  }
}
</style>
