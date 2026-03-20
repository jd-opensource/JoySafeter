import {
  Plus,
  LayoutGrid,
  Compass,
  ChevronDown,
  Clock,
  MessageSquare,
  Workflow,
  Loader2,
  Trash2,
  Settings,
  ShieldCheck,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import { ViewMode } from '../../types'

// Local type definition (chatService was removed as empty stub)
interface ChatSession {
  id: string
  title: string
  messages: any[]
  updatedAt: number
}

// Empty stub for backward compatibility (component not actively used)
const chatService = {
  getSessions: async (): Promise<ChatSession[]> => [],
  deleteSession: async (_id: string): Promise<void> => {},
}
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '../ui/alert-dialog'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../ui/tooltip'

interface SidebarProps {
  onNewChat: () => void
  onLoadHistory: (id: string) => void
  activeView: ViewMode
  onViewChange: (view: ViewMode) => void
  refreshTrigger?: number
}

export default function Sidebar({
  onNewChat,
  onLoadHistory,
  activeView,
  onViewChange,
  refreshTrigger = 0,
}: SidebarProps) {
  const [historyItems, setHistoryItems] = useState<ChatSession[]>([])
  const [loading, setLoading] = useState(true)
  const [deleteId, setDeleteId] = useState<string | null>(null)

  const isCollapsed = activeView === 'builder' || activeView === 'skills'

  const loadHistory = async () => {
    setLoading(true)
    try {
      const sessions = await chatService.getSessions()
      setHistoryItems(sessions || [])
    } catch (e) {
      setHistoryItems([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadHistory()
  }, [refreshTrigger])

  const confirmDelete = async () => {
    if (deleteId) {
      try {
        await chatService.deleteSession(deleteId)
        setHistoryItems((prev) => prev.filter((i) => i.id !== deleteId))
      } finally {
        setDeleteId(null)
      }
    }
  }

  const NavButton = ({
    icon: Icon,
    label,
    isActive,
    onClick,
    rightAction,
  }: {
    icon: any
    label: string
    isActive?: boolean
    onClick: () => void
    rightAction?: React.ReactNode
  }) => (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onClick}
          className={`group relative flex w-full items-center gap-2 rounded-lg py-2 text-sm transition-colors ${isCollapsed ? 'justify-center px-0' : 'px-2'} ${isActive ? 'bg-gray-100 font-medium text-gray-900' : 'text-gray-600 hover:bg-gray-50'} `}
        >
          <Icon
            size={18}
            className={
              isActive
                ? label === 'Agent Builder'
                  ? 'text-purple-600'
                  : label === 'Skills'
                    ? 'text-emerald-600'
                    : 'text-blue-600'
                : 'text-gray-400 group-hover:text-gray-600'
            }
          />
          {!isCollapsed && <span className="truncate">{label}</span>}
          {!isCollapsed && rightAction && (
            <div className="ml-auto opacity-0 transition-opacity group-hover:opacity-100">
              {rightAction}
            </div>
          )}
        </button>
      </TooltipTrigger>
      {isCollapsed && <TooltipContent side="right">{label}</TooltipContent>}
    </Tooltip>
  )

  return (
    <TooltipProvider>
      <div
        className={`relative z-20 flex h-full flex-shrink-0 select-none flex-col border-r border-gray-200 bg-white transition-all duration-300 ease-in-out ${isCollapsed ? 'w-16' : 'w-56'} `}
      >
        <div
          className={`flex items-center ${isCollapsed ? 'justify-center p-4' : 'gap-1.5 py-4 pl-2 pr-4'} h-14 min-w-0 border-b border-transparent`}
        >
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-black">
            <div className="h-3 w-3 rounded-full bg-white"></div>
          </div>
          {!isCollapsed && (
            <span className="whitespace-nowrap text-[17px] font-bold tracking-tight text-gray-900">
              JoySafeter
            </span>
          )}
        </div>

        <div className={`space-y-1 py-2 ${isCollapsed ? 'px-2' : 'px-2'}`}>
          <NavButton
            icon={MessageSquare}
            label="Chat Canvas"
            isActive={activeView === 'chat'}
            onClick={() => onViewChange('chat')}
            rightAction={
              <div
                onClick={(e) => {
                  e.stopPropagation()
                  onNewChat()
                }}
                className="rounded p-1 text-gray-500 hover:bg-gray-200"
                title="New Chat"
              >
                <Plus size={14} />
              </div>
            }
          />
          <NavButton
            icon={Workflow}
            label="Agent Builder"
            isActive={activeView === 'builder'}
            onClick={() => onViewChange('builder')}
          />
          <NavButton
            icon={ShieldCheck}
            label="Skills"
            isActive={activeView === 'skills'}
            onClick={() => onViewChange('skills')}
          />
          <NavButton icon={Compass} label="Discover" onClick={() => {}} />
        </div>

        {!isCollapsed && (
          <div className="mt-4 flex flex-1 flex-col overflow-hidden">
            <div className="px-4">
              <div className="group mb-2 flex cursor-pointer items-center justify-between text-xs font-semibold uppercase tracking-wider text-gray-400 hover:text-gray-600">
                <span>Projects</span>
                <Plus size={12} className="opacity-0 group-hover:opacity-100" />
              </div>
            </div>
            <div className="custom-scrollbar flex-1 overflow-y-auto px-3">
              <div className="group mb-2 flex cursor-pointer items-center justify-between px-1 text-xs font-semibold uppercase tracking-wider text-gray-400 hover:text-gray-600">
                <span>History</span>
                <ChevronDown size={12} className="opacity-0 group-hover:opacity-100" />
              </div>
              {loading ? (
                <div className="flex items-center justify-center gap-2 py-4 text-gray-400">
                  <Loader2 size={14} className="animate-spin" />
                </div>
              ) : (
                <div className="space-y-1">
                  {historyItems.map((item) => (
                    <div
                      key={item.id}
                      onClick={() => onLoadHistory(item.id)}
                      className="group flex cursor-pointer items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-sm text-gray-600 hover:bg-gray-100"
                    >
                      <div className="flex items-center gap-2 overflow-hidden">
                        <Clock size={12} className="flex-shrink-0 text-gray-400" />
                        <span className="truncate">{item.title}</span>
                      </div>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              setDeleteId(item.id)
                            }}
                            className="p-0.5 text-gray-400 opacity-0 hover:text-red-500 group-hover:opacity-100"
                          >
                            <Trash2 size={12} />
                          </button>
                        </AlertDialogTrigger>
                        <AlertDialogContent variant="destructive">
                          <AlertDialogHeader>
                            <AlertDialogTitle>Are you absolutely sure?</AlertDialogTitle>
                            <AlertDialogDescription>
                              Permanently delete this chat session?
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction
                              onClick={confirmDelete}
                              className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
                            >
                              Delete
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        <div
          className={`mt-auto border-t border-gray-200 bg-gray-50/50 p-3 ${isCollapsed ? 'flex flex-col items-center' : ''}`}
        >
          <div
            className={`flex cursor-pointer items-center gap-2 overflow-hidden rounded-lg p-1 transition-colors hover:bg-gray-200/50 ${isCollapsed ? 'w-full justify-center' : ''}`}
          >
            <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-medium text-white">
              ZY
            </div>
            {!isCollapsed && (
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-sm font-medium text-gray-900">zhen yu</span>
                <span className="truncate text-[10px] text-gray-500">Settings</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </TooltipProvider>
  )
}
