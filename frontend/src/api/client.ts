import axios, { AxiosError, AxiosResponse } from 'axios'

const BASE_URL = '/api/v1'

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 60_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ─── Request Interceptor ──────────────────────────────────────────────────────

apiClient.interceptors.request.use(
  (config) => {
    // 可在此处注入 Auth Token
    return config
  },
  (error) => Promise.reject(error),
)

// ─── Response Interceptor ─────────────────────────────────────────────────────

apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError<{ detail: string }>) => {
    const message =
      error.response?.data?.detail ??
      error.message ??
      '请求失败，请稍后重试'

    const enhancedError = new Error(message) as Error & {
      status: number | undefined
      originalError: AxiosError
    }
    enhancedError.status = error.response?.status
    enhancedError.originalError = error

    return Promise.reject(enhancedError)
  },
)

export default apiClient
