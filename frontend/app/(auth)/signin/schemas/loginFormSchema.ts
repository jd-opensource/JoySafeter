import { z } from 'zod'

/**
 * Login form schema using Zod validation.
 *
 * Basic format checks only -- the more thorough runtime validation
 * (disposable-email detection, MX-record lookup, etc.) stays in
 * `quickValidateEmail` and runs inside `onSubmit`.
 */
export const loginFormSchema = z.object({
  email: z.string().min(1, 'required').email('invalid format'),
  password: z.string().min(1, 'required'),
})

export type LoginFormData = z.infer<typeof loginFormSchema>
