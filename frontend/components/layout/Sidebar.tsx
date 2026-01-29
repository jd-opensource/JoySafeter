
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
  ShieldCheck
} from 'lucide-react';
import React, { useEffect, useState } from 'react';

import { ViewMode } from '../../types';

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
};
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
} from "../ui/alert-dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../ui/tooltip";

interface SidebarProps {
  onNewChat: () => void;
  onLoadHistory: (id: string) => void;
  activeView: ViewMode;
  onViewChange: (view: ViewMode) => void;
  refreshTrigger?: number;
}

const Sidebar: React.FC<SidebarProps> = ({ onNewChat, onLoadHistory, activeView, onViewChange, refreshTrigger = 0 }) => {
  const [historyItems, setHistoryItems] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleteId, setDeleteId] = useState<string | null>(null);

  const isCollapsed = activeView === 'builder' || activeView === 'skills';

  const loadHistory = async () => {
      setLoading(true);
      try {
          const sessions = await chatService.getSessions();
          setHistoryItems(sessions || []);
      } catch (e) {
          setHistoryItems([]);
      } finally {
          setLoading(false);
      }
  };

  useEffect(() => {
      loadHistory();
  }, [refreshTrigger]);

  const confirmDelete = async () => {
      if (deleteId) {
          try {
            await chatService.deleteSession(deleteId);
            setHistoryItems(prev => prev.filter(i => i.id !== deleteId));
          } finally {
            setDeleteId(null);
          }
      }
  };

  const NavButton = ({ 
    icon: Icon, 
    label, 
    isActive, 
    onClick, 
    rightAction 
  }: { 
    icon: any, 
    label: string, 
    isActive?: boolean, 
    onClick: () => void,
    rightAction?: React.ReactNode 
  }) => (
    <Tooltip>
        <TooltipTrigger asChild>
            <button 
              onClick={onClick}
              className={`
                w-full flex items-center gap-2 py-2 text-sm rounded-lg transition-colors group relative
                ${isCollapsed ? 'justify-center px-0' : 'px-2'}
                ${isActive ? 'bg-gray-100 text-gray-900 font-medium' : 'text-gray-600 hover:bg-gray-50'}
              `}
            >
              <Icon size={18} className={isActive ? (label === "Agent Builder" ? 'text-purple-600' : label === "Skills" ? 'text-emerald-600' : 'text-blue-600') : 'text-gray-400 group-hover:text-gray-600'} />
              {!isCollapsed && <span className="truncate">{label}</span>}
              {!isCollapsed && rightAction && (
                <div className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity">
                    {rightAction}
                </div>
              )}
            </button>
        </TooltipTrigger>
        {isCollapsed && <TooltipContent side="right">{label}</TooltipContent>}
    </Tooltip>
  );

  return (
    <TooltipProvider>
        <div 
            className={`
                h-full border-r border-gray-200 bg-white flex flex-col flex-shrink-0 z-20 relative select-none transition-all duration-300 ease-in-out
                ${isCollapsed ? 'w-16' : 'w-56'}
            `}
        >
        <div className={`flex items-center ${isCollapsed ? 'justify-center p-4' : 'pl-2 pr-4 py-4 gap-1.5'} border-b border-transparent h-14 min-w-0`}>
            <div className="w-6 h-6 bg-black rounded-full flex items-center justify-center flex-shrink-0">
                <div className="w-3 h-3 bg-white rounded-full"></div>
            </div>
            {!isCollapsed && <span className="font-bold text-[17px] tracking-tight text-gray-900 whitespace-nowrap">JoySafeter</span>}
        </div>

        <div className={`py-2 space-y-1 ${isCollapsed ? 'px-2' : 'px-2'}`}>
            <NavButton 
                icon={MessageSquare} 
                label="Chat Canvas" 
                isActive={activeView === 'chat'} 
                onClick={() => onViewChange('chat')} 
                rightAction={
                    <div onClick={(e) => { e.stopPropagation(); onNewChat(); }} className="p-1 hover:bg-gray-200 rounded text-gray-500" title="New Chat">
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
            <div className="flex-1 overflow-hidden flex flex-col mt-4">
                <div className="px-4">
                    <div className="flex items-center justify-between text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 group cursor-pointer hover:text-gray-600">
                    <span>Projects</span>
                    <Plus size={12} className="opacity-0 group-hover:opacity-100" />
                    </div>
                </div>
                <div className="px-3 flex-1 overflow-y-auto custom-scrollbar">
                    <div className="flex items-center justify-between text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-1 group cursor-pointer hover:text-gray-600">
                    <span>History</span>
                    <ChevronDown size={12} className="opacity-0 group-hover:opacity-100" />
                    </div>
                    {loading ? (
                        <div className="flex items-center justify-center py-4 text-gray-400 gap-2">
                            <Loader2 size={14} className="animate-spin" />
                        </div>
                    ) : (
                        <div className="space-y-1">
                            {historyItems.map(item => (
                                <div 
                                    key={item.id}
                                    onClick={() => onLoadHistory(item.id)}
                                    className="flex items-center justify-between gap-2 px-2 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg cursor-pointer group"
                                >
                                    <div className="flex items-center gap-2 overflow-hidden">
                                        <Clock size={12} className="text-gray-400 flex-shrink-0" />
                                        <span className="truncate">{item.title}</span>
                                    </div>
                                    <AlertDialog>
                                        <AlertDialogTrigger asChild>
                                             <button 
                                                onClick={(e) => { e.stopPropagation(); setDeleteId(item.id); }}
                                                className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 p-0.5"
                                            >
                                                <Trash2 size={12} />
                                            </button>
                                        </AlertDialogTrigger>
                                        <AlertDialogContent variant="destructive">
                                            <AlertDialogHeader>
                                                <AlertDialogTitle>Are you absolutely sure?</AlertDialogTitle>
                                                <AlertDialogDescription>Permanently delete this chat session?</AlertDialogDescription>
                                            </AlertDialogHeader>
                                            <AlertDialogFooter>
                                                <AlertDialogCancel>Cancel</AlertDialogCancel>
                                                <AlertDialogAction onClick={confirmDelete} className="bg-[#ef4444] text-white hover:bg-[#dc2626]">Delete</AlertDialogAction>
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

        <div className={`p-3 mt-auto border-t border-gray-200 bg-gray-50/50 ${isCollapsed ? 'flex flex-col items-center' : ''}`}>
            <div className={`flex items-center gap-2 p-1 hover:bg-gray-200/50 rounded-lg cursor-pointer transition-colors overflow-hidden ${isCollapsed ? 'justify-center w-full' : ''}`}>
                <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-xs font-medium text-white flex-shrink-0">ZY</div>
                {!isCollapsed && (
                    <div className="flex flex-col min-w-0">
                        <span className="text-sm font-medium text-gray-900 truncate">zhen yu</span>
                        <span className="text-[10px] text-gray-500 truncate">Settings</span>
                    </div>
                )}
            </div>
        </div>
        </div>
    </TooltipProvider>
  );
};

export default Sidebar;
