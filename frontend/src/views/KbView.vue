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
import BackHome from '../components/BackHome.vue'

const docs = ref<KbDocumentInfo[]>([])

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

/** 类别码 → 中文标签（下拉里不再显示裸英文码） */
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

/* ---------- 文档预览：来源 → 模块 → 文章 三级筛选，分片可展开 + 整篇预览 ---------- */

const previewSource = ref<'kb' | 'case'>('kb')
const previewCategory = ref('')
const previewDocId = ref<number | null>(null)
const previewChunks = ref<KbChunkInfo[]>([])
const previewLoading = ref(false)
const expandedChunks = ref<number[]>([])

const sourceDocs = computed(() =>
  docs.value.filter((d) => (previewSource.value === 'case' ? d.category === 'case' : d.category !== 'case')),
)
const moduleOptions = computed(() => [...new Set(sourceDocs.value.map((d) => d.category))])
const articleOptions = computed(() =>
  previewSource.value === 'kb' && previewCategory.value
    ? sourceDocs.value.filter((d) => d.category === previewCategory.value)
    : sourceDocs.value,
)
const previewDoc = computed(() => sourceDocs.value.find((d) => d.id === previewDocId.value) ?? null)
const fullText = computed(() => previewChunks.value.map((c) => c.content).join('\n\n'))

function selectDoc(id: number | null): void {
  previewDocId.value = id
  previewChunks.value = []
  expandedChunks.value = []
  if (id !== null) void loadChunks(id)
}

function onSourceChange(): void {
  previewCategory.value = ''
  selectDoc(null)
}

function onCategoryChange(): void {
  selectDoc(null)
}

async function loadChunks(id: number): Promise<void> {
  previewLoading.value = true
  try {
    previewChunks.value = await listKbChunks(id)
    if (previewChunks.value.length === 0) {
      ElMessage.info('该文档暂无分片（可能解析失败）')
    }
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
  } catch {
    ElMessage.error('入库失败：检查文件类型或联系管理员')
  } finally {
    uploading.value = false
  }
}

async function doDelete(doc: KbDocumentInfo): Promise<void> {
  await ElMessageBox.confirm(`删除「${doc.title}」及其 ${doc.chunk_count} 个知识块？`, '确认删除', { type: 'warning' })
  await deleteKbDocument(doc.id)
  ElMessage.success('已删除')
  if (previewDocId.value === doc.id) selectDoc(null)
  await refresh()
}

async function doSearch(): Promise<void> {
  if (!searchForm.query.trim()) return
  searching.value = true
  try {
    hits.value = await kbSearch(searchForm.query.trim(), searchForm.category || null, searchForm.topK)
    if (hits.value.length === 0) {
      ElMessage.info('无命中结果')
    }
  } finally {
    searching.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="kb-page">
    <header class="topbar">
      <BackHome />
      <div class="brand">
        <h1>知识库管理</h1>
        <p class="subtitle">上传文档 · 文档预览 · 检索测试台</p>
      </div>
    </header>

    <main class="content">
      <section class="card">
        <h2>检索测试台</h2>
        <div class="search-row">
          <el-input
            v-model="searchForm.query"
            class="query-input"
            placeholder="输入查询，例如：冬天续航掉得厉害 / P0A7F"
            clearable
            @keyup.enter="doSearch"
          />
          <el-select v-model="searchForm.category" placeholder="全部类别" clearable class="cat-select">
            <el-option v-for="c in CATEGORIES" :key="c" :label="catLabel(c)" :value="c" />
          </el-select>
          <div class="topk">
            <span class="topk-label">返回条数</span>
            <el-select v-model="searchForm.topK" class="topk-select">
              <el-option v-for="n in TOP_K_OPTIONS" :key="n" :label="`${n} 条`" :value="n" />
            </el-select>
          </div>
          <el-button type="primary" :icon="Search" :loading="searching" @click="doSearch">检索</el-button>
        </div>
        <div v-if="hits.length" class="hits">
          <div v-for="h in hits" :key="h.chunk_id" class="hit">
            <div class="hit-head">
              <span class="hit-doc">{{ h.document }}</span>
              <span class="hit-sec">{{ h.section }}</span>
              <span class="hit-meta">score {{ h.score.toFixed(4) }} · {{ h.legs.join('+') }}</span>
            </div>
            <p class="hit-content">{{ h.content }}</p>
          </div>
        </div>
      </section>

      <section id="doc-preview" class="card">
        <h2>文档预览</h2>
        <div class="preview-filters">
          <div class="filter-field">
            <span class="filter-label">分类</span>
            <el-select v-model="previewSource" class="filter-select" @change="onSourceChange">
              <el-option label="知识库" value="kb" />
              <el-option label="沉淀案例" value="case" />
            </el-select>
          </div>
          <div v-if="previewSource === 'kb'" class="filter-field">
            <span class="filter-label">模块</span>
            <el-select v-model="previewCategory" placeholder="全部模块" clearable class="filter-select" @change="onCategoryChange">
              <!-- 显式复位入口：触屏设备无 hover，clearable 清除按钮不可达 -->
              <el-option label="全部模块" value="" />
              <el-option v-for="c in moduleOptions" :key="c" :label="catLabel(c)" :value="c" />
            </el-select>
          </div>
          <div class="filter-field article-field">
            <span class="filter-label">文章</span>
            <el-select
              :model-value="previewDocId"
              placeholder="选择文章后可预览"
              class="filter-select"
              :loading="previewLoading"
              @change="(v: number | null) => selectDoc(v ?? null)"
            >
              <el-option v-for="d in articleOptions" :key="d.id" :label="`${d.title}（${d.chunk_count} 块）`" :value="d.id" />
            </el-select>
          </div>
        </div>

        <template v-if="previewDoc">
          <div class="doc-meta-row">
            <p class="doc-meta">
              {{ catLabel(previewDoc.category) }} · {{ previewDoc.chunk_count }} 块 ·
              状态 {{ previewDoc.status }}<span v-if="previewDoc.source_note"> · 来源：{{ previewDoc.source_note }}</span>
            </p>
            <el-button class="doc-delete" link type="danger" size="small" @click="doDelete(previewDoc)">删除</el-button>
          </div>

          <h3 class="preview-sub">分片预览<span class="preview-hint">（点开查看原文块）</span></h3>
          <div v-loading="previewLoading">
            <el-collapse v-if="previewChunks.length" v-model="expandedChunks" class="chunk-collapse">
              <el-collapse-item v-for="c in previewChunks" :key="c.id" :name="c.id">
                <template #title>
                  <span class="chunk-title">
                    #{{ c.seq }} · {{ c.section_path || '（无章节）' }}<span v-if="c.page_no"> · P{{ c.page_no }}</span>
                  </span>
                </template>
                <p class="chunk-content">{{ c.content }}</p>
              </el-collapse-item>
            </el-collapse>
            <p v-else-if="!previewLoading" class="muted">暂无分片</p>
          </div>

          <h3 class="preview-sub">整篇预览</h3>
          <div class="full-text">{{ fullText }}</div>
        </template>
        <p v-else class="muted">先选分类，再从文章下拉里挑一篇即可在下方阅读。</p>
      </section>

      <section class="card">
        <h2>上传新文档</h2>
        <el-form label-width="90px">
          <el-form-item label="文件">
            <div class="upload-row">
              <input ref="fileInput" type="file" accept=".pdf,.docx,.md,.markdown,.txt,.csv,.json" @change="onFileChange" />
              <span class="hint">支持 PDF / Word / MD / TXT / CSV / JSON</span>
            </div>
          </el-form-item>
          <el-form-item label="或文本">
            <el-input
              v-model="uploadForm.markdown_text"
              type="textarea"
              :rows="5"
              placeholder="直接粘贴 Markdown 文本（# 标题结构会被识别为章节路径）"
            />
          </el-form-item>
          <el-form-item label="标题">
            <el-input v-model="uploadForm.title" placeholder="留空自动取文件名" />
          </el-form-item>
          <el-form-item label="类别">
            <el-select v-model="uploadForm.category" style="width: 200px">
              <el-option v-for="c in CATEGORIES" :key="c" :label="catLabel(c)" :value="c" />
            </el-select>
          </el-form-item>
          <el-form-item label="来源说明">
            <div class="upload-row">
              <el-input v-model="uploadForm.source_url" placeholder="来源 URL（可选）" style="flex: 1" />
              <el-input v-model="uploadForm.source_note" placeholder="来源说明（可溯源要求）" style="flex: 1" />
            </div>
          </el-form-item>
          <el-button type="primary" :icon="Upload" :loading="uploading" @click="doUpload">解析入库</el-button>
        </el-form>
      </section>
    </main>
  </div>
</template>

<style scoped>
.kb-page {
  min-height: 100vh;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.brand h1 {
  font-size: 1.05rem;
  margin: 0;
}

.subtitle {
  color: var(--muted);
  font-size: 0.72rem;
  margin: 0.25rem 0 0;
}

.content {
  max-width: 1080px;
  margin: 0 auto;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1rem 1.25rem;
}

.card h2 {
  font-size: 0.95rem;
  margin: 0 0 0.75rem;
}

.card h3 {
  font-size: 0.85rem;
  margin: 0.9rem 0 0.5rem;
}

.search-row {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.query-input {
  flex: 1;
  min-width: 220px;
}

.cat-select {
  width: 130px;
}

.topk {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.topk-label {
  font-size: 0.78rem;
  color: var(--muted);
  white-space: nowrap;
}

.topk-select {
  width: 96px;
}

.hits {
  margin-top: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.hit {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.6rem 0.75rem;
}

.hit-head {
  display: flex;
  gap: 0.75rem;
  font-size: 0.75rem;
  color: var(--muted);
  flex-wrap: wrap;
}

.hit-doc {
  color: var(--accent);
}

.hit-content {
  margin: 0.4rem 0 0;
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--text);
}

.preview-filters {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.filter-field {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.filter-label {
  font-size: 0.78rem;
  color: var(--muted);
  white-space: nowrap;
}

.filter-select {
  width: 170px;
}

.article-field {
  flex: 1;
  min-width: 240px;
}

.article-field .filter-select {
  width: 100%;
}

.doc-meta-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: 0.75rem;
}

.doc-meta {
  font-size: 0.75rem;
  color: var(--muted);
  margin: 0;
}

.doc-delete {
  flex-shrink: 0;
}

.preview-sub {
  font-size: 0.85rem;
  margin: 0.9rem 0 0.5rem;
}

.preview-hint {
  font-size: 0.72rem;
  color: var(--muted);
  font-weight: 400;
}

.chunk-collapse {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.chunk-title {
  font-size: 0.78rem;
  color: var(--accent-dim, var(--muted));
}

.chunk-content {
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.full-text {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.75rem 0.9rem;
  max-height: 420px;
  overflow-y: auto;
  font-size: 0.8rem;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.muted {
  color: var(--muted);
  font-size: 0.78rem;
}

.upload-row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  width: 100%;
}

.hint {
  font-size: 0.72rem;
  color: var(--muted);
}

@media (max-width: 640px) {
  .search-row > * {
    width: 100%;
  }

  .cat-select,
  .topk-select {
    width: 100%;
  }

  .topk {
    justify-content: space-between;
  }

  .filter-field {
    width: 100%;
  }

  .filter-select {
    flex: 1;
    width: auto;
  }
}
</style>
