// Maps backend error detail strings to i18n keys for user-facing messages.
// Unknown errors fall back to 'error.unknown'. Technical details are logged to console.

const DETAIL_MAP: Record<string, string> = {
  // login / credentials
  '用户名或密码错误': 'error.auth.invalidCredentials',
  // register
  '用户名已被占用': 'error.auth.usernameAlreadyTaken',
  '邮箱已被注册': 'error.auth.emailAlreadyRegistered',
  '该邮箱已被注册': 'error.auth.emailAlreadyRegistered',
  '该邮箱已被其他账号使用': 'error.auth.emailAlreadyUsed',
  '用户不存在': 'error.auth.userNotFound',
  '密码长度不能少于 8 位': 'error.auth.passwordTooShort',
  '人机验证失败，请刷新页面重试': 'error.auth.captchaFailed',
  // tokens / session
  '缺少 refresh_token': 'error.auth.missingRefreshToken',
  '无效或已过期的令牌': 'error.auth.missingRefreshToken',
  '令牌类型错误': 'error.auth.missingToken',
  '无效令牌': 'error.auth.missingToken',
  // reset password
  '邮箱未注册': 'error.auth.emailNotRegistered',
  // otp
  '验证码不存在或已过期': 'error.auth.codeExpired',
  '验证码尝试次数过多，请重新发送': 'error.auth.tooManyAttempts',
  '请等待 60 秒后再重新发送': 'error.auth.rateLimited',
  // world
  'World not found': 'error.world.notFound',
  'LLM not configured': 'error.llm.notConfigured',
  'Embedding provider not configured': 'error.llm.notConfigured',
  '未能获取该页面内容，请稍后重试': 'error.world.wikiPreviewFetchFailed',
  // 503 service errors
  'AI 服务繁忙，请稍后重试': 'error.llm.serviceBusy',
  'LLM 服务暂不可用，请稍后重试': 'error.llm.serviceUnavailable',
  // generic error handler responses
  'Internal server error': 'error.unknown',
  'Resource not found': 'error.world.notFound',
  // character
  '角色不存在': 'error.character.notFound',
  // report
  '举报原因不能为空': 'error.report.reasonRequired',
  '举报原因过长': 'error.report.reasonTooLong',
  '举报不存在': 'error.report.notFound',
  // staff management
  '无效的用户 ID': 'error.staff.invalidUserId',
  '不能修改管理员的内部账号权限': 'error.staff.cannotModifyAdmin',
  '不能修改自己的内部账号状态': 'error.staff.cannotModifySelf',
  '搜索词至少 2 个字符': 'error.staff.searchTooShort',
  // BYOK
  'API key 解密失败，请重新设置你的 API key': 'error.byok.decryptionFailed',
  'API key 验证失败，请检查 key 是否正确': 'error.byok.validationFailed',
  'API key 无效，请检查是否正确': 'error.byok.invalidKey',
  '验证超时，请检查网络连接': 'error.byok.timeout',
  '网络连接失败，请检查网络': 'error.byok.networkError',
  '验证请求过于频繁，请稍后再试（每分钟最多 5 次）': 'error.byok.rateLimited',
  '验证失败，请稍后重试': 'error.byok.validationFailed',
  'URL 格式无效': 'error.byok.invalidBaseUrl',
  'URL 必须使用 http 或 https 协议': 'error.byok.invalidBaseUrl',
  'URL 缺少主机名': 'error.byok.invalidBaseUrl',
  '不允许使用本地地址': 'error.byok.invalidBaseUrl',
  '不允许使用内网地址': 'error.byok.invalidBaseUrl',
  // welcome quotes
  '内容不能为空': 'error.quote.contentEmpty',
  '内容不能超过 40 个字符': 'error.quote.contentTooLong',
  '需要完成角色生成后才能提交感言': 'error.quote.noPermission',
  '提交过于频繁，请稍后再试': 'error.quote.rateLimited',
  '感言不存在': 'error.quote.notFound',
  '无效的感言 ID': 'error.quote.invalidId',
}

export function parseApiError(error: unknown, t: (key: string) => string): string {
  const axiosError = error as any
  const status: number | undefined = axiosError?.response?.status
  const detail: unknown = axiosError?.response?.data?.detail

  // Only log status in production, full detail in development
  if (import.meta.env.DEV) {
    console.error('[API Error]', { status, detail, message: axiosError?.message })
  } else {
    console.error('[API Error]', { status })
  }

  if (typeof detail === 'string') {
    if (DETAIL_MAP[detail]) return t(DETAIL_MAP[detail])
    // dynamic patterns
    if (detail.startsWith('验证码错误')) return t('error.auth.invalidCode')
    if (detail.startsWith('请等待') && detail.includes('秒')) return t('error.auth.rateLimited')
    if (detail.startsWith('无法删除')) return t('error.cannotDelete')
  }

  // HTTP status fallbacks (only when detail has no specific mapping)
  if (status === 401) return t('error.auth.missingToken')
  if (status === 403) return t('error.auth.forbidden')
  if (status === 409) return t('error.unknown')
  if (status === 422) {
    // Pydantic validation errors: try to extract field-specific message
    if (Array.isArray(detail) && detail.length > 0) {
      const firstError = detail[0]
      if (firstError.loc && Array.isArray(firstError.loc)) {
        const field = firstError.loc[firstError.loc.length - 1]
        // Map known fields to user-friendly messages
        if (field === 'rpm') return t('error.validation.rpm')
        if (field === 'provider') return t('error.validation.provider')
        if (field === 'key') return t('error.validation.key')
      }
    }
    return t('error.validation')
  }
  if (status === 429) return t('error.auth.rateLimited')
  if (status === 503) {
    // 503 错误：有 detail 时走通用繁忙提示，无 detail 时降级为未配置
    if (typeof detail === 'string' && detail) {
      return t('error.llm.serviceBusy')
    }
    return t('error.llm.notConfigured')
  }

  return t('error.unknown')
}
