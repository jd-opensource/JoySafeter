import SignupForm from '@/app/(auth)/signup/signup-form'
import { env, isTruthy } from '@/lib/core/config/env'

export const dynamic = 'force-dynamic'

export default async function SignupPage() {

  if (isTruthy(env.DISABLE_REGISTRATION)) {
    return <div>Registration is disabled, please contact your admin.</div>
  }

  return (
    <SignupForm
    />
  )
}
