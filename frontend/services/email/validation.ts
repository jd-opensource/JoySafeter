interface EmailValidationChecks {
  syntax: boolean
  domain: boolean
  mxRecord: boolean
  disposable: boolean
}

interface QuickEmailValidationResult {
  isValid: boolean
  reason?: string
  confidence: 'high' | 'medium' | 'low'
  checks: EmailValidationChecks
}

const DISPOSABLE_DOMAINS = new Set([
  '10minutemail.com',
  'tempmail.org',
  'guerrillamail.com',
  'mailinator.com',
  'yopmail.com',
  'temp-mail.org',
  'throwaway.email',
  'getnada.com',
  '10minutemail.net',
  'temporary-mail.net',
  'fakemailgenerator.com',
  'sharklasers.com',
  'guerrillamailblock.com',
  'pokemail.net',
  'spam4.me',
  'tempail.com',
  'tempr.email',
  'dispostable.com',
  'emailondeck.com',
])

function validateEmailSyntax(email: string): boolean {
  const emailRegex =
    /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/
  return emailRegex.test(email) && email.length <= 254
}

function isDisposableEmail(email: string): boolean {
  const domain = email.split('@')[1]?.toLowerCase()
  return domain ? DISPOSABLE_DOMAINS.has(domain) : false
}

function hasInvalidPatterns(email: string): boolean {
  if (email.includes('..')) return true
  const localPart = email.split('@')[0]
  if (localPart && localPart.length > 64) return true
  return false
}

export function quickValidateEmail(email: string): QuickEmailValidationResult {
  const checks: EmailValidationChecks = {
    syntax: false,
    domain: false,
    mxRecord: true,
    disposable: false,
  }

  checks.syntax = validateEmailSyntax(email)
  if (!checks.syntax) {
    return {
      isValid: false,
      reason: 'Invalid email format',
      confidence: 'high',
      checks,
    }
  }

  const domain = email.split('@')[1]?.toLowerCase()
  if (!domain) {
    return {
      isValid: false,
      reason: 'Missing domain',
      confidence: 'high',
      checks,
    }
  }

  checks.disposable = !isDisposableEmail(email)
  if (!checks.disposable) {
    return {
      isValid: false,
      reason: 'Disposable email addresses are not allowed',
      confidence: 'high',
      checks,
    }
  }

  if (hasInvalidPatterns(email)) {
    return {
      isValid: false,
      reason: 'Email contains suspicious patterns',
      confidence: 'medium',
      checks,
    }
  }

  checks.domain = domain.includes('.') && !domain.startsWith('.') && !domain.endsWith('.')
  if (!checks.domain) {
    return {
      isValid: false,
      reason: 'Invalid domain format',
      confidence: 'high',
      checks,
    }
  }

  return {
    isValid: true,
    confidence: 'medium',
    checks,
  }
}
