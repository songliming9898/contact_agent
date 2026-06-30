<template>
  <div class="admin-view">
    <!-- 登录面板 -->
    <div v-if="!loggedIn" class="login-panel">
      <div class="login-card">
        <div class="login-icon">🔐</div>
        <div class="login-title">后台管理</div>
        <div class="login-desc">请输入管理密码</div>
        <input
          v-model="password"
          type="password"
          class="login-input"
          placeholder="管理密码"
          @keyup.enter="doLogin"
        />
        <button class="login-btn" @click="doLogin">登 录</button>
        <div v-if="loginError" class="login-error">{{ loginError }}</div>
        <div class="login-back" @click="$router.push('/')">← 返回对话</div>
      </div>
    </div>

    <!-- 管理面板 -->
    <div v-else class="admin-panel">
      <!-- 导航栏 -->
      <van-nav-bar title="后台管理" fixed>
        <template #left>
          <van-icon name="arrow-left" size="20" @click="$router.push('/')" />
        </template>
        <template #right>
          <span class="logout-btn" @click="doLogout">退出</span>
        </template>
      </van-nav-bar>

      <div class="admin-content">
        <!-- 上传区域 -->
        <div class="section">
          <div class="section-title">📎 批量上传合同</div>
          <div class="section-body">
            <van-uploader
              v-model="fileList"
              :max-count="10"
              accept=".docx,.pdf"
              multiple
              :after-read="onFileRead"
            />
            <button
              v-if="fileList.length > 0"
              class="upload-btn"
              :disabled="uploading"
              @click="doUpload"
            >
              {{ uploading ? '上传解析中...' : `开始上传 (${fileList.length}个文件)` }}
            </button>
            <div v-if="uploadResult" class="upload-result">
              <div
                v-for="(r, i) in uploadResult"
                :key="i"
                :class="['result-item', r.status]"
              >
                <span class="result-file">{{ r.filename }}</span>
                <span v-if="r.status === 'success'" class="result-ok">✅ {{ r.contract_id }}</span>
                <span v-else class="result-err">❌ {{ r.error }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 系统状态 -->
        <div class="section">
          <div class="section-title">📊 系统状态</div>
          <div class="section-body">
            <div class="status-grid">
              <div class="status-item">
                <div class="status-value">{{ status.contracts_total || 0 }}</div>
                <div class="status-label">合同总数</div>
              </div>
              <div class="status-item">
                <div class="status-value">{{ status.amount_avg || 0 }}</div>
                <div class="status-label">平均金额(元)</div>
              </div>
              <div class="status-item">
                <div class="status-value">{{ status.amount_total || 0 }}</div>
                <div class="status-label">合同总额(元)</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 文档列表 -->
        <div class="section">
          <div class="section-title">📄 文档列表 ({{ documents.length }})</div>
          <div class="section-body">
            <div v-if="documents.length === 0" class="empty-tip">暂无已解析合同</div>
            <div v-for="doc in documents" :key="doc.contract_id" class="doc-item">
              <div class="doc-info">
                <div class="doc-name">{{ doc.file_name }}</div>
                <div class="doc-meta">
                  {{ doc.party_a }} ⟷ {{ doc.party_b }}
                </div>
                <div class="doc-meta">
                  {{ doc.contract_id }} · 
                  <span v-if="doc.total_amount">¥{{ doc.total_amount?.toLocaleString() }} · </span>
                  {{ doc.sign_date || '日期未知' }}
                </div>
              </div>
              <van-swipe-cell>
                <template #right>
                  <van-button
                    square
                    type="danger"
                    text="删除"
                    @click="doDelete(doc.contract_id)"
                  />
                </template>
              </van-swipe-cell>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { showToast, showConfirmDialog } from 'vant'
import { adminLogin, uploadContracts, getDocuments, getStatus, deleteContract } from '@/api'

// 登录状态
const loggedIn = ref(false)
const password = ref('')
const loginError = ref('')
const token = ref('')

// 管理数据
const fileList = ref([])
const uploading = ref(false)
const uploadResult = ref(null)
const documents = ref([])
const status = ref({})

// 登录
async function doLogin() {
  if (!password.value) return

  try {
    const res = await adminLogin(password.value)
    if (res.success) {
      token.value = res.token
      loggedIn.value = true
      loginError.value = ''
      await loadData()
    } else {
      loginError.value = res.message || '密码错误'
    }
  } catch (e) {
    loginError.value = '登录失败，请检查网络'
  }
}

// 退出
function doLogout() {
  loggedIn.value = false
  token.value = ''
  password.value = ''
}

// 加载数据
async function loadData() {
  try {
    const [docsRes, statusRes] = await Promise.all([
      getDocuments(token.value),
      getStatus(token.value),
    ])
    documents.value = docsRes.items || docsRes.documents || []
    status.value = statusRes
  } catch (e) {
    showToast('加载数据失败')
  }
}

// 文件读取
function onFileRead(file) {
  // Vant Uploader 自动添加到 fileList
}

// 上传
async function doUpload() {
  if (fileList.value.length === 0) return

  uploading.value = true
  uploadResult.value = null

  try {
    const rawFiles = fileList.value.map((f) => f.file)
    const res = await uploadContracts(rawFiles, token.value)
    uploadResult.value = res.results || []

    const successCount = uploadResult.value.filter((r) => r.status === 'success').length
    showToast(`上传完成：成功 ${successCount} 个`)

    // 清空文件列表
    fileList.value = []

    // 刷新数据
    await loadData()
  } catch (e) {
    showToast('上传失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    uploading.value = false
  }
}

// 删除合同
async function doDelete(contractId) {
  try {
    await showConfirmDialog({
      title: '确认删除',
      message: `确定要删除合同 "${contractId}" 吗？`,
    })
  } catch {
    return // 取消
  }

  try {
    await deleteContract(contractId, token.value)
    showToast('已删除')
    await loadData()
  } catch (e) {
    showToast('删除失败')
  }
}
</script>

<style scoped>
.admin-view {
  height: 100%;
  background: #f7f8fa;
}

/* ===== 登录面板 ===== */
.login-panel {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.login-card {
  width: 100%;
  max-width: 300px;
  background: #fff;
  border-radius: 16px;
  padding: 32px 24px;
  text-align: center;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
}
.login-icon {
  font-size: 40px;
  margin-bottom: 12px;
}
.login-title {
  font-size: 20px;
  font-weight: 600;
  color: #323233;
  margin-bottom: 6px;
}
.login-desc {
  font-size: 13px;
  color: #969799;
  margin-bottom: 24px;
}
.login-input {
  width: 100%;
  height: 44px;
  padding: 0 14px;
  border: 1px solid #ebedf0;
  border-radius: 8px;
  font-size: 15px;
  outline: none;
  margin-bottom: 16px;
}
.login-input:focus {
  border-color: #1989fa;
}
.login-btn {
  width: 100%;
  height: 44px;
  border: none;
  border-radius: 8px;
  background: #1989fa;
  color: #fff;
  font-size: 16px;
  cursor: pointer;
}
.login-btn:active {
  opacity: 0.8;
}
.login-error {
  color: #ee0a24;
  font-size: 13px;
  margin-top: 12px;
}
.login-back {
  margin-top: 16px;
  font-size: 14px;
  color: #1989fa;
  cursor: pointer;
}

/* ===== 管理面板 ===== */
.admin-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.admin-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  margin-top: 46px;
  -webkit-overflow-scrolling: touch;
}
.logout-btn {
  font-size: 14px;
  color: #fff;
  cursor: pointer;
}

/* 区块 */
.section {
  background: #fff;
  border-radius: 12px;
  margin-bottom: 12px;
  overflow: hidden;
}
.section-title {
  padding: 14px 16px 8px;
  font-size: 15px;
  font-weight: 600;
  color: #323233;
}
.section-body {
  padding: 8px 16px 14px;
}

/* 上传 */
.upload-btn {
  width: 100%;
  height: 40px;
  border: none;
  border-radius: 8px;
  background: #1989fa;
  color: #fff;
  font-size: 14px;
  margin-top: 12px;
  cursor: pointer;
}
.upload-btn:disabled {
  opacity: 0.5;
}
.upload-result {
  margin-top: 12px;
}
.result-item {
  font-size: 13px;
  padding: 6px 0;
  border-bottom: 1px solid #f5f5f5;
}
.result-file {
  display: block;
  color: #323233;
}
.result-ok {
  color: #07c160;
}
.result-err {
  color: #ee0a24;
}

/* 状态 */
.status-grid {
  display: flex;
  gap: 8px;
}
.status-item {
  flex: 1;
  text-align: center;
  background: #f7f8fa;
  border-radius: 8px;
  padding: 12px 8px;
}
.status-value {
  font-size: 22px;
  font-weight: 700;
  color: #1989fa;
}
.status-label {
  font-size: 12px;
  color: #969799;
  margin-top: 4px;
}

/* 文档列表 */
.doc-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid #f5f5f5;
}
.doc-item:last-child {
  border-bottom: none;
}
.doc-info {
  flex: 1;
}
.doc-name {
  font-size: 14px;
  font-weight: 500;
  color: #323233;
  margin-bottom: 2px;
}
.doc-meta {
  font-size: 12px;
  color: #969799;
}
.empty-tip {
  text-align: center;
  color: #c8c9cc;
  font-size: 14px;
  padding: 20px 0;
}
</style>
