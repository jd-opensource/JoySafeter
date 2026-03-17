'use client';

import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
    RefreshCw,
    StopCircle,
    Trash2,
    PlayCircle,
    RotateCcw,
    Cpu,
    MemoryStick,
    Clock,
    Box,
    Loader2,
    User,
    Activity
} from 'lucide-react';
import { useToast } from '@/components/ui/use-toast';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@/components/ui/tooltip';
import { sandboxService, Sandbox } from '@/services/sandbox-service';
import { cn } from '@/lib/utils';
import { formatDistanceToNow } from 'date-fns';

export const SandboxesPage = () => {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [sandboxes, setSandboxes] = useState<Sandbox[]>([]);
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState<string | null>(null);
    const [confirmDialog, setConfirmDialog] = useState<{
        type: 'stop' | 'restart' | 'rebuild' | 'delete';
        sandboxId: string;
        open: boolean;
    }>({ type: 'stop', sandboxId: '', open: false });

    const fetchSandboxes = async () => {
        try {
            const response = await sandboxService.listSandboxes(1, 100);
            setSandboxes(response.items);
        } catch (error) {
            toast({
                title: t('settings.sandboxes.operationFailed'),
                description: String(error),
                variant: 'destructive',
            });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchSandboxes();
        const interval = setInterval(fetchSandboxes, 30000);
        return () => clearInterval(interval);
    }, []);

    const handleAction = async () => {
        if (!confirmDialog.sandboxId) return;

        setActionLoading(confirmDialog.sandboxId);
        try {
            switch (confirmDialog.type) {
                case 'stop':
                    await sandboxService.stopSandbox(confirmDialog.sandboxId);
                    break;
                case 'restart':
                    await sandboxService.restartSandbox(confirmDialog.sandboxId);
                    break;
                case 'rebuild':
                    await sandboxService.rebuildSandbox(confirmDialog.sandboxId);
                    break;
                case 'delete':
                    await sandboxService.deleteSandbox(confirmDialog.sandboxId);
                    break;
            }
            toast({
                title: t('settings.sandboxes.operationSuccess'),
            });
            fetchSandboxes();
        } catch (error) {
            toast({
                title: t('settings.sandboxes.operationFailed'),
                description: String(error),
                variant: 'destructive',
            });
        } finally {
            setActionLoading(null);
            setConfirmDialog(prev => ({ ...prev, open: false }));
        }
    };

    const getStatusConfig = (status: string) => {
        switch (status.toLowerCase()) {
            case 'running':
                return {
                    color: 'bg-emerald-50 text-emerald-700 border-emerald-200',
                    dot: 'bg-emerald-500',
                    animate: true
                };
            case 'creating':
                return {
                    color: 'bg-blue-50 text-blue-700 border-blue-200',
                    dot: 'bg-blue-500',
                    animate: true
                };
            case 'stopped':
                return {
                    color: 'bg-gray-50 text-gray-600 border-gray-200',
                    dot: 'bg-gray-400',
                    animate: false
                };
            case 'failed':
                return {
                    color: 'bg-red-50 text-red-700 border-red-200',
                    dot: 'bg-red-500',
                    animate: false
                };
            default:
                return {
                    color: 'bg-gray-50 text-gray-600 border-gray-200',
                    dot: 'bg-gray-400',
                    animate: false
                };
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center h-full min-h-[400px]">
                <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
            </div>
        );
    }

    return (
        <TooltipProvider>
            <div className="flex flex-col h-full">
                {/* Header */}
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 shadow-sm">
                            <Box className="h-5 w-5 text-white" />
                        </div>
                        <div>
                            <h2 className="text-lg font-bold text-gray-900 tracking-tight">
                                {t('settings.sandboxes.title')}
                            </h2>
                            <p className="text-xs text-gray-500 mt-0.5">
                                {t('settings.sandboxes.description')}
                            </p>
                        </div>
                    </div>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => { setLoading(true); fetchSandboxes(); }}
                        className="gap-2 rounded-lg border-gray-200 hover:bg-gray-50 hover:border-gray-300 transition-all"
                    >
                        <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
                        <span className="text-xs font-medium">{t('settings.sandboxes.refresh')}</span>
                    </Button>
                </div>

                {/* Stats Bar */}
                <div className="flex items-center gap-4 mb-4 px-1">
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                        <Activity className="h-3.5 w-3.5" />
                        <span>
                            {sandboxes.filter(s => s.status === 'running').length} {t('settings.sandboxes.running', 'running')}
                        </span>
                    </div>
                    <div className="h-3 w-px bg-gray-200" />
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                        <User className="h-3.5 w-3.5" />
                        <span>{sandboxes.length} {t('settings.sandboxes.total', 'total')}</span>
                    </div>
                </div>

                {/* Table Container */}
                <div className="border border-gray-200 rounded-xl overflow-hidden flex-1 flex flex-col bg-white shadow-sm">
                    <div className="flex-1 overflow-auto">
                        <Table>
                            <TableHeader>
                                <TableRow className="bg-gray-50/80 hover:bg-gray-50/80">
                                    <TableHead className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider py-3">
                                        {t('settings.sandboxes.user')}
                                    </TableHead>
                                    <TableHead className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider py-3">
                                        {t('settings.sandboxes.status')}
                                    </TableHead>
                                    <TableHead className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider py-3">
                                        {t('settings.sandboxes.resources')}
                                    </TableHead>
                                    <TableHead className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider py-3">
                                        {t('settings.sandboxes.runtime')}
                                    </TableHead>
                                    <TableHead className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider py-3">
                                        {t('settings.sandboxes.lastActive')}
                                    </TableHead>
                                    <TableHead className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider py-3 text-right">
                                        {t('settings.sandboxes.actions')}
                                    </TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {sandboxes.length === 0 ? (
                                    <TableRow>
                                        <TableCell colSpan={6} className="text-center py-16">
                                            <div className="flex flex-col items-center gap-3">
                                                <div className="p-4 rounded-full bg-gray-100 border border-gray-200">
                                                    <Box className="h-8 w-8 text-gray-300" />
                                                </div>
                                                <p className="text-sm font-medium text-gray-500">
                                                    {t('settings.sandboxes.noSandboxes')}
                                                </p>
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                ) : (
                                    sandboxes.map((sandbox) => {
                                        const statusConfig = getStatusConfig(sandbox.status);
                                        return (
                                            <TableRow
                                                key={sandbox.id}
                                                className="group hover:bg-gray-50/50 transition-colors"
                                            >
                                                <TableCell className="py-3">
                                                    <div className="flex items-center gap-3">
                                                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-gray-100 to-gray-200 flex items-center justify-center">
                                                            <User className="h-4 w-4 text-gray-500" />
                                                        </div>
                                                        <div className="flex flex-col">
                                                            <span className="text-sm font-medium text-gray-900">
                                                                {sandbox.user?.name || sandbox.user?.email || 'Unknown'}
                                                            </span>
                                                            <span className="text-[10px] text-gray-400 font-mono">
                                                                {sandbox.id.substring(0, 8)}...
                                                            </span>
                                                        </div>
                                                    </div>
                                                </TableCell>
                                                <TableCell className="py-3">
                                                    <Badge
                                                        variant="outline"
                                                        className={cn(
                                                            "gap-1.5 px-2 py-0.5 text-[11px] font-medium rounded-full",
                                                            statusConfig.color
                                                        )}
                                                    >
                                                        <span className={cn(
                                                            "w-1.5 h-1.5 rounded-full",
                                                            statusConfig.dot,
                                                            statusConfig.animate && "animate-pulse"
                                                        )} />
                                                        {sandbox.status}
                                                    </Badge>
                                                </TableCell>
                                                <TableCell className="py-3">
                                                    <div className="flex items-center gap-3">
                                                        <div className="flex items-center gap-1.5 text-xs text-gray-600">
                                                            <Cpu className="h-3.5 w-3.5 text-gray-400" />
                                                            <span className="font-medium">{sandbox.cpu_limit}</span>
                                                        </div>
                                                        <div className="h-3 w-px bg-gray-200" />
                                                        <div className="flex items-center gap-1.5 text-xs text-gray-600">
                                                            <MemoryStick className="h-3.5 w-3.5 text-gray-400" />
                                                            <span className="font-medium">{sandbox.memory_limit}M</span>
                                                        </div>
                                                    </div>
                                                </TableCell>
                                                <TableCell className="py-3">
                                                    {sandbox.status === 'running' && sandbox.created_at ? (
                                                        <div className="flex items-center gap-1.5 text-xs text-emerald-600">
                                                            <Clock className="h-3.5 w-3.5" />
                                                            <span className="font-medium">
                                                                {formatDistanceToNow(new Date(sandbox.created_at))}
                                                            </span>
                                                        </div>
                                                    ) : (
                                                        <span className="text-xs text-gray-400">—</span>
                                                    )}
                                                </TableCell>
                                                <TableCell className="py-3">
                                                    <span className="text-xs text-gray-500">
                                                        {sandbox.last_active_at
                                                            ? formatDistanceToNow(new Date(sandbox.last_active_at), { addSuffix: true })
                                                            : '—'}
                                                    </span>
                                                </TableCell>
                                                <TableCell className="py-3">
                                                    <div className="flex justify-end gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                                                        {sandbox.status === 'running' ? (
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <Button
                                                                        variant="ghost"
                                                                        size="icon"
                                                                        className="h-7 w-7 rounded-md text-amber-600 hover:text-amber-700 hover:bg-amber-50"
                                                                        onClick={() => setConfirmDialog({ type: 'stop', sandboxId: sandbox.id, open: true })}
                                                                        disabled={actionLoading === sandbox.id}
                                                                    >
                                                                        <StopCircle className="h-3.5 w-3.5" />
                                                                    </Button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    {t('settings.sandboxes.stop')}
                                                                </TooltipContent>
                                                            </Tooltip>
                                                        ) : (
                                                            <Tooltip>
                                                                <TooltipTrigger asChild>
                                                                    <Button
                                                                        variant="ghost"
                                                                        size="icon"
                                                                        className="h-7 w-7 rounded-md text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50"
                                                                        onClick={() => setConfirmDialog({ type: 'restart', sandboxId: sandbox.id, open: true })}
                                                                        disabled={actionLoading === sandbox.id}
                                                                    >
                                                                        <PlayCircle className="h-3.5 w-3.5" />
                                                                    </Button>
                                                                </TooltipTrigger>
                                                                <TooltipContent side="top" className="text-xs">
                                                                    {t('settings.sandboxes.restart')}
                                                                </TooltipContent>
                                                            </Tooltip>
                                                        )}
                                                        <Tooltip>
                                                            <TooltipTrigger asChild>
                                                                <Button
                                                                    variant="ghost"
                                                                    size="icon"
                                                                    className="h-7 w-7 rounded-md text-blue-600 hover:text-blue-700 hover:bg-blue-50"
                                                                    onClick={() => setConfirmDialog({ type: 'rebuild', sandboxId: sandbox.id, open: true })}
                                                                    disabled={actionLoading === sandbox.id}
                                                                >
                                                                    <RotateCcw className="h-3.5 w-3.5" />
                                                                </Button>
                                                            </TooltipTrigger>
                                                            <TooltipContent side="top" className="text-xs">
                                                                {t('settings.sandboxes.rebuild')}
                                                            </TooltipContent>
                                                        </Tooltip>
                                                        <Tooltip>
                                                            <TooltipTrigger asChild>
                                                                <Button
                                                                    variant="ghost"
                                                                    size="icon"
                                                                    className="h-7 w-7 rounded-md text-red-600 hover:text-red-700 hover:bg-red-50"
                                                                    onClick={() => setConfirmDialog({ type: 'delete', sandboxId: sandbox.id, open: true })}
                                                                    disabled={actionLoading === sandbox.id}
                                                                >
                                                                    <Trash2 className="h-3.5 w-3.5" />
                                                                </Button>
                                                            </TooltipTrigger>
                                                            <TooltipContent side="top" className="text-xs">
                                                                {t('settings.sandboxes.delete')}
                                                            </TooltipContent>
                                                        </Tooltip>
                                                    </div>
                                                </TableCell>
                                            </TableRow>
                                        );
                                    })
                                )}
                            </TableBody>
                        </Table>
                    </div>
                </div>

                {/* Confirm Dialog */}
                <AlertDialog open={confirmDialog.open} onOpenChange={(open) => setConfirmDialog(prev => ({ ...prev, open }))}>
                    <AlertDialogContent className="rounded-xl border-0 shadow-xl">
                        <AlertDialogHeader>
                            <AlertDialogTitle className="text-lg font-semibold">
                                {confirmDialog.type === 'stop' && t('settings.sandboxes.stop')}
                                {confirmDialog.type === 'restart' && t('settings.sandboxes.restart')}
                                {confirmDialog.type === 'rebuild' && t('settings.sandboxes.rebuild')}
                                {confirmDialog.type === 'delete' && t('settings.sandboxes.delete')}
                            </AlertDialogTitle>
                            <AlertDialogDescription className="text-sm text-gray-500">
                                {confirmDialog.type === 'stop' && t('settings.sandboxes.stopConfirm')}
                                {confirmDialog.type === 'restart' && t('settings.sandboxes.restartConfirm')}
                                {confirmDialog.type === 'rebuild' && t('settings.sandboxes.rebuildConfirm')}
                                {confirmDialog.type === 'delete' && t('settings.sandboxes.deleteConfirm')}
                            </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                            <AlertDialogCancel className="rounded-lg">{t('common.cancel', 'Cancel')}</AlertDialogCancel>
                            <AlertDialogAction
                                onClick={handleAction}
                                className={cn(
                                    "rounded-lg text-white",
                                    confirmDialog.type === 'delete'
                                        ? "bg-red-600 hover:bg-red-700"
                                        : "bg-violet-600 hover:bg-violet-700"
                                )}
                            >
                                {actionLoading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                                {t('common.confirm', 'Confirm')}
                            </AlertDialogAction>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                </AlertDialog>
            </div>
        </TooltipProvider>
    );
};
