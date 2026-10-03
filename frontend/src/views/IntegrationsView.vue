<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>资源对接</h2>
        <div class="sub">代理 IP · 接码平台 · 账号采购 · 发消息通道</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadCurrent">刷新</el-button>
    </div>

    <el-tabs v-model="activeTab">
      <!-- ==================== 集成状态 ==================== -->
      <el-tab-pane label="集成状态" name="providers">
        <el-alert
          v-if="status && status.available === false"
          type="error"
          :closable="false"
          show-icon
          :title="`providers 包不可用：${status.error || '未知原因'}`"
        />
        <template v-else>
          <el-row :gutter="16" class="card-row">
            <el-col v-for="item in providers" :key="item.kind" :xs="24" :md="12">
              <el-card shadow="never" class="provider-card">
                <template #header>
                  <div class="card-header">
                    <span>{{ PROVIDER_KIND_LABEL[item.kind] || item.kind }}</span>
                    <span>
                      <el-tag :type="item.configured ? 'success' : 'danger'" size="small" effect="plain">
                        {{ item.configured ? '已配置' : '未配置' }}
                      </el-tag>
                      <el-tag v-if="item.mock" type="warning" size="small" class="tag-gap">模拟</el-tag>
                    </span>
                  </div>
                </template>
                <el-descriptions :column="1" size="small" border>
                  <el-descriptions-item label="实现">{{ item.name }}</el-descriptions-item>
                  <el-descriptions-item label="说明">{{ item.detail || '-' }}</el-descriptions-item>
                  <el-descriptions-item v-if="item.balance !== null" label="余额">
                    {{ item.balance }}
                  </el-descriptions-item>
                  <el-descriptions-item v-if="item.pool" label="代理池">
                    空闲 {{ item.pool.free }} / 占用 {{ item.pool.in_use }} / 停用 {{ item.pool.disabled }}
                  </el-descriptions-item>
                </el-descriptions>
                <div v-if="item.kind === 'proxy'" class="card-actions">
                  <el-button size="small" :loading="syncing" @click="syncProxies">从供应商同步代理</el-button>
                </div>
              </el-card>
            </el-col>
          </el-row>

          <el-card v-if="status" shadow="never" class="section-gap">
            <template #header>运行配置</template>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="发消息通道">
                {{ status.config.message_provider }}
              </el-descriptions-item>
              <el-descriptions-item label="缺少代理时中断注册">
                {{ status.config.proxy_required ? '是' : '否（仅记日志）' }}
              </el-descriptions-item>
            </el-descriptions>
            <div class="field-hint">
              所有供应商在未配置密钥时都会自动退化为模拟实现，系统照常可跑；配置方式见
              docs/INTEGRATIONS.md 与 env.example.ps1。
            </div>
          </el-card>
        </template>
      </el-tab-pane>

      <!-- ==================== 代理池 ==================== -->
      <el-tab-pane label="代理池" name="proxies">


        <el-card shadow="never">
          <div class="filter-bar">
            <el-select v-model="proxyFilters.status" placeholder="状态" style="width: 130px" clearable>
              <el-option
                v-for="(label, key) in PROXY_STATUS_LABEL"
                :key="key"
                :label="label"
                :value="key"
              />
            </el-select>
            <el-input
              v-model="proxyFilters.country"
              placeholder="国家代码，如 ID"
              style="width: 160px"
              clearable
              @keyup.enter="reloadProxies"
            />
            <el-button type="primary" :icon="Search" @click="reloadProxies">查询</el-button>
            <el-button @click="resetProxyFilters">重置</el-button>
            <el-button :loading="syncing" @click="syncProxies">同步代理</el-button>
            <el-button :icon="Upload" @click="importVisible = true">导入代理</el-button>
          </div>
          <el-table v-loading="proxyLoading" :data="proxyRows" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="address" label="代理地址" min-width="250" show-overflow-tooltip />
            <el-table-column label="协议" width="90">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ row.protocol }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="country" label="国家" width="80" />
            <el-table-column prop="provider" label="来源" width="110" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="proxyStatusType(row.status)" size="small">
                  {{ PROXY_STATUS_LABEL[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="绑定号码" width="100">
              <template #default="{ row }">{{ row.bound_number_id ?? '-' }}</template>
            </el-table-column>
            <el-table-column prop="used_count" label="使用" width="70" />
            <el-table-column label="成功率" width="90">
              <template #default="{ row }">{{ successRate(row) }}</template>
            </el-table-column>
            <el-table-column label="延迟" width="90">
              <template #default="{ row }">{{ row.latency_ms ? `${row.latency_ms} ms` : '-' }}</template>
            </el-table-column>
            <el-table-column label="最近检测" width="170">
              <template #default="{ row }">{{ formatDateTime(row.last_checked_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="130" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="testProxy(row)">测试</el-button>
                <el-button
                  link
                  type="warning"
                  :disabled="row.status !== 'in_use'"
                  @click="releaseProxy(row)"
                >
                  释放
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="代理池是空的，点「同步代理」或「导入代理」" />
            </template>
          </el-table>
          <div class="pager">
            <el-pagination
              v-model:current-page="proxyPage"
              v-model:page-size="proxySize"
              :page-sizes="[10, 20, 50]"
              :total="proxyTotal"
              layout="total, sizes, prev, pager, next"
              background
              @current-change="loadProxies"
              @size-change="onProxySizeChange"
            />
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ==================== 接码订单 ==================== -->
      <el-tab-pane label="接码订单" name="sms">


        <el-card shadow="never">
        <div class="filter-bar">
          <el-select v-model="smsFilters.status" placeholder="状态" style="width: 130px" clearable>
            <el-option
              v-for="(label, key) in SMS_ORDER_STATUS_LABEL"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
          <el-button type="primary" :icon="Search" @click="reloadSms">查询</el-button>
          <el-button @click="smsFilters.status = ''; reloadSms()">重置</el-button>
          <el-button type="primary" :icon="Plus" @click="smsDialogVisible = true">取号</el-button>
        </div>
          <el-table v-loading="smsLoading" :data="smsRows" stripe>
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="phone" label="手机号" min-width="140" />
            <el-table-column prop="service" label="服务" width="80" />
            <el-table-column prop="country" label="国家" width="80" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="smsStatusType(row.status)" size="small">
                  {{ SMS_ORDER_STATUS_LABEL[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="验证码" width="110">
              <template #default="{ row }">
                <span v-if="row.code" class="code">{{ row.code }}</span>
                <span v-else class="muted">-</span>
              </template>
            </el-table-column>
            <el-table-column label="价格" width="90">
              <template #default="{ row }">{{ row.price ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="关联号码" width="100">
              <template #default="{ row }">{{ row.number_id ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="短信内容" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ row.text || '-' }}</template>
            </el-table-column>
            <el-table-column label="创建时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="230" fixed="right">
              <template #default="{ row }">
                <template v-if="row.status === 'waiting'">
                  <el-button link type="primary" :loading="smsBusy === row.id" @click="pollSms(row)">
                    查询一次
                  </el-button>
                  <el-button link type="success" :loading="smsWaiting === row.id" @click="waitSms(row)">
                    等待验证码
                  </el-button>
                  <el-button link type="danger" @click="cancelSms(row)">取消</el-button>
                </template>
                <span v-else class="muted">-</span>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="还没有取号记录，点上方「取号」从接码平台获取号码" />
            </template>
          </el-table>
          <div class="pager">
            <el-pagination
              v-model:current-page="smsPage"
              v-model:page-size="smsSize"
              :page-sizes="[10, 20, 50]"
              :total="smsTotal"
              layout="total, sizes, prev, pager, next"
              background
              @current-change="loadSms"
              @size-change="onSmsSizeChange"
            />
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ==================== 采购订单 ==================== -->
      <el-tab-pane label="采购订单" name="purchase">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>商品列表</span>
              <span class="muted">供应商：{{ productProvider || '-' }}</span>
            </div>
          </template>
          <el-table v-loading="productLoading" :data="products" stripe size="small">
            <el-table-column prop="name" label="商品" min-width="200" />
            <el-table-column label="单价" width="130">
              <template #default="{ row }">{{ row.price }} {{ row.currency }}</template>
            </el-table-column>
            <el-table-column prop="country" label="国家" width="90" />
            <el-table-column prop="stock" label="库存" width="90" />
            <el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip />
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" :disabled="row.stock <= 0" @click="openPurchase(row)">
                  采购
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="供应商没有返回商品，请检查 ACCOUNT_API_BASE 配置或供应商库存" />
            </template>
          </el-table>
        </el-card>

        <el-card shadow="never" class="section-gap">
          <template #header>
            <div class="card-header">
              <span>采购订单</span>
              <span class="muted">{{ purchaseTotal }} 条</span>
            </div>
          </template>
          <div class="filter-bar">
            <el-select v-model="purchaseFilters.status" placeholder="状态" style="width: 130px" clearable>
                <el-option
                  v-for="(label, key) in PURCHASE_ORDER_STATUS_LABEL"
                  :key="key"
                  :label="label"
                  :value="key"
                />
              </el-select>
              <el-input
                v-model="purchaseFilters.keyword"
                placeholder="订单号 / 商品名"
                style="width: 200px"
                clearable
                @keyup.enter="reloadPurchase"
              />
              <el-button type="primary" :icon="Search" @click="reloadPurchase">查询</el-button>
              <el-button @click="resetPurchaseFilters">重置</el-button>
          </div>

            <el-table v-loading="purchaseLoading" :data="purchaseRows" stripe>
              <el-table-column prop="order_no" label="订单号" min-width="150" />
              <el-table-column prop="product_name" label="商品" min-width="160" show-overflow-tooltip />
              <el-table-column prop="quantity" label="数量" width="70" />
              <el-table-column label="金额" width="120">
                <template #default="{ row }">{{ row.amount }} {{ row.currency }}</template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="purchaseStatusType(row.status)" size="small">
                    {{ PURCHASE_ORDER_STATUS_LABEL[row.status] || row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="provider" label="供应商" width="100" />
              <el-table-column label="交付账号" min-width="200">
                <template #default="{ row }">
                  <template v-if="row.accounts.length">
                    <el-tag v-for="account in row.accounts" :key="account" size="small" class="tag-gap">
                      {{ account }}
                    </el-tag>
                  </template>
                  <span v-else class="muted">未交付</span>
                </template>
              </el-table-column>
              <el-table-column label="创建时间" width="170">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="130" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click="syncPurchase(row)">同步</el-button>
                  <el-button link type="danger" @click="removePurchase(row)">删除</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <el-empty description="还没有采购订单，从上方商品列表点「采购」下单" />
              </template>
            </el-table>
            <div class="pager">
              <el-pagination
                v-model:current-page="purchasePage"
                v-model:page-size="purchaseSize"
                :page-sizes="[10, 20, 50]"
                :total="purchaseTotal"
                layout="total, sizes, prev, pager, next"
                background
                @current-change="loadPurchase"
                @size-change="onPurchaseSizeChange"
              />
            </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 导入代理 -->
    <el-dialog v-model="importVisible" title="导入代理" width="560px">
      <el-form label-width="80px">
        <el-form-item label="国家">
          <el-input v-model="importForm.country" placeholder="选填，如 ID" />
        </el-form-item>
        <el-form-item label="代理列表">
          <el-input
            v-model="importForm.text"
            type="textarea"
            :rows="7"
            placeholder="每行一个：&#10;1.2.3.4:8080:user:pass&#10;socks5://user:pass@5.6.7.8:1080"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="submitImport">导入</el-button>
      </template>
    </el-dialog>

    <!-- 取号 -->
    <el-dialog v-model="smsDialogVisible" title="接码取号" width="460px">
      <el-form label-width="80px">
        <el-form-item label="服务">
          <el-input v-model="smsForm.service" placeholder="WhatsApp 一般为 wa" />
        </el-form-item>
        <el-form-item label="国家">
          <el-input v-model="smsForm.country" placeholder="如 ID / GB / BR" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="smsDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="smsCreating" @click="submitSms">取号</el-button>
      </template>
    </el-dialog>

    <!-- 采购下单 -->
    <el-dialog v-model="purchaseDialogVisible" title="采购账号" width="480px">
      <el-form label-width="80px">
        <el-form-item label="商品">
          <el-input :model-value="purchaseForm.name" readonly />
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="purchaseForm.quantity" :min="1" :max="purchaseForm.stock || 999" />
          <span class="muted unit">库存 {{ purchaseForm.stock }}</span>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="purchaseForm.remark" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="purchaseDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="purchasing" @click="submitPurchase">下单</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search, Plus, Upload } from '@element-plus/icons-vue'
import { integrationApi } from '@/api'
import type {
  ProductRow,
  ProvidersStatus,
  ProxyRow,
  PurchaseOrderRow,
  SmsOrderRow,
} from '@/types/api'
import {
  PROVIDER_KIND_LABEL,
  PROXY_STATUS_LABEL,
  PURCHASE_ORDER_STATUS_LABEL,
  SMS_ORDER_STATUS_LABEL,
  formatDateTime,
} from '@/utils/format'

const activeTab = ref('providers')
const loading = ref(false)
const syncing = ref(false)

// ---------- 集成状态 ----------
const status = ref<ProvidersStatus | null>(null)
const providers = computed(() => status.value?.items ?? [])

async function loadStatus() {
  try {
    status.value = await integrationApi.status()
  } catch {
    /* 拦截器已提示 */
  }
}

// ---------- 代理池 ----------
const proxyLoading = ref(false)
const proxyRows = ref<ProxyRow[]>([])
const proxyTotal = ref(0)
const proxyPage = ref(1)
const proxySize = ref(20)
const proxyFilters = reactive({ status: '', country: '' })
const importVisible = ref(false)
const importing = ref(false)
const importForm = reactive({ text: '', country: '' })

function proxyStatusType(value: string) {
  return value === 'free' ? 'success' : value === 'in_use' ? 'warning' : 'danger'
}

function successRate(row: ProxyRow) {
  const total = (row.ok_count || 0) + (row.fail_count || 0)
  if (!total) return '-'
  return `${Math.round(((row.ok_count || 0) / total) * 100)}%`
}

async function loadProxies() {
  proxyLoading.value = true
  try {
    const res = await integrationApi.listProxies({
      page: proxyPage.value,
      size: proxySize.value,
      status: proxyFilters.status || undefined,
      country: proxyFilters.country || undefined,
    })
    proxyRows.value = res.list
    proxyTotal.value = res.total
  } catch {
    /* 拦截器已提示 */
  } finally {
    proxyLoading.value = false
  }
}

function reloadProxies() {
  proxyPage.value = 1
  loadProxies()
}

function onProxySizeChange() {
  proxyPage.value = 1
  loadProxies()
}

function resetProxyFilters() {
  proxyFilters.status = ''
  proxyFilters.country = ''
  reloadProxies()
}

async function syncProxies() {
  syncing.value = true
  try {
    const res = await integrationApi.syncProxies({ limit: 50 })
    ElMessage.success(`同步完成：新增 ${res.added} 条，更新 ${res.updated} 条（来自 ${res.provider}）`)
    loadProxies()
    loadStatus()
  } catch {
    /* 拦截器已提示 */
  } finally {
    syncing.value = false
  }
}

async function submitImport() {
  if (!importForm.text.trim()) {
    ElMessage.warning('请粘贴代理列表')
    return
  }
  importing.value = true
  try {
    const res = await integrationApi.importProxies({
      text: importForm.text,
      country: importForm.country,
    })
    ElMessage.success(`导入完成：新增 ${res.added} 条，跳过 ${res.skipped} 条`)
    importVisible.value = false
    importForm.text = ''
    reloadProxies()
  } catch {
    /* 拦截器已提示 */
  } finally {
    importing.value = false
  }
}

async function testProxy(row: ProxyRow) {
  try {
    const res = await integrationApi.testProxy(row.id)
    if (res.ok) ElMessage.success(`代理可用（${res.detail}）`)
    else ElMessage.warning(`代理不可用：${res.detail}`)
    loadProxies()
  } catch {
    /* 拦截器已提示 */
  }
}

async function releaseProxy(row: ProxyRow) {
  try {
    await ElMessageBox.confirm(`确认释放代理 ${row.host}:${row.port}？`, '释放代理', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await integrationApi.releaseProxy(row.id)
    ElMessage.success('已释放')
    loadProxies()
  } catch {
    /* 拦截器已提示 */
  }
}

// ---------- 接码订单 ----------
const smsLoading = ref(false)
const smsRows = ref<SmsOrderRow[]>([])
const smsTotal = ref(0)
const smsPage = ref(1)
const smsSize = ref(20)
const smsFilters = reactive({ status: '' })
const smsDialogVisible = ref(false)
const smsCreating = ref(false)
const smsBusy = ref<number | null>(null)
const smsWaiting = ref<number | null>(null)
const smsForm = reactive({ service: 'wa', country: 'ID' })

function smsStatusType(value: string) {
  switch (value) {
    case 'completed':
      return 'success'
    case 'waiting':
      return 'warning'
    case 'cancelled':
      return 'info'
    default:
      return 'danger'
  }
}

async function loadSms() {
  smsLoading.value = true
  try {
    const res = await integrationApi.listSmsOrders({
      page: smsPage.value,
      size: smsSize.value,
      status: smsFilters.status || undefined,
    })
    smsRows.value = res.list
    smsTotal.value = res.total
  } catch {
    /* 拦截器已提示 */
  } finally {
    smsLoading.value = false
  }
}

function reloadSms() {
  smsPage.value = 1
  loadSms()
}

function onSmsSizeChange() {
  smsPage.value = 1
  loadSms()
}

async function submitSms() {
  smsCreating.value = true
  try {
    const order = await integrationApi.createSmsOrder({ ...smsForm })
    ElMessage.success(`取号成功：${order.phone}`)
    smsDialogVisible.value = false
    reloadSms()
  } catch {
    /* 拦截器已提示 */
  } finally {
    smsCreating.value = false
  }
}

async function pollSms(row: SmsOrderRow) {
  smsBusy.value = row.id
  try {
    const order = await integrationApi.pollSmsOrder(row.id)
    if (order.code) ElMessage.success(`收到验证码：${order.code}`)
    else ElMessage.info('还没收到短信，稍后再试')
    loadSms()
  } catch {
    /* 拦截器已提示 */
  } finally {
    smsBusy.value = null
  }
}

async function waitSms(row: SmsOrderRow) {
  smsWaiting.value = row.id
  try {
    const res = await integrationApi.waitSmsOrder(row.id, { timeout: 180, interval: 5 })
    if (res.ok) ElMessage.success(`收到验证码：${res.code}`)
    else ElMessage.warning(res.detail || '未等到验证码')
    loadSms()
  } catch {
    /* 拦截器已提示 */
  } finally {
    smsWaiting.value = null
  }
}

async function cancelSms(row: SmsOrderRow) {
  try {
    await ElMessageBox.confirm(`确认取消订单 ${row.phone}？`, '取消接码订单', { type: 'warning' })
  } catch {
    return
  }
  try {
    await integrationApi.cancelSmsOrder(row.id)
    ElMessage.success('已取消')
    loadSms()
  } catch {
    /* 拦截器已提示 */
  }
}

// ---------- 采购订单 ----------
const productLoading = ref(false)
const products = ref<ProductRow[]>([])
const productProvider = ref('')
const purchaseLoading = ref(false)
const purchaseRows = ref<PurchaseOrderRow[]>([])
const purchaseTotal = ref(0)
const purchasePage = ref(1)
const purchaseSize = ref(20)
const purchaseFilters = reactive({ status: '', keyword: '' })
const purchaseDialogVisible = ref(false)
const purchasing = ref(false)
const purchaseForm = reactive({ product_id: '', name: '', stock: 0, quantity: 1, remark: '' })

function purchaseStatusType(value: string) {
  switch (value) {
    case 'delivered':
      return 'success'
    case 'pending':
      return 'warning'
    case 'failed':
      return 'danger'
    default:
      return 'info'
  }
}

async function loadProducts() {
  productLoading.value = true
  try {
    const res = await integrationApi.listProducts()
    products.value = res.list
    productProvider.value = res.provider
  } catch {
    /* 拦截器已提示 */
  } finally {
    productLoading.value = false
  }
}

async function loadPurchase() {
  purchaseLoading.value = true
  try {
    const res = await integrationApi.listPurchaseOrders({
      page: purchasePage.value,
      size: purchaseSize.value,
      status: purchaseFilters.status || undefined,
      keyword: purchaseFilters.keyword || undefined,
    })
    purchaseRows.value = res.list
    purchaseTotal.value = res.total
  } catch {
    /* 拦截器已提示 */
  } finally {
    purchaseLoading.value = false
  }
}

function reloadPurchase() {
  purchasePage.value = 1
  loadPurchase()
}

function onPurchaseSizeChange() {
  purchasePage.value = 1
  loadPurchase()
}

function resetPurchaseFilters() {
  purchaseFilters.status = ''
  purchaseFilters.keyword = ''
  reloadPurchase()
}

function openPurchase(product: ProductRow) {
  purchaseForm.product_id = product.product_id
  purchaseForm.name = product.name
  purchaseForm.stock = product.stock
  purchaseForm.quantity = 1
  purchaseForm.remark = ''
  purchaseDialogVisible.value = true
}

async function submitPurchase() {
  purchasing.value = true
  try {
    const order = await integrationApi.createPurchaseOrder({
      product_id: purchaseForm.product_id,
      quantity: purchaseForm.quantity,
      remark: purchaseForm.remark,
    })
    ElMessage.success(`下单成功：${order.order_no}`)
    purchaseDialogVisible.value = false
    loadPurchase()
  } catch {
    /* 拦截器已提示 */
  } finally {
    purchasing.value = false
  }
}

async function syncPurchase(row: PurchaseOrderRow) {
  try {
    const order = await integrationApi.syncPurchaseOrder(row.id)
    ElMessage.success(`订单状态：${PURCHASE_ORDER_STATUS_LABEL[order.status] || order.status}`)
    loadPurchase()
  } catch {
    /* 拦截器已提示 */
  }
}

async function removePurchase(row: PurchaseOrderRow) {
  try {
    await ElMessageBox.confirm(`确认删除订单 ${row.order_no}？`, '删除采购订单', { type: 'warning' })
  } catch {
    return
  }
  try {
    await integrationApi.removePurchaseOrder(row.id)
    ElMessage.success('已删除')
    loadPurchase()
  } catch {
    /* 拦截器已提示 */
  }
}

// ---------- 加载调度 ----------
function loadCurrent() {
  if (activeTab.value === 'providers') return loadStatus()
  if (activeTab.value === 'proxies') return loadProxies()
  if (activeTab.value === 'sms') return loadSms()
  return Promise.all([loadProducts(), loadPurchase()])
}

watch(activeTab, (tab) => {
  if (tab === 'providers' && !status.value) loadStatus()
  if (tab === 'proxies' && !proxyRows.value.length) loadProxies()
  if (tab === 'sms' && !smsRows.value.length) loadSms()
  if (tab === 'purchase' && !purchaseRows.value.length) {
    loadProducts()
    loadPurchase()
  }
})

async function loadAll() {
  loading.value = true
  try {
    await loadStatus()
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.provider-card {
  height: 100%;
}

.card-actions {
  margin-top: 12px;
}
</style>
