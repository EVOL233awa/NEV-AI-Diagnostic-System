<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  changeSuperadminPassword,
  fetchHealth,
  fetchSuperadminConfig,
  getApiBase,
  saveSuperadminConfig,
  setApiBase,
  testProviderSlot,
  testSearchProvider,
  type AgentParams,
  type AsrProviderName,
  type HealthResp,
  type PasswordSource,
  type SearchProviderName,
  type SlotTestResult,
  type SuperadminConfig,
} from '../api/client'
import PageHeader from '../components/layout/PageHeader.vue'

const loading = ref(true)
const saving = ref(false)
const cfg = ref<SuperadminConfig | null>(null)

// 前端接入地址只存本机浏览器（localStorage），与服务器 config.json 无关：
// 前端与后端不同源部署时在此填写，测试成功即对本浏览器生效。
const apiBase = ref(getApiBase())
const testingBase = ref(false)
const baseHealth = ref<HealthResp | null>(null)

async function testBaseConnection(): Promise<void> {
  setApiBase(apiBase.value.trim())
  testingBase.value = true
  baseHealth.value = null
  try {
    baseHealth.value = await fetchHealth()
    ElMessage.success(`连接成功：${baseHealth.value.app}（v${baseHealth.value.version}）`)
  } catch {
    ElMessage.error('连接失败：请检查服务器地址与后端是否已启动')
  } finally {
    testingBase.value = false
  }
}

// key 永远拿不到明文：用户输入的新 key 存这里，留空 = 不修改（后端语义）
const newKeys = reactive({
  main: '',
  aux: '',
  embedding: '',
  rerank: '',
  searchDeepseek: '',
  searchTavily: '',
  searchCustom: '',
  asrDeepseek: '',
  asrOpenai: '',
})

const providers = reactive({
  main: { base_url: '', model: '' },
  embedding: { base_url: '', model: '' },
  rerank: { enabled: true, url: '', model: '', score_threshold: 0 },
})

const search = reactive({
  provider: 'deepseek' as SearchProviderName,
  fallback_to_tavily: true,
  fallback_on_empty: false,
  count: 5,
  content_max_chars: 1200,
  deepseek: { base_url: '', need_content: true, dynamic_language: true, timeout: 20 },
  tavily: { search_depth: 'basic' as 'basic' | 'advanced', max_results: 5, timeout: 20 },
  custom: { base_url: '', timeout: 20 },
})

const asr = reactive({
  provider: 'deepseek' as AsrProviderName,
  max_seconds: 120,
  max_bytes: 8388608,
  deepseek: { base_url: '', timeout: 60 },
  openai: { base_url: '', model: 'whisper-1', timeout: 60 },
})

// 限额输入用字符串承接：留空 = null = 不限制（后端 null/0 均视为不限制）
const quotaInputs = reactive({ asr: '', search: '', budget: '' })

const agent = reactive<AgentParams>({
  max_tool_rounds: 6,
  max_ask_user: 3,
  force_first_round_search: false,
  max_tokens: 2000,
  temperature: 0.6,
  tool_result_max_chars: 4000,
  compress_max_rounds: 20,
  compress_token_budget: 24000,
  compress_min_keep_rounds: 4,
  summary_max_chars: 800,
  title_temperature: 0.2,
  title_max_tokens: 60,
  title_input_chars: 500,
  extract_temperature: 0,
  extract_max_tokens: 300,
  extract_input_chars: 800,
})

const newPassword = ref('')
const confirmPassword = ref('')
const passwordSaving = ref(false)

const passwordSourceLabel: Record<PasswordSource, string> = {
  env: '环境变量 NEV_SUPERADMIN_PASSWORD（重启会覆盖面板修改）',
  config: '本机 data/config.json（固定值）',
  generated: '首次启动随机生成（一次性，建议尽快固定）',
}

const passwordSource = computed<PasswordSource>(() => cfg.value?.superadmin.password_source ?? 'config')

const testResults: Record<string, SlotTestResult | null> = reactive({
  main: null,
  aux: null,
  embedding: null,
  rerank: null,
  search: null,
})
const testing = reactive<Record<string, boolean>>({})

function fillForm(data: SuperadminConfig): void {
  cfg.value = data
  providers.main.base_url = data.providers.main.base_url
  providers.main.model = data.providers.main.model
  providers.embedding.base_url = data.providers.embedding.base_url
  providers.embedding.model = data.providers.embedding.model
  providers.rerank.enabled = data.providers.rerank.enabled
  providers.rerank.url = data.providers.rerank.url
  providers.rerank.model = data.providers.rerank.model
  providers.rerank.score_threshold = data.providers.rerank.score_threshold

  Object.assign(search, {
    provider: data.search.provider,
    fallback_to_tavily: data.search.fallback_to_tavily,
    fallback_on_empty: data.search.fallback_on_empty,
    count: data.search.count,
    content_max_chars: data.search.content_max_chars,
  })
  Object.assign(search.deepseek, {
    base_url: data.search.deepseek.base_url,
    need_content: data.search.deepseek.need_content,
    dynamic_language: data.search.deepseek.dynamic_language,
    timeout: data.search.deepseek.timeout,
  })
  Object.assign(search.tavily, {
    search_depth: data.search.tavily.search_depth,
    max_results: data.search.tavily.max_results,
    timeout: data.search.tavily.timeout,
  })
  Object.assign(search.custom, {
    base_url: data.search.custom.base_url,
    timeout: data.search.custom.timeout,
  })

  Object.assign(asr, {
    provider: data.asr.provider,
    max_seconds: data.asr.max_seconds,
    max_bytes: data.asr.max_bytes,
  })
  Object.assign(asr.deepseek, {
    base_url: data.asr.deepseek.base_url,
    timeout: data.asr.deepseek.timeout,
  })
  Object.assign(asr.openai, {
    base_url: data.asr.openai.base_url,
    model: data.asr.openai.model,
    timeout: data.asr.openai.timeout,
  })

  quotaInputs.asr = data.quota.asr_daily_seconds_per_user == null
    ? '' : String(data.quota.asr_daily_seconds_per_user)
  quotaInputs.search = data.quota.search_daily_calls_per_user == null
    ? '' : String(data.quota.search_daily_calls_per_user)
  quotaInputs.budget = data.quota.global_daily_usd == null
    ? '' : String(data.quota.global_daily_usd)

  Object.assign(agent, data.agent)
}

onMounted(async () => {
  try {
    fillForm(await fetchSuperadminConfig())
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    loading.value = false
  }
})

/** 留空 = null（不限制）；非法/负数返回 'invalid'。 */
function parseQuota(value: string): number | null | 'invalid' {
  const text = value.trim()
  if (!text) return null
  const number = Number(text)
  if (!Number.isFinite(number) || number < 0) return 'invalid'
  return number === 0 ? null : number
}

function quotaHint(seconds: number | null): string {
  if (seconds == null) return ''
  const minutes = seconds / 60
  return `${seconds} 秒 ≈ ${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)} 分钟/人/日`
}

async function save(): Promise<void> {
  const asrQuota = parseQuota(quotaInputs.asr)
  const searchQuota = parseQuota(quotaInputs.search)
  const budgetQuota = parseQuota(quotaInputs.budget)
  if (asrQuota === 'invalid' || searchQuota === 'invalid' || budgetQuota === 'invalid') {
    ElMessage.error('限额只能留空（不限制）或填写非负数字')
    return
  }
  saving.value = true
  try {
    await saveSuperadminConfig({
      providers: {
        main: {
          base_url: providers.main.base_url,
          model: providers.main.model,
          api_key: newKeys.main || undefined,
          aux_key: newKeys.aux || undefined,
        },
        embedding: {
          base_url: providers.embedding.base_url,
          model: providers.embedding.model,
          api_key: newKeys.embedding || undefined,
        },
        rerank: {
          enabled: providers.rerank.enabled,
          url: providers.rerank.url,
          model: providers.rerank.model,
          score_threshold: providers.rerank.score_threshold,
          api_key: newKeys.rerank || undefined,
        },
      },
      search: {
        provider: search.provider,
        fallback_to_tavily: search.fallback_to_tavily,
        fallback_on_empty: search.fallback_on_empty,
        count: search.count,
        content_max_chars: search.content_max_chars,
        deepseek: {
          base_url: search.deepseek.base_url,
          need_content: search.deepseek.need_content,
          dynamic_language: search.deepseek.dynamic_language,
          timeout: search.deepseek.timeout,
          api_key: newKeys.searchDeepseek || undefined,
        },
        tavily: {
          search_depth: search.tavily.search_depth,
          max_results: search.tavily.max_results,
          timeout: search.tavily.timeout,
          api_key: newKeys.searchTavily || undefined,
        },
        custom: {
          base_url: search.custom.base_url,
          timeout: search.custom.timeout,
          api_key: newKeys.searchCustom || undefined,
        },
      },
      asr: {
        provider: asr.provider,
        max_seconds: asr.max_seconds,
        max_bytes: asr.max_bytes,
        deepseek: {
          base_url: asr.deepseek.base_url,
          timeout: asr.deepseek.timeout,
          api_key: newKeys.asrDeepseek || undefined,
        },
        openai: {
          base_url: asr.openai.base_url,
          model: asr.openai.model,
          timeout: asr.openai.timeout,
          api_key: newKeys.asrOpenai || undefined,
        },
      },
      quota: {
        asr_daily_seconds_per_user: asrQuota,
        search_daily_calls_per_user: searchQuota,
        global_daily_usd: budgetQuota,
      },
      agent: { ...agent },
    })
    Object.keys(newKeys).forEach((key) => { newKeys[key as keyof typeof newKeys] = '' })
    fillForm(await fetchSuperadminConfig())
    ElMessage.success('已保存，配置对后续请求即时生效')
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    saving.value = false
  }
}

async function testSlot(slot: 'main' | 'aux' | 'embedding' | 'rerank' | 'search'): Promise<void> {
  testing[slot] = true
  testResults[slot] = null
  try {
    testResults[slot] = await testProviderSlot(slot)
  } catch (e) {
    testResults[slot] = { ok: false, slot, error: extractError(e), latency_ms: 0 }
  } finally {
    testing[slot] = false
  }
}

async function testSearch(provider?: SearchProviderName): Promise<void> {
  const key = provider ? `search:${provider}` : 'search'
  testing[key] = true
  testResults[key] = null
  try {
    testResults[key] = await testSearchProvider(provider)
  } catch (e) {
    testResults[key] = { ok: false, slot: 'search', error: extractError(e), latency_ms: 0 }
  } finally {
    testing[key] = false
  }
}

async function savePassword(): Promise<void> {
  if (newPassword.value.length < 8) {
    ElMessage.error('新密码至少 8 位，且须同时包含字母和数字')
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    ElMessage.error('两次输入的新密码不一致')
    return
  }
  passwordSaving.value = true
  try {
    const result = await changeSuperadminPassword(newPassword.value)
    newPassword.value = ''
    confirmPassword.value = ''
    fillForm(await fetchSuperadminConfig())
    ElMessage.success('superadmin 密码已更新')
    if (result.warning) ElMessage.warning(result.warning)
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    passwordSaving.value = false
  }
}

function keyPlaceholder(has_key: boolean, masked: string): string {
  return has_key ? `已配置 ${masked}（留空保持不变）` : '未配置，输入新 key'
}

function extractError(e: unknown): string {
  const resp = (e as { response?: { data?: { detail?: string } } }).response
  return resp?.data?.detail ?? '操作失败'
}

function testText(result: SlotTestResult | null): string {
  if (!result) return ''
  if (!result.ok) return `失败：${result.error}`
  const parts = [result.provider, result.model, result.reply ?? result.detail, `${result.latency_ms}ms`]
    .filter(Boolean)
  const titles = result.titles?.length ? `｜${result.titles.join(' / ')}` : ''
  return `通过（${parts.join(' · ')}）${titles}`
}
</script>

<template>
  <div class="page">
    <PageHeader title="系统参数配置" subtitle="三模型、搜索、ASR、限额与安全；保存即写盘并对后续请求生效">
      <template #actions>
        <el-button type="primary" :loading="saving" @click="save">保存全部配置</el-button>
      </template>
    </PageHeader>

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="此处修改的是服务器上的 config.json（含密钥唯一宿主）：保存即写盘并对后续请求生效，无需重启。host/port 等网络参数不在本页修改。"
    />

    <template v-if="!loading">
      <el-alert
        v-if="passwordSource !== 'config'"
        class="block"
        :type="passwordSource === 'env' ? 'warning' : 'info'"
        :closable="false"
        show-icon
        :title="passwordSource === 'env'
          ? '当前 superadmin 密码来自环境变量：面板修改会在下次启动时被环境变量覆盖。'
          : '当前 superadmin 密码是首次启动生成的一次性随机值：建议用 --set-superadmin-password 或 NEV_SUPERADMIN_PASSWORD 固定。'"
      />

      <el-card class="block">
        <template #header>三模型配置（主模型 / 嵌入 / 重排）</template>

        <h4 class="slot-title">主模型（诊断 Agent + 压缩 / 标题 / 抽取）</h4>
        <p class="desc">辅助任务复用同一模型；辅助 Key 留空则回退主对话 Key，仅用于避免抢占限流。</p>
        <el-form label-width="130px" class="grid-form">
          <el-form-item label="API 地址">
            <el-input v-model="providers.main.base_url" placeholder="https://api.deepseek.com" />
          </el-form-item>
          <el-form-item label="模型">
            <el-input v-model="providers.main.model" placeholder="deepseek-chat" />
          </el-form-item>
          <el-form-item label="主对话 Key">
            <el-input
              v-model="newKeys.main"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.providers.main.has_key, cfg!.providers.main.key_masked)"
            />
          </el-form-item>
          <el-form-item label="辅助任务 Key">
            <el-input
              v-model="newKeys.aux"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.providers.main.aux_has_key, cfg!.providers.main.aux_key_masked)"
            />
          </el-form-item>
        </el-form>
        <div class="slot-actions">
          <el-button size="small" :loading="testing.main" @click="testSlot('main')">测试主 Key</el-button>
          <el-button size="small" :loading="testing.aux" @click="testSlot('aux')">测试辅助 Key</el-button>
          <span class="test-result" :class="testResults.main?.ok ? 'ok' : 'fail'">{{ testText(testResults.main) }}</span>
        </div>

        <el-divider />

        <h4 class="slot-title">嵌入（知识库向量检索）</h4>
        <el-form label-width="130px" class="grid-form">
          <el-form-item label="API 地址">
            <el-input v-model="providers.embedding.base_url" placeholder="https://api.siliconflow.cn" />
          </el-form-item>
          <el-form-item label="模型">
            <el-input v-model="providers.embedding.model" placeholder="BAAI/bge-m3" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="newKeys.embedding"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.providers.embedding.has_key, cfg!.providers.embedding.key_masked)"
            />
          </el-form-item>
        </el-form>
        <div class="slot-actions">
          <el-button size="small" :loading="testing.embedding" @click="testSlot('embedding')">测试连接</el-button>
          <span class="test-result" :class="testResults.embedding?.ok ? 'ok' : 'fail'">{{ testText(testResults.embedding) }}</span>
        </div>

        <el-divider />

        <h4 class="slot-title">重排（对向量召回结果精排）</h4>
        <el-form label-width="130px" class="grid-form">
          <el-form-item label="启用重排">
            <el-switch v-model="providers.rerank.enabled" />
          </el-form-item>
          <el-form-item label="API 地址">
            <el-input v-model="providers.rerank.url" placeholder="https://api.siliconflow.cn（留空 = 不启用重排）" />
          </el-form-item>
          <el-form-item label="模型">
            <el-input v-model="providers.rerank.model" placeholder="BAAI/bge-reranker-v2-m3" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="newKeys.rerank"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.providers.rerank.has_key, cfg!.providers.rerank.key_masked)"
            />
          </el-form-item>
          <el-form-item label="分数阈值（0=纯排序）">
            <el-input-number v-model="providers.rerank.score_threshold" :min="0" :max="1" :step="0.05" :precision="2" />
          </el-form-item>
        </el-form>
        <div class="slot-actions">
          <el-button size="small" :loading="testing.rerank" @click="testSlot('rerank')">测试连接</el-button>
          <span class="test-result" :class="testResults.rerank?.ok ? 'ok' : 'fail'">{{ testText(testResults.rerank) }}</span>
        </div>
      </el-card>

      <el-card class="block">
        <template #header>联网检索</template>
        <p class="desc">
          默认 DeepSeek 官方搜索；Tavily 保留为可切换 provider 与失败降级通道。DeepSeek 专用 Key 留空时，
          仅当 API 地址为 api.deepseek.com 才回退主模型 Key。
        </p>
        <el-form label-width="170px" class="grid-form">
          <el-form-item label="首选 provider">
            <el-select v-model="search.provider" class="w220">
              <el-option label="DeepSeek 官方" value="deepseek" />
              <el-option label="Tavily" value="tavily" />
              <el-option label="自定义接口" value="custom" />
            </el-select>
          </el-form-item>
          <el-form-item label="失败降级到 Tavily">
            <el-switch v-model="search.fallback_to_tavily" />
          </el-form-item>
          <el-form-item label="零结果也降级">
            <el-switch v-model="search.fallback_on_empty" />
          </el-form-item>
          <el-form-item label="结果条数 / 正文上限">
            <el-input-number v-model="search.count" :min="1" :max="10" />
            <el-input-number v-model="search.content_max_chars" :min="200" :max="8000" :step="100" class="ml8" />
          </el-form-item>
        </el-form>

        <el-divider />
        <h4 class="slot-title">DeepSeek 官方</h4>
        <el-form label-width="170px" class="grid-form">
          <el-form-item label="API 地址">
            <el-input v-model="search.deepseek.base_url" placeholder="https://api.deepseek.com（非官方地址时必须单独填 Key）" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="newKeys.searchDeepseek"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.search.deepseek.has_key, cfg!.search.deepseek.key_masked)"
            />
          </el-form-item>
          <el-form-item label="返回正文">
            <el-switch v-model="search.deepseek.need_content" />
          </el-form-item>
          <el-form-item label="按语言加 lang: 算子">
            <el-switch v-model="search.deepseek.dynamic_language" />
          </el-form-item>
          <el-form-item label="超时（秒）">
            <el-input-number v-model="search.deepseek.timeout" :min="1" :max="300" />
          </el-form-item>
        </el-form>

        <el-divider />
        <h4 class="slot-title">Tavily</h4>
        <el-form label-width="170px" class="grid-form">
          <el-form-item label="API Key">
            <el-input
              v-model="newKeys.searchTavily"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.search.tavily.has_key, cfg!.search.tavily.key_masked)"
            />
          </el-form-item>
          <el-form-item label="检索深度">
            <el-select v-model="search.tavily.search_depth" class="w220">
              <el-option label="basic" value="basic" />
              <el-option label="advanced" value="advanced" />
            </el-select>
          </el-form-item>
          <el-form-item label="最大条数 / 超时">
            <el-input-number v-model="search.tavily.max_results" :min="1" :max="10" />
            <el-input-number v-model="search.tavily.timeout" :min="1" :max="300" class="ml8" />
          </el-form-item>
        </el-form>

        <el-divider />
        <h4 class="slot-title">自定义搜索接口（可选）</h4>
        <el-form label-width="170px" class="grid-form">
          <el-form-item label="接口地址">
            <el-input v-model="search.custom.base_url" placeholder="https://your-search.example/api/search" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="newKeys.searchCustom"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.search.custom.has_key, cfg!.search.custom.key_masked)"
            />
          </el-form-item>
          <el-form-item label="超时（秒）">
            <el-input-number v-model="search.custom.timeout" :min="1" :max="300" />
          </el-form-item>
        </el-form>

        <div class="slot-actions">
          <el-button size="small" :loading="testing.search" @click="testSlot('search')">按当前策略测试</el-button>
          <el-button size="small" :loading="testing['search:deepseek']" @click="testSearch('deepseek')">测 DeepSeek</el-button>
          <el-button size="small" :loading="testing['search:tavily']" @click="testSearch('tavily')">测 Tavily</el-button>
          <el-button size="small" :loading="testing['search:custom']" @click="testSearch('custom')">测自定义</el-button>
        </div>
        <p class="test-result" :class="testResults.search?.ok ? 'ok' : 'fail'">{{ testText(testResults.search) }}</p>
        <p
          v-for="name in (['deepseek', 'tavily', 'custom'] as const)"
          :key="name"
          class="test-result"
          :class="testResults[`search:${name}`]?.ok ? 'ok' : 'fail'"
        >{{ testResults[`search:${name}`] ? `${name}：${testText(testResults[`search:${name}`])}` : '' }}</p>
      </el-card>

      <el-card class="block">
        <template #header>语音转文字（ASR）</template>
        <p class="desc">
          录音在浏览器侧转 16kHz 单声道 WAV 后上传；DeepSeek 专用 Key 留空时仅当 API 地址为 official 才回退主模型 Key。
        </p>
        <el-form label-width="170px" class="grid-form">
          <el-form-item label="首选 provider">
            <el-select v-model="asr.provider" class="w220">
              <el-option label="DeepSeek 官方" value="deepseek" />
              <el-option label="OpenAI 兼容接口" value="openai" />
            </el-select>
          </el-form-item>
          <el-form-item label="最长录音（秒）">
            <el-input-number v-model="asr.max_seconds" :min="5" :max="600" :step="5" />
          </el-form-item>
          <el-form-item label="最大音频（字节）">
            <el-input-number v-model="asr.max_bytes" :min="1048576" :max="16777216" :step="1048576" />
          </el-form-item>
        </el-form>

        <el-divider />
        <h4 class="slot-title">DeepSeek 官方</h4>
        <el-form label-width="170px" class="grid-form">
          <el-form-item label="API 地址">
            <el-input v-model="asr.deepseek.base_url" placeholder="https://api.deepseek.com" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="newKeys.asrDeepseek"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.asr.deepseek.has_key, cfg!.asr.deepseek.key_masked)"
            />
          </el-form-item>
          <el-form-item label="超时（秒）">
            <el-input-number v-model="asr.deepseek.timeout" :min="1" :max="300" />
          </el-form-item>
        </el-form>

        <el-divider />
        <h4 class="slot-title">OpenAI 兼容接口</h4>
        <el-form label-width="170px" class="grid-form">
          <el-form-item label="API 地址">
            <el-input v-model="asr.openai.base_url" placeholder="https://your-asr.example/v1" />
          </el-form-item>
          <el-form-item label="模型（必填）">
            <el-input v-model="asr.openai.model" placeholder="whisper-1" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="newKeys.asrOpenai"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.asr.openai.has_key, cfg!.asr.openai.key_masked)"
            />
          </el-form-item>
          <el-form-item label="超时（秒）">
            <el-input-number v-model="asr.openai.timeout" :min="1" :max="300" />
          </el-form-item>
        </el-form>
      </el-card>

      <el-card class="block">
        <template #header>限额与预算（留空 = 不限制，演示默认）</template>
        <p class="desc">
          三项留空即完全不做超限判断；填写正数后按服务器本地日期统计，次日 00:00 重置。
          全局预算只覆盖搜索/语音的估算成本，不影响文字对话。管理端始终可见消耗。
        </p>
        <el-form label-width="220px" class="grid-form">
          <el-form-item label="每人每日语音秒数">
            <el-input v-model="quotaInputs.asr" placeholder="留空 = 不限制" class="w220" />
            <span class="hint">{{ quotaHint(parseQuota(quotaInputs.asr) === 'invalid' ? null : parseQuota(quotaInputs.asr) as number | null) }}</span>
          </el-form-item>
          <el-form-item label="每人每日搜索次数">
            <el-input v-model="quotaInputs.search" placeholder="留空 = 不限制" class="w220" />
          </el-form-item>
          <el-form-item label="全局每日预算（USD）">
            <el-input v-model="quotaInputs.budget" placeholder="留空 = 不限制" class="w220" />
          </el-form-item>
        </el-form>
      </el-card>

      <el-card class="block">
        <template #header>Agent 运行参数（改完保存，对下一轮对话即时生效）</template>

        <div class="param-grid">
          <div class="param">
            <el-input-number v-model="agent.max_tool_rounds" :min="1" :max="20" />
            <div class="param-name">单轮最大工具调用轮数</div>
            <div class="param-desc">一次用户消息内允许的「模型 → 工具 → 模型」循环上限，超出后强制基于已有证据收束结论。</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.max_ask_user" :min="0" :max="10" />
            <div class="param-name">单轮追问上限</div>
            <div class="param-desc">单轮 ask_user 提问次数上限，超出后不再追问、缺失信息列入待确认清单。</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.max_tokens" :min="256" :max="32000" :step="128" />
            <div class="param-name">单次回复 token 上限</div>
            <div class="param-desc">主模型单次回复的 max_tokens。</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.temperature" :min="0" :max="2" :step="0.1" />
            <div class="param-name">采样温度</div>
            <div class="param-desc">调低更稳定，调高更多样；诊断场景建议 0.2~0.8。</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.tool_result_max_chars" :min="500" :max="30000" :step="500" />
            <div class="param-name">工具结果截断（字符）</div>
            <div class="param-desc">单条工具结果送入模型的字符预算，防单次检索撑爆上下文。</div>
          </div>
        </div>

        <el-divider />

        <div class="param-grid">
          <div class="param">
            <el-input-number v-model="agent.compress_max_rounds" :min="2" :max="100" />
            <div class="param-name">上下文压缩：保留轮数</div>
            <div class="param-desc">阀门一：超过该轮数的最早对话被移出上下文（原文仍在库里，可回看）。</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.compress_token_budget" :min="4000" :max="200000" :step="1000" />
            <div class="param-name">上下文压缩：token 预算</div>
            <div class="param-desc">阀门二：估算超预算时把较早轮次摘要为「前情摘要」。</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.compress_min_keep_rounds" :min="1" :max="20" />
            <div class="param-name">压缩最少保留轮数</div>
            <div class="param-desc">阀门二触发时至少保留的最近轮数。</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.summary_max_chars" :min="200" :max="4000" :step="100" />
            <div class="param-name">前情摘要字数上限</div>
            <div class="param-desc">压缩摘要的长度约束（越小越省 token，越大保真越多）。</div>
          </div>
        </div>

        <el-divider />

        <div class="param-grid">
          <div class="param">
            <el-input-number v-model="agent.title_temperature" :min="0" :max="2" :step="0.1" :precision="1" />
            <div class="param-name">标题生成温度</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.title_max_tokens" :min="16" :max="512" :step="16" />
            <div class="param-name">标题 token 上限</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.title_input_chars" :min="50" :max="2000" :step="50" />
            <div class="param-name">标题输入截断（字符）</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.extract_temperature" :min="0" :max="2" :step="0.1" :precision="1" />
            <div class="param-name">状态卡抽取温度</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.extract_max_tokens" :min="50" :max="2000" :step="50" />
            <div class="param-name">抽取 token 上限</div>
          </div>
          <div class="param">
            <el-input-number v-model="agent.extract_input_chars" :min="100" :max="8000" :step="100" />
            <div class="param-name">抽取输入截断（字符）</div>
          </div>
        </div>

        <el-divider />

        <div class="switch-row">
          <el-switch v-model="agent.force_first_round_search" />
          <div>
            <div class="param-name">首轮强制检索（实验性）</div>
            <div class="param-desc">
              开启后会话首轮请求经 API 层 tool_choice 锁定 kb_search，模型必须先查知识库（协议级硬强制，区别于系统提示词的软约束）。
              注意：对「你好」等非诊断开场白也会强制检索，且要求供应商支持 tool_choice 参数——不支持时首轮会报错，关掉即可。
            </div>
          </div>
        </div>
      </el-card>

      <el-card class="block">
        <template #header>superadmin 密码（固定密码）</template>
        <p class="desc">
          当前来源：{{ passwordSourceLabel[passwordSource] }}。密码明文只存服务器本机 config.json，
          不会返回前端；启动时打印到后端终端窗口。
        </p>
        <el-form label-width="140px" class="grid-form">
          <el-form-item label="新密码">
            <el-input v-model="newPassword" type="password" show-password placeholder="至少 8 位，字母+数字，不能含 superadmin" />
          </el-form-item>
          <el-form-item label="确认新密码">
            <el-input v-model="confirmPassword" type="password" show-password placeholder="再次输入" />
          </el-form-item>
        </el-form>
        <div class="slot-actions">
          <el-button size="small" :loading="passwordSaving" @click="savePassword">修改密码</el-button>
        </div>
      </el-card>

      <el-card class="block">
        <template #header>前端接入地址（本机浏览器）</template>
        <p class="desc">
          本页其他配置保存在服务器 config.json；此项例外——它只写入当前浏览器（localStorage），
          决定这个浏览器的前端把请求发往哪台后端。留空 = 当前站点（同源部署）。
        </p>
        <div class="base-row">
          <el-input
            v-model="apiBase"
            placeholder="留空 = 当前站点（同源部署）"
            spellcheck="false"
            clearable
            class="base-input"
          />
          <el-button :loading="testingBase" @click="testBaseConnection">测试连接</el-button>
        </div>
        <p v-if="baseHealth" class="health-line">
          后端在线 · 主模型 {{ baseHealth.providers.main_model || '未配置' }} · 联网检索
          {{ baseHealth.providers.web_search ? `已启用（${baseHealth.providers.search_provider ?? '未知'}）` : '未配置' }}
          · 语音识别 {{ baseHealth.providers.asr_configured ? '已配置' : '未配置' }}
        </p>
      </el-card>

      <el-card class="block">
        <template #header>服务器信息</template>
        <p class="desc">
          版本 {{ cfg!.server.version }} · 监听 {{ cfg!.server.host }}:{{ cfg!.server.port }}。
          server.host / server.port / cors_origins / security.jwt_secret 修改需重启进程生效，请直接编辑服务器上的 config.json。
        </p>
      </el-card>

      <div class="save-bar">
        <el-button type="primary" size="large" :loading="saving" @click="save">保存全部配置</el-button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page {
  max-inline-size: 980px;
  margin-inline: auto;
  padding: 1rem clamp(0.8rem, 2vw, 1.4rem) 2.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.slot-title {
  margin: 1rem 0 0.55rem;
  font-size: var(--hmi-fs-4);
  font-weight: 650;
  color: var(--hmi-text);
}

.slot-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 0.25rem;
}

.test-result {
  font-size: 0.78rem;
}

.test-result.ok {
  color: var(--accent);
}

.test-result.fail {
  color: var(--el-color-danger, #f56c6c);
}

.grid-form {
  max-width: 640px;
}

.param-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1rem;
}

.param-name {
  font-size: var(--hmi-fs-3);
  margin-top: 0.3rem;
  color: var(--hmi-text-2);
}

.param-desc {
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
  margin-top: 0.15rem;
  line-height: 1.5;
}

.switch-row {
  display: flex;
  align-items: flex-start;
  gap: 0.9rem;
}

.desc {
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-3);
  line-height: 1.7;
  margin: 0 0 0.5rem;
}

.hint {
  margin-inline-start: 0.6rem;
  font-size: var(--hmi-fs-1);
  color: var(--hmi-text-3);
}

.base-row {
  display: flex;
  gap: 0.6rem;
  max-width: 560px;
}

.base-input {
  flex: 1;
}

.health-line {
  margin: 0.75rem 0 0;
  font-size: var(--hmi-fs-2);
  color: var(--hmi-text-3);
}

.ml8 {
  margin-left: 0.5rem;
}

.w220 {
  width: 220px;
}

.save-bar {
  position: sticky;
  inset-block-end: 0;
  z-index: 10;
  display: flex;
  justify-content: flex-end;
  padding: 0.7rem 0;
  background: linear-gradient(180deg, transparent, var(--hmi-bg) 45%);
}

@media (max-width: 640px) {
  .grid-form :deep(.el-form-item) {
    display: block;
  }

  .grid-form :deep(.el-form-item__label) {
    inline-size: auto;
    justify-content: flex-start;
    margin-block-end: 0.2rem;
  }

  .grid-form :deep(.el-form-item__content) {
    margin-inline-start: 0 !important;
  }

  .w220 {
    inline-size: 100%;
  }
}
</style>
