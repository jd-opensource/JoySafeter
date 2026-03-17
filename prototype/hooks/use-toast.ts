/**
 * Re-export toast from @/components/ui/use-toast for backwards compatibility.
 *
 * All toast usage should use the same underlying toast system (shadcn/ui)
 * to ensure toasts are properly rendered by the Toaster component.
 */
export { useToast, toast } from '@/components/ui/use-toast'
