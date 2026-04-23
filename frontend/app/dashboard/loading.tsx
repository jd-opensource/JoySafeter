export default function DashboardLoading() {
  return (
    <div className="flex h-full items-center justify-center bg-[var(--bg)]">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-[var(--border)] border-t-[var(--brand-500)]" />
    </div>
  )
}
