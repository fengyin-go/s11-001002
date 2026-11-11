/** 统一请求封装：拼后端地址、抛网络错误、给页脚留一句可读的说明。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

/** 动作接口统一返回体：业务成败看 ok，不能只看 HTTP 状态。 */
export interface ActionResult {
  ok: boolean
  message: string
  entry?: Record<string, unknown> | null
  token?: string | null
  duplicate?: boolean
}

async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    if (typeof payload.detail === 'string' && payload.detail) {
      return payload.detail
    }
  } catch {
    // 响应体不是 JSON 时退回通用文案。
  }
  return `${fallback}（HTTP ${response.status}）`
}

export interface ActionRequest {
  action: string
  token: string
}

/**
 * 提交一个业务动作。
 *
 * 动作走新协议放在请求体顶层，同时携带操作令牌 token 用于后端幂等；
 * 后端兼容旧协议 values.action。判定成败以响应体的 ok 字段为准——
 * HTTP 200 但 ok=false 属于业务拒绝，必须把后端原因抛给页面展示，
 * 不能假装操作完成。
 */
export async function postAction(
  path: string,
  payload: ActionRequest,
  fallback = '动作未生效',
): Promise<ActionResult> {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify({ action: payload.action, token: payload.token }),
  })
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, fallback))
  }
  const result = (await response.json()) as ActionResult
  if (!result.ok) {
    throw new Error(result.message || fallback)
  }
  return result
}

/** 生成操作令牌：同一按钮的重复点击共用一个令牌，后端只执行一次。 */
export function createActionToken(): string {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `act-${Date.now()}-${random}`
}
