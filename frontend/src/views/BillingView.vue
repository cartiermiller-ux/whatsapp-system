<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2>余额与计费</h2>
        <div class="sub">余额 · 消费流水 · 充值 · 计费规则</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
    </div>

    <!-- 余额概览 -->
    <el-row :gutter="16">
      <el-col :xs="12" :md="6">
        <div class="stat-card stat-card-gap">
          <div class="label">当前余额（{{ balance.currency }}）</div>
          <div class="value" style="color: #25d366">{{ balance.balance }}</div>
          <div class="hint">更新于 {{ formatDateTime(balance.updated_at) }}</div>
        </div>
      </el-col>
      <el-col :xs="12" :md="6">
        <div class="stat-card stat-card-gap">
          <div class="label">累计充值</div>
          <div class="value" style="color: #409eff">{{ balance.total_recharge }}</div>
          <div class="hint">单位 {{ balance.currency }}</div>
        </div>
      </el-col>
      <el-col :xs="12" :md="6">
        <div class="stat-card stat-card-gap">
          <div class="label">累计消费</div>
          <div class="value" style="color: #e6a23c">{{ balance.total_consume }}</div>
          <div class="hint">单位 {{ balance.currency }}</div>
        </div>
      </el-col>
      <el-col :xs="12" :md="6">
        <div class="stat-card stat-card-gap">
          <div class="label">待支付订单</div>
          <div class="value" style="color: #f56c6c">{{ balance.pending_orders }}</div>
          <div class="hint">未到账的充值订单</div>
        </div>
      </el-col>
    </el-row>

    <!-- 充值 -->
    <el-card shadow="never" class="section-gap">
      <template #header>
        <div class="card-header">
          <span>{{ currency }} 充值</span>
          <span class="muted">单笔最低 {{ minAmount }} {{ currency }}</span>
        </div>
      </template>

      <el-alert
        v-if="!address"
        class="block-gap"
        type="warning"
        show-icon
        :closable="false"
        title="尚未配置收款地址，无法创建充值订单"
        description="请前往「系统设置 -> 计费与充值」配置收款地址（recharge_address）与收款链（recharge_chain），保存后返回本页刷新。"
      />

      <el-form label-width="100px" @submit.prevent>
        <el-form-item label="充值金额">
          <el-input-number v-model="amount" :min="minAmount" :step="10" />
          <span class="muted unit">{{ currency }}</span>
        </el-form-item>
        <el-form-item label="收款地址">
          <el-input :model-value="address" readonly placeholder="未配置，请先在系统设置中填写" />
          <el-button class="unit" :icon="CopyDocument" :disabled="!address" @click="copyAddress">
            复制
          </el-button>
        </el-form-item>
        <el-form-item label="链">
          <el-input :model-value="chain" readonly placeholder="未配置" />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="recharging"
            :disabled="!canRecharge"
            @click="createRecharge"
          >
            创建充值订单
          </el-button>
          <span class="muted unit">
            充值到账需人工确认（模拟到账接口，链上回调接入前使用）
          </span>
        </el-form-item>
      </el-form>

      <el-divider content-position="left">充值订单</el-divider>

      <el-table v-loading="ordersLoading" :data="orders" stripe>
        <el-table-column prop="order_no" label="订单号" min-width="200" show-overflow-tooltip />
        <el-table-column label="金额" width="140">
          <template #default="{ row }">{{ row.amount }} {{ row.currency }}</template>
        </el-table-column>
        <el-table-column prop="chain" label="链" width="100" />
        <el-table-column prop="address" label="收款地址" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">
              {{ ORDER_STATUS_LABEL[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="到期时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.expire_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <el-button link type="primary" :icon="CircleCheck" @click="confirmOrder(row)">
                确认到账
              </el-button>
              <el-button link type="danger" @click="cancelOrder(row)">取消</el-button>
            </template>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无充值订单" />
        </template>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="ordersPage"
          v-model:page-size="ordersSize"
          :page-sizes="[10, 20, 50]"
          :total="ordersTotal"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="loadOrders"
          @size-change="onOrdersSizeChange"
        />
      </div>
    </el-card>

    <!-- 余额消费流水 -->
    <el-card shadow="never" class="section-gap">
      <template #header>
        <div class="card-header">
          <span>余额消费流水</span>
          <span class="muted">{{ txTotal }} 条</span>
        </div>
      </template>

      <div class="filter-bar">
        <el-select v-model="txFilters.type" placeholder="流水类型" style="width: 150px" clearable>
          <el-option
            v-for="(label, key) in TRANSACTION_TYPE_LABEL"
            :key="key"
            :label="label"
            :value="key"
          />
        </el-select>
        <el-input
          v-model="txFilters.keyword"
          placeholder="搜索任务 / 备注 / 国家"
          style="width: 220px"
          :prefix-icon="Search"
          clearable
          @keyup.enter="reloadTransactions"
        />
        <el-button type="primary" :icon="Search" @click="reloadTransactions">查询</el-button>
        <el-button @click="resetTxFilters">重置</el-button>
      </div>

      <el-table v-loading="txLoading" :data="transactions" stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="流水类型" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">
              {{ TRANSACTION_TYPE_LABEL[row.type] || row.type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="金额" width="130">
          <template #default="{ row }">
            <span :style="{ color: row.amount < 0 ? '#f56c6c' : '#25d366' }">
              {{ row.amount }} {{ row.currency }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="balance_before" label="余额(前)" width="110" />
        <el-table-column prop="balance_after" label="余额(后)" width="110" />
        <el-table-column prop="country" label="计费国家" width="110" />
        <el-table-column prop="task" label="任务" min-width="140" show-overflow-tooltip />
        <el-table-column label="结果" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.result)" size="small">
              {{ row.result === 'success' ? '成功' : row.result }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无流水记录" />
        </template>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="txPage"
          v-model:page-size="txSize"
          :page-sizes="[10, 20, 50]"
          :total="txTotal"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="loadTransactions"
          @size-change="onTxSizeChange"
        />
      </div>
    </el-card>

    <!-- 国家收费规则 -->
    <el-card shadow="never" class="section-gap">
      <template #header>
        <div class="card-header">
          <span>国家收费规则</span>
          <span class="muted">{{ rules.length }} 条</span>
        </div>
      </template>
      <el-table v-loading="rulesLoading" :data="rules" stripe>
        <el-table-column prop="country" label="国家代码" width="120" />
        <el-table-column prop="country_name" label="国家" min-width="160" />
        <el-table-column prop="dimension" label="计费维度" width="160" />
        <el-table-column label="单价" width="160">
          <template #default="{ row }">{{ row.unit_price }} {{ row.currency }}</template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无计费规则" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search, CopyDocument, CircleCheck } from '@element-plus/icons-vue'
import { billingApi } from '@/api'
import type { BalanceInfo, BillingRule, RechargeOrder, TransactionRow } from '@/types/api'
import {
  ORDER_STATUS_LABEL,
  TRANSACTION_TYPE_LABEL,
  formatDateTime,
  statusTagType,
} from '@/utils/format'

const loading = ref(false)

// ---------- 余额概览 ----------
const balance = ref<BalanceInfo>({
  balance: 0,
  currency: 'USDT',
  total_recharge: 0,
  total_consume: 0,
  pending_orders: 0,
  updated_at: null,
})

async function loadBalance() {
  try {
    balance.value = await billingApi.balance()
  } catch {
    /* 拦截器已提示 */
  }
}

// ---------- 充值 ----------
const ordersLoading = ref(false)
const orders = ref<RechargeOrder[]>([])
const ordersTotal = ref(0)
const ordersPage = ref(1)
const ordersSize = ref(20)
const address = ref('')
const chain = ref('')
const currency = ref('USDT')
const minAmount = ref(0)
const amount = ref(0)
const recharging = ref(false)

const canRecharge = computed(() => !!address.value && amount.value >= minAmount.value)

async function loadOrders() {
  ordersLoading.value = true
  try {
    const res = await billingApi.orders({ page: ordersPage.value, size: ordersSize.value })
    orders.value = res.list
    ordersTotal.value = res.total
    address.value = res.address
    chain.value = res.chain
    currency.value = res.currency
    minAmount.value = res.min_amount
    if (!amount.value || amount.value < res.min_amount) amount.value = res.min_amount
  } catch {
    /* 拦截器已提示 */
  } finally {
    ordersLoading.value = false
  }
}

function onOrdersSizeChange() {
  ordersPage.value = 1
  loadOrders()
}

async function copyAddress() {
  if (!address.value) return
  try {
    await navigator.clipboard.writeText(address.value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败，请手动复制')
  }
}

async function createRecharge() {
  if (!canRecharge.value) return
  recharging.value = true
  try {
    const order = await billingApi.recharge(amount.value)
    ElMessage.success(`充值订单已创建：${order.order_no}`)
    await refreshAccountData()
  } catch {
    /* 拦截器已提示 */
  } finally {
    recharging.value = false
  }
}

async function confirmOrder(row: RechargeOrder) {
  try {
    await ElMessageBox.confirm(
      `确认订单 ${row.order_no} 已收到 ${row.amount} ${row.currency}？这是模拟到账接口（链上回调接入前使用），确认后余额立即增加。`,
      '确认到账',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const res = await billingApi.confirmOrder(row.id)
    ElMessage.success(`订单 ${row.order_no} 已确认到账，当前余额 ${res.balance} ${balance.value.currency}`)
    await refreshAccountData()
  } catch {
    /* 拦截器已提示 */
  }
}

async function cancelOrder(row: RechargeOrder) {
  try {
    await ElMessageBox.confirm(`确认取消充值订单 ${row.order_no}？取消后该订单不可恢复。`, '取消订单', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await billingApi.cancelOrder(row.id)
    ElMessage.success('订单已取消')
    await refreshAccountData()
  } catch {
    /* 拦截器已提示 */
  }
}

// ---------- 消费流水 ----------
const txLoading = ref(false)
const transactions = ref<TransactionRow[]>([])
const txTotal = ref(0)
const txPage = ref(1)
const txSize = ref(20)
const txFilters = reactive({ type: '', keyword: '' })

async function loadTransactions() {
  txLoading.value = true
  try {
    const res = await billingApi.transactions({
      page: txPage.value,
      size: txSize.value,
      type: txFilters.type || undefined,
      keyword: txFilters.keyword || undefined,
    })
    transactions.value = res.list
    txTotal.value = res.total
  } catch {
    /* 拦截器已提示 */
  } finally {
    txLoading.value = false
  }
}

function reloadTransactions() {
  txPage.value = 1
  loadTransactions()
}

function onTxSizeChange() {
  txPage.value = 1
  loadTransactions()
}

function resetTxFilters() {
  txFilters.type = ''
  txFilters.keyword = ''
  reloadTransactions()
}

// ---------- 计费规则 ----------
const rulesLoading = ref(false)
const rules = ref<BillingRule[]>([])

async function loadRules() {
  rulesLoading.value = true
  try {
    rules.value = await billingApi.rules()
  } catch {
    /* 拦截器已提示 */
  } finally {
    rulesLoading.value = false
  }
}

// ---------- 汇总加载 ----------
/** 余额 + 充值订单 + 流水（充值/确认/取消后刷新） */
async function refreshAccountData() {
  await Promise.all([loadBalance(), loadOrders(), loadTransactions()])
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([refreshAccountData(), loadRules()])
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)
</script>


