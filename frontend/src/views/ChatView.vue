<template>
  <div class="chat-view">
    <!-- 顶部导航栏 -->
    <van-nav-bar title="合同问数助手" fixed>
      <template #right>
        <van-icon name="setting-o" size="20" @click="goAdmin" />
      </template>
    </van-nav-bar>

    <!-- 聊天消息列表 -->
    <div class="chat-messages" ref="messagesRef">
      <!-- 欢迎消息 -->
      <div v-if="messages.length === 0" class="welcome">
        <div class="welcome-icon">📋</div>
        <div class="welcome-title">合同智能问数助手</div>
        <div class="welcome-desc">基于 LangChain Agent，支持结构化查询和语义检索</div>
        <div class="welcome-tips">
          <div class="tip-title">试试这样问：</div>
          <div
            v-for="tip in tips"
            :key="tip"
            class="tip-item"
            @click="sendMessage(tip)"
          >
            {{ tip }}
          </div>
        </div>
      </div>

      <!-- 消息气泡 -->
      <div
        v-for="(msg, index) in messages"
        :key="index"
        :class="['message-wrapper', msg.role === 'user' ? 'message-user' : 'message-ai']"
      >
        <div class="message-avatar">
          {{ msg.role === 'user' ? '👤' : '🤖' }}
        </div>
        <div :class="['message-bubble', msg.role]">
          <!-- 用户消息 -->
          <div v-if="msg.role === 'user'" class="bubble-text">{{ msg.content }}</div>

          <!-- AI 消息 - Markdown 渲染 -->
          <div v-else class="bubble-text" v-html="renderMarkdown(msg.content)"></div>

          <!-- 加载动画 -->
          <div v-if="msg.loading" class="typing-indicator">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>

      <div class="bottom-safe"></div>
    </div>

    <!-- 底部输入区 -->
    <div class="chat-input-area">
      <div class="input-wrapper">
        <input
          ref="inputRef"
          v-model="inputText"
          class="chat-input"
          placeholder="输入合同相关问题..."
          @keyup.enter="sendMessage(inputText)"
          :disabled="loading"
        />
        <button
          class="send-btn"
          :class="{ disabled: !inputText.trim() || loading }"
          :disabled="!inputText.trim() || loading"
          @click="sendMessage(inputText)"
        >
          发送
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { marked } from 'marked'
import { streamChat } from '@/api'

const router = useRouter()

// 状态
const messages = ref([])
const inputText = ref('')
const loading = ref(false)
const messagesRef = ref(null)
const inputRef = ref(null)

// 推荐问题
const tips = [
  '合同总金额最高的三个合同是什么？',
  '所有合同中甲方为"XX科技"的有哪些？',
  '软件开发合同的付款节点有哪些？',
  '保密协议的保密期限是多久？',
  '尾款金额超过10万的合同有哪些？',
]

// Markdown 渲染
function renderMarkdown(text) {
  if (!text) return ''
  try {
    return marked.parse(text)
  } catch {
    return text.replace(/\n/g, '<br>')
  }
}

// 发送消息
function sendMessage(text) {
  const question = text?.trim()
  if (!question || loading.value) return

  // 添加用户消息
  messages.value.push({
    role: 'user',
    content: question,
  })

  // 添加 AI 占位消息
  const aiMsg = { role: 'ai', content: '', loading: true }
  messages.value.push(aiMsg)

  inputText.value = ''
  loading.value = true

  scrollToBottom()

  // 流式请求
  streamChat(
    question,
    // onMessage
    (chunk) => {
      aiMsg.content += chunk
      aiMsg.loading = false
      scrollToBottom()
    },
    // onDone
    () => {
      aiMsg.loading = false
      loading.value = false
      scrollToBottom()
    },
    // onError
    (error) => {
      aiMsg.content = `❌ ${error}`
      aiMsg.loading = false
      loading.value = false
    }
  )
}

// 滚动到底部
function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

// 跳转管理页
function goAdmin() {
  router.push('/admin')
}

onMounted(() => {
  inputRef.value?.focus()
})
</script>

<style scoped>
.chat-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f7f8fa;
}

/* 消息列表 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px 12px 0;
  margin-top: 46px;
  -webkit-overflow-scrolling: touch;
}

/* 欢迎区域 */
.welcome {
  text-align: center;
  padding: 40px 20px 20px;
}
.welcome-icon {
  font-size: 48px;
  margin-bottom: 12px;
}
.welcome-title {
  font-size: 20px;
  font-weight: 600;
  color: #323233;
  margin-bottom: 8px;
}
.welcome-desc {
  font-size: 13px;
  color: #969799;
  margin-bottom: 24px;
}
.welcome-tips {
  text-align: left;
  background: #fff;
  border-radius: 12px;
  padding: 16px;
}
.tip-title {
  font-size: 13px;
  color: #969799;
  margin-bottom: 10px;
}
.tip-item {
  font-size: 14px;
  color: #1989fa;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
  cursor: pointer;
}
.tip-item:last-child {
  border-bottom: none;
}
.tip-item:active {
  opacity: 0.7;
}

/* 消息气泡 */
.message-wrapper {
  display: flex;
  margin-bottom: 16px;
  align-items: flex-start;
}
.message-user {
  flex-direction: row-reverse;
}
.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #f0f0f0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.message-bubble {
  max-width: calc(100% - 56px);
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}
.message-user .message-bubble {
  background: #1989fa;
  color: #fff;
  margin-right: 8px;
  border-top-right-radius: 4px;
}
.message-ai .message-bubble {
  background: #fff;
  color: #323233;
  margin-left: 8px;
  border-top-left-radius: 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

/* AI 消息 Markdown 样式 */
.bubble-text :deep(p) {
  margin: 4px 0;
}
.bubble-text :deep(ul), .bubble-text :deep(ol) {
  padding-left: 20px;
  margin: 4px 0;
}
.bubble-text :deep(code) {
  background: #f5f5f5;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 13px;
}
.bubble-text :deep(pre) {
  background: #f5f5f5;
  padding: 8px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 12px;
}
.bubble-text :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  font-size: 12px;
}
.bubble-text :deep(th), .bubble-text :deep(td) {
  border: 1px solid #e5e5e5;
  padding: 4px 8px;
  text-align: left;
}
.bubble-text :deep(th) {
  background: #f5f5f5;
}
.bubble-text :deep(strong) {
  color: #1989fa;
}

/* 打字动画 */
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}
.typing-indicator span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #c8c9cc;
  animation: typing 1.4s infinite ease-in-out both;
}
.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
@keyframes typing {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

/* 底部输入区 */
.chat-input-area {
  background: #fff;
  padding: 8px 12px;
  padding-bottom: calc(8px + var(--safe-area-bottom));
  border-top: 1px solid #ebedf0;
}
.input-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chat-input {
  flex: 1;
  height: 40px;
  padding: 0 12px;
  border: 1px solid #ebedf0;
  border-radius: 20px;
  font-size: 14px;
  outline: none;
  background: #f7f8fa;
  transition: border-color 0.2s;
}
.chat-input:focus {
  border-color: #1989fa;
}
.chat-input::placeholder {
  color: #c8c9cc;
}
.send-btn {
  width: 56px;
  height: 40px;
  border: none;
  border-radius: 20px;
  background: #1989fa;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  flex-shrink: 0;
  transition: opacity 0.2s;
}
.send-btn.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.send-btn:active:not(.disabled) {
  opacity: 0.8;
}

.bottom-safe {
  height: 12px;
}
</style>
