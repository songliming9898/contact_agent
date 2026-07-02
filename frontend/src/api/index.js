import axios from 'axios'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 60000,
})

// ==================== 智能问数 ====================

/**
 * 流式聊天（SSE）— V1.1 支持 session_id
 * @param {string} question - 用户问题
 * @param {string} sessionId - 会话ID
 * @param {function} onMessage - 接收消息回调
 * @param {function} onDone - 完成回调(sessionId)
 * @param {function} onError - 错误回调
 */
export function streamChat(question, sessionId, onMessage, onDone, onError) {
  const baseURL = import.meta.env.VITE_API_BASE || ''
  const url = `${baseURL}/api/chat`

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id: sessionId }),
  })
    .then(async (response) => {
      if (!response.ok) {
        const err = await response.json()
        onError(err.detail || '请求失败')
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 解析 SSE 事件
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            // V1.1: done 事件可能包含 session_id
            if (data.startsWith('{') && data.includes('"session_id"')) {
              try {
                const doneData = JSON.parse(data)
                onDone(doneData.session_id)
              } catch {
                onDone()
              }
              return
            }
            if (data === '[DONE]') {
              onDone()
              return
            }
            onMessage(data)
          }
        }
      }

      // 处理剩余 buffer
      if (buffer.startsWith('data: ')) {
        const data = buffer.slice(6)
        if (data !== '[DONE]' && !data.startsWith('{')) {
          onMessage(data)
        }
      }
      onDone()
    })
    .catch((err) => {
      onError(err.message || '网络错误')
    })
}

/**
 * 同步聊天（备用）
 */
export async function syncChat(question, sessionId) {
  const response = await apiClient.post('/api/chat/sync', { question, session_id: sessionId })
  return response.data
}

// ==================== 后台管理 ====================

/**
 * 管理员登录
 */
export async function adminLogin(password) {
  const response = await apiClient.post('/api/admin/login', { password })
  return response.data
}

/**
 * 上传合同文件
 */
export async function uploadContracts(files, token) {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))

  const response = await apiClient.post('/api/admin/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
      Authorization: `Bearer ${token}`,
    },
  })
  return response.data
}

/**
 * 获取文档列表
 */
export async function getDocuments(token) {
  const response = await apiClient.get('/api/admin/documents', {
    headers: { Authorization: `Bearer ${token}` },
  })
  return response.data
}

/**
 * 获取系统状态
 */
export async function getStatus(token) {
  const response = await apiClient.get('/api/admin/status', {
    headers: { Authorization: `Bearer ${token}` },
  })
  return response.data
}

/**
 * 删除合同
 */
export async function deleteContract(filename, token) {
  const response = await apiClient.delete(`/api/admin/delete/${filename}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return response.data
}

export default apiClient
