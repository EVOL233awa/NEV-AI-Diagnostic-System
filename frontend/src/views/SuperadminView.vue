<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchHealth,
  fetchSuperadminConfig,
  getApiBase,
  saveSuperadminConfig,
  setApiBase,
  testProviderSlot,
  type HealthResp,
  type SlotTestResult,
  type SuperadminConfig,
} from '../api/client'
import BackHome from '../components/BackHome.vue'

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
const newKeys = reactive({ main: '', background: '', embedding: '', rerank: '', small_model: '', web_search: '' })

const providers = reactive({
  main: { base_url: '', model: '' },
  background: { base_url: '', model: '' },
  embedding: { base_url: '', model: '' },
  subagent_url: '',
  rerank: { enabled: false, url: '', model: '', score_threshold: 0 },
  small_model: {
    base_url: '',
    model: '',
    disable_thinking: true,
    title_temperature: 0.2,
    title_max_tokens: 60,
    title_input_chars: 500,
    extract_temperature: 0,
    extract_max_tokens: 300,
    extract_input_chars: 800,
  },
})

const agent = reactive({
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
})

const testResults: Record<string, SlotTestResult | null> = reactive({
  main: null,
  background: null,
  embedding: null,
  rerank: null,
  small_model: null,
  web_search: null,
})
const testing = reactive<Record<string, boolean>>({})

function fillForm(data: SuperadminConfig): void {
  cfg.value = data
  providers.main.base_url = data.providers.main.base_url
  providers.main.model = data.providers.main.model
  providers.background.base_url = data.providers.background.base_url
  providers.background.model = data.providers.background.model
  providers.embedding.base_url = data.providers.embedding.base_url
  providers.embedding.model = data.providers.embedding.model
  providers.subagent_url = data.providers.subagent_url
  providers.rerank.enabled = data.providers.rerank.enabled
  providers.rerank.url = data.providers.rerank.url
  providers.rerank.model = data.providers.rerank.model
  providers.rerank.score_threshold = data.providers.rerank.score_threshold
  Object.assign(providers.small_model, {
    base_url: data.providers.small_model.base_url,
    model: data.providers.small_model.model,
    disable_thinking: data.providers.small_model.disable_thinking,
    title_temperature: data.providers.small_model.title_temperature,
    title_max_tokens: data.providers.small_model.title_max_tokens,
    title_input_chars: data.providers.small_model.title_input_chars,
    extract_temperature: data.providers.small_model.extract_temperature,
    extract_max_tokens: data.providers.small_model.extract_max_tokens,
    extract_input_chars: data.providers.small_model.extract_input_chars,
  })
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

async function save(): Promise<void> {
  saving.value = true
  try {
    await saveSuperadminConfig({
      providers: {
        main: { base_url: providers.main.base_url, model: providers.main.model, api_key: newKeys.main || undefined },
        background: {
          base_url: providers.background.base_url,
          model: providers.background.model,
          api_key: newKeys.background || undefined,
        },
        embedding: {
          base_url: providers.embedding.base_url,
          model: providers.embedding.model,
          api_key: newKeys.embedding || undefined,
        },
        web_search: newKeys.web_search ? { api_key: newKeys.web_search } : undefined,
        subagent_url: providers.subagent_url,
        rerank: {
          enabled: providers.rerank.enabled,
          url: providers.rerank.url,
          model: providers.rerank.model,
          score_threshold: providers.rerank.score_threshold,
          api_key: newKeys.rerank || undefined,
        },
        small_model: { ...providers.small_model, api_key: newKeys.small_model || undefined },
      },
      agent: { ...agent },
    })
    Object.assign(newKeys, { main: '', background: '', embedding: '', rerank: '', small_model: '', web_search: '' })
    fillForm(await fetchSuperadminConfig())
    ElMessage.success('已保存，配置对后续请求即时生效')
  } catch (e) {
    ElMessage.error(extractError(e))
  } finally {
    saving.value = false
  }
}

async function testSlot(
  slot: 'main' | 'background' | 'embedding' | 'rerank' | 'small_model' | 'web_search',
): Promise<void> {
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
  const parts = [result.model, result.reply ?? result.detail, `${result.latency_ms}ms`].filter(Boolean)
  return `通过（${parts.join(' · ')}）`
}
</script>

<template>
  <div class="page">
    <header class="page-head"><BackHome /><h2>系统参数配置（调试后台）</h2></header>

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="此处修改的是服务器上的 config.json（含密钥唯一宿主）：保存即写盘并对后续请求生效，无需重启。host/port 等网络参数不在本页修改。"
    />

    <template v-if="!loading">
      <el-card class="block">
        <template #header>模型供应商（OpenAI 兼容）</template>

        <h4 class="slot-title">主对话槽位（诊断 Agent）</h4>
        <el-form label-width="110px" class="grid-form">
          <el-form-item label="API 地址">
            <el-input v-model="providers.main.base_url" placeholder="https://api.deepseek.com" />
          </el-form-item>
          <el-form-item label="模型">
            <el-input v-model="providers.main.model" placeholder="deepseek-chat" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="newKeys.main"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.providers.main.has_key, cfg!.providers.main.key_masked)"
            />
          </el-form-item>
        </el-form>
        <div class="slot-actions">
          <el-button size="small" :loading="testing.main" @click="testSlot('main')">测试连接</el-button>
          <span class="test-result" :class="testResults.main?.ok ? 'ok' : 'fail'">{{ testText(testResults.main) }}</span>
        </div>

        <el-divider />

        <h4 class="slot-title">后台任务槽位（压缩 / 标题 / 抽取）</h4>
        <p class="desc">地址留空 = 跟随主对话槽位；Key 留空 = 沿用主对话 Key。</p>
        <el-form label-width="110px" class="grid-form">
          <el-form-item label="API 地址">
            <el-input v-model="providers.background.base_url" placeholder="留空跟随主对话" />
          </el-form-item>
          <el-form-item label="模型">
            <el-input v-model="providers.background.model" placeholder="deepseek-chat" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="newKeys.background"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.providers.background.has_key, cfg!.providers.background.key_masked)"
            />
          </el-form-item>
        </el-form>
        <div class="slot-actions">
          <el-button size="small" :loading="testing.background" @click="testSlot('background')">测试连接</el-button>
          <span class="test-result" :class="testResults.background?.ok ? 'ok' : 'fail'">{{ testText(testResults.background) }}</span>
        </div>

        <el-divider />

        <h4 class="slot-title">嵌入槽位（知识库向量检索）</h4>
        <el-form label-width="110px" class="grid-form">
          <el-form-item label="API 地址">
            <el-input v-model="providers.embedding.base_url" placeholder="https://api.siliconflow.cn/v1（本地 llama-server 填 http://127.0.0.1:11436）" />
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

        <h4 class="slot-title">联网检索（Tavily）与本地模型地址</h4>
        <el-form label-width="180px" class="grid-form">
          <el-form-item label="Tavily Key">
            <el-input
              v-model="newKeys.web_search"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.providers.web_search.has_key, cfg!.providers.web_search.key_masked)"
            />
          </el-form-item>
          <el-form-item label="本地小模型地址（可选）">
            <el-input v-model="providers.subagent_url" placeholder="http://127.0.0.1:11435（留空 = 本地默认）" />
          </el-form-item>
        </el-form>
        <div class="slot-actions">
          <el-button size="small" :loading="testing.web_search" @click="testSlot('web_search')">测试连接</el-button>
          <span class="test-result" :class="testResults.web_search?.ok ? 'ok' : 'fail'">{{ testText(testResults.web_search) }}</span>
        </div>

        <el-divider />

        <h4 class="slot-title">检索重排（对向量召回结果精排）</h4>
        <el-form label-width="180px" class="grid-form">
          <el-form-item label="启用重排">
            <el-switch v-model="providers.rerank.enabled" />
          </el-form-item>
          <el-form-item label="重排 API 地址">
            <el-input v-model="providers.rerank.url" placeholder="https://api.siliconflow.cn（留空 = 不启用重排）" />
          </el-form-item>
          <el-form-item label="重排模型">
            <el-input v-model="providers.rerank.model" placeholder="BAAI/bge-reranker-v2-m3（免费）" />
          </el-form-item>
          <el-form-item label="重排 API Key">
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

        <el-divider />

        <h4 class="slot-title">小模型槽位（会话标题 / 状态卡抽取）</h4>
        <el-form label-width="180px" class="grid-form">
          <el-form-item label="API 地址">
            <el-input v-model="providers.small_model.base_url" placeholder="留空 = 用主聊天模型（后台槽位）生成" />
          </el-form-item>
          <el-form-item label="模型">
            <el-input v-model="providers.small_model.model" placeholder="如 Qwen/Qwen3.5-4B（免费档实测排队可达 1 分钟）" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="newKeys.small_model"
              type="password"
              show-password
              :placeholder="keyPlaceholder(cfg!.providers.small_model.has_key, cfg!.providers.small_model.key_masked)"
            />
          </el-form-item>
          <el-form-item label="关闭思考模式">
            <el-switch v-model="providers.small_model.disable_thinking" />
          </el-form-item>
          <el-form-item label="标题温度 / Token 上限">
            <el-input-number v-model="providers.small_model.title_temperature" :min="0" :max="2" :step="0.1" :precision="1" />
            <el-input-number v-model="providers.small_model.title_max_tokens" :min="16" :max="512" :step="16" class="ml8" />
          </el-form-item>
          <el-form-item label="抽取温度 / Token 上限">
            <el-input-number v-model="providers.small_model.extract_temperature" :min="0" :max="2" :step="0.1" :precision="1" />
            <el-input-number v-model="providers.small_model.extract_max_tokens" :min="50" :max="2000" :step="50" class="ml8" />
          </el-form-item>
          <el-form-item label="输入截断（标题 / 抽取）">
            <el-input-number v-model="providers.small_model.title_input_chars" :min="50" :max="2000" :step="50" />
            <el-input-number v-model="providers.small_model.extract_input_chars" :min="100" :max="8000" :step="100" class="ml8" />
          </el-form-item>
        </el-form>
        <div class="slot-actions">
          <el-button size="small" :loading="testing.small_model" @click="testSlot('small_model')">测试连接</el-button>
          <span class="test-result" :class="testResults.small_model?.ok ? 'ok' : 'fail'">{{ testText(testResults.small_model) }}</span>
        </div>
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
        <template #header>前端接入地址（本机浏览器）</template>
        <p class="desc">
          本页其他配置保存在服务器 config.json；此项例外——它只写入当前浏览器（localStorage），
          决定这个浏览器的前端把请求发往哪台后端。留空 = 当前站点（同源部署）。
          前端与后端跨源部署（如前端托管在静态站点）时在此填写后端地址，测试成功即生效，无需保存。
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
          {{ baseHealth.providers.web_search ? '已启用' : '未配置' }}
        </p>
      </el-card>

      <el-card class="block">
        <template #header>服务器信息</template>
        <p class="desc">
          版本 {{ cfg!.server.version }} · 监听 {{ cfg!.server.host }}:{{ cfg!.server.port }}。
          server.host / server.port / cors_origins / security.jwt_secret 修改需重启进程生效，请直接编辑服务器上的 config.json。
          superadmin 密码只在创建/重置时打印于后端终端窗口：重新生成请在该终端运行
          <code>python main.py --reset-superadmin</code>。
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
  max-width: 860px;
  margin: 0 auto;
  padding: 1rem 1.25rem 2.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.page-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.page-head h2 {
  margin: 0;
  font-size: 1.05rem;
}

.slot-title {
  margin: 0.2rem 0 0.6rem;
  font-size: 0.9rem;
}

.slot-actions {
  display: flex;
  align-items: center;
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
  max-width: 560px;
}

.param-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1rem;
}

.param-name {
  font-size: 0.85rem;
  margin-top: 0.3rem;
}

.param-desc {
  font-size: 0.72rem;
  color: var(--muted);
  margin-top: 0.15rem;
  line-height: 1.5;
}

.switch-row {
  display: flex;
  align-items: flex-start;
  gap: 0.9rem;
}

.desc {
  font-size: 0.78rem;
  color: var(--muted);
  line-height: 1.7;
  margin: 0 0 0.5rem;
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
  font-size: 0.78rem;
  color: var(--muted);
}

.save-bar {
  position: sticky;
  bottom: 0;
  display: flex;
  justify-content: flex-end;
  padding: 0.6rem 0;
}
</style>
