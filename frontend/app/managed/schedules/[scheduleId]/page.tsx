import { redirect } from 'next/navigation'

/**
 * Old per-schedule links redirect to the unified Triggers list. Schedule ids do
 * not map 1:1 to the new trigger id space, so we send users to the list rather
 * than a detail page that may 404.
 */
export default function ScheduleDetailRedirectPage() {
  redirect('/managed/triggers')
}
