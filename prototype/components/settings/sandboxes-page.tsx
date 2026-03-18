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
                    color: 'bg-[rgba(53,111,97,0.12)] text-[var(--status-healthy)] border-[rgba(53,111,97,0.18)]',
                    dot: 'bg-[var(--status-healthy)]',
                    animate: true
                };
            case 'creating':
                return {
                    color: 'bg-[rgba(54,93,130,0.12)] text-[var(--status-running)] border-[rgba(54,93,130,0.18)]',
                    dot: 'bg-[var(--status-running)]',
                    animate: true
                };
            case 'stopped':
                return {
                    color: 'bg-[rgba(107,93,79,0.12)] text-[var(--status-pending)] border-[rgba(107,93,79,0.18)]',
                    dot: 'bg-[var(--status-pending)]',
                    animate: false
                };
            case 'failed':
                return {
                    color: 'bg-[rgba(156,68,56,0.12)] text-[var(--status-offline)] border-[rgba(156,68,56,0.18)]',
                    dot: 'bg-[var(--status-offline)]',
                    animate: false
                };
            default:
                return {
                    color: 'bg-[rgba(107,93,79,0.12)] text-[var(--status-pending)] border-[rgba(107,93,79,0.18)]',
                    dot: 'bg-[var(--status-pending)]',
                    animate: false
                };
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center h-full min-h-[400px]">
                <Loader2 className="h-6 w-6 animate-spin text-[var(--brand-500)]" />
            </div>
        );
    }

    return (
        <TooltipProvider>
            <div className="flex h-full flex-col">
                {/* Header */}
                <div className="surface-panel mb-6 flex items-center justify-between px-6 py-5">
                    <div className="flex items-center gap-3">
                        <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-[var(--divider)] bg-[var(--surface-2)]">
                            <Box className="h-5 w-5 text-[var(--brand-500)]" />
                        </div>
                        <div>
                            <div className="section-label mb-1">Sandbox Registry</div>
                            <h2 className="text-lg font-semibold tracking-[-0.03em] text-[var(--text-primary)]">
                                {t('settings.sandboxes.title')}
                            </h2>
                            <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                                {t('settings.sandboxes.description')}
                            </p>
                        </div>
                    </div>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => { setLoading(true); fetchSandboxes(); }}
                        className="gap-2 rounded-full border-[var(--border)] bg-white/80 hover:border-[var(--border-hover)] hover:bg-white"
                    >
                        <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
                        <span className="text-xs font-medium">{t('settings.sandboxes.refresh')}</span>
                    </Button>
                </div>

                {/* Stats Bar */}
                <div className="mb-4 flex items-center gap-4 px-1">
                    <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
                        <Activity className="h-3.5 w-3.5" />
                        <span>
                            {sandboxes.filter(s => s.status === 'running').length} {t('settings.sandboxes.running', 'running')}
                        </span>
                    </div>
                    <div className="h-3 w-px bg-[var(--divider)]" />
                    <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
                        <User className="h-3.5 w-3.5" />
                        <span>{sandboxes.length} {t('settings.sandboxes.total', 'total')}</span>
                    </div>
                </div>

                {/* Table Container */}
                <div className="surface-panel flex flex-1 flex-col overflow-hidden">
                    <div className="flex-1 overflow-auto">
                        <Table>
                            <TableHeader>
                                <TableRow className="bg-[var(--surface-2)] hover:bg-[var(--surface-2)]">
                                    <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]">
                                        {t('settings.sandboxes.user')}
                                    </TableHead>
                                    <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]">
                                        {t('settings.sandboxes.status')}
                                    </TableHead>
                                    <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]">
                                        {t('settings.sandboxes.resources')}
                                    </TableHead>
                                    <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]">
                                        {t('settings.sandboxes.runtime')}
                                    </TableHead>
                                    <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]">
                                        {t('settings.sandboxes.lastActive')}
                                    </TableHead>
                                    <TableHead className="py-3 text-right text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]">
                                        {t('settings.sandboxes.actions')}
                                    </TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {sandboxes.length === 0 ? (
                                    <TableRow>
                                        <TableCell colSpan={6} className="text-center py-16">
                                            <div className="flex flex-col items-center gap-3">
                                                <div className="rounded-full border border-[var(--divider)] bg-[var(--surface-2)] p-4">
                                                    <Box className="h-8 w-8 text-[var(--text-subtle)]" />
                                                </div>
                                                <p className="text-sm font-medium text-[var(--text-secondary)]">
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
                                                className="group transition-colors hover:bg-[rgba(255,255,255,0.5)]"
                                            >
                                                <TableCell className="py-3">
                                                    <div className="flex items-center gap-3">
                                                        <div className="flex h-8 w-8 items-center justify-center rounded-full border border-[var(--divider)] bg-[var(--surface-2)]">
                                                            <User className="h-4 w-4 text-[var(--text-secondary)]" />
                                                        </div>
                                                        <div className="flex flex-col">
                                                            <span className="text-sm font-medium text-[var(--text-primary)]">
                                                                {sandbox.user?.name || sandbox.user?.email || 'Unknown'}
                                                            </span>
                                                            <span className="font-mono text-[10px] text-[var(--text-muted)]">
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
                                                        <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                                                            <Cpu className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                                                            <span className="font-medium">{sandbox.cpu_limit}</span>
                                                        </div>
                                                        <div className="h-3 w-px bg-[var(--divider)]" />
                                                        <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                                                            <MemoryStick className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                                                            <span className="font-medium">{sandbox.memory_limit}M</span>
                                                        </div>
                                                    </div>
                                                </TableCell>
                                                <TableCell className="py-3">
                                                    {sandbox.status === 'running' && sandbox.created_at ? (
                                                        <div className="flex items-center gap-1.5 text-xs text-[var(--status-healthy)]">
                                                            <Clock className="h-3.5 w-3.5" />
                                                            <span className="font-medium">
                                                                {formatDistanceToNow(new Date(sandbox.created_at))}
                                                            </span>
                                                        </div>
                                                    ) : (
                                                        <span className="text-xs text-[var(--text-muted)]">—</span>
                                                    )}
                                                </TableCell>
                                                <TableCell className="py-3">
                                                    <span className="text-xs text-[var(--text-secondary)]">
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
                                                                        className="h-7 w-7 rounded-full text-[var(--warning)] hover:bg-[rgba(155,106,45,0.08)] hover:text-[var(--warning)]"
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
                                                                        className="h-7 w-7 rounded-full text-[var(--status-healthy)] hover:bg-[rgba(53,111,97,0.08)] hover:text-[var(--status-healthy)]"
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
                                                                    className="h-7 w-7 rounded-full text-[var(--status-running)] hover:bg-[rgba(54,93,130,0.08)] hover:text-[var(--status-running)]"
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
                                                                    className="h-7 w-7 rounded-full text-[var(--status-offline)] hover:bg-[rgba(156,68,56,0.08)] hover:text-[var(--status-offline)]"
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
                    <AlertDialogContent className="rounded-[1.5rem] border border-[var(--border)] bg-[var(--surface-elevated)] shadow-[0_28px_60px_rgba(15,23,42,0.16)]">
                        <AlertDialogHeader>
                            <AlertDialogTitle className="text-lg font-semibold tracking-[-0.03em] text-[var(--text-primary)]">
                                {confirmDialog.type === 'stop' && t('settings.sandboxes.stop')}
                                {confirmDialog.type === 'restart' && t('settings.sandboxes.restart')}
                                {confirmDialog.type === 'rebuild' && t('settings.sandboxes.rebuild')}
                                {confirmDialog.type === 'delete' && t('settings.sandboxes.delete')}
                            </AlertDialogTitle>
                            <AlertDialogDescription className="text-sm leading-6 text-[var(--text-secondary)]">
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
                                    "rounded-full px-5 text-white",
                                    confirmDialog.type === 'delete'
                                        ? "bg-red-600 hover:bg-red-700"
                                        : "btn-primary hover:opacity-95"
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
