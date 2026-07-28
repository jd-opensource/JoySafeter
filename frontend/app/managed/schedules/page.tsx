import { redirect } from 'next/navigation'

/**
 * The Schedules stack was unified into Triggers (type=cron). This redirect keeps
 * old links/bookmarks working — /managed/schedules → /managed/triggers.
 */
export default function SchedulesRedirectPage() {
  redirect('/managed/triggers')
}
