'use client'

import { X, Info, Plus, FileJson, SquarePen, Trash2, Save, Loader2 } from 'lucide-react';
import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/components/ui/use-toast';
import { useCreateMcpServer, useUpdateMcpServer, useTestMcpServer } from '@/hooks/queries/mcp';
import type { McpServer } from '@/hooks/queries/mcp'
import { cn } from '@/lib/utils';

import { serverToEditData, DEFAULT_MCP_FORM_CONFIG, type McpServerEditData } from './mcp-dialog-utils'


interface AddMcpDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    editingServer?: McpServer | null;
}

interface HeaderItem {
    key: string;
    value: string;
}

export const AddMcpDialog: React.FC<AddMcpDialogProps> = ({ open, onOpenChange, editingServer }) => {
    const { t } = useTranslation();
    const isEditMode = !!editingServer;
    const [mode, setMode] = useState<'form' | 'json'>('form');
    const [name, setName] = useState('');
    const [transport, setTransport] = useState<'streamable-http' | 'sse' | 'stdio'>(DEFAULT_MCP_FORM_CONFIG.transport);
    const [address, setAddress] = useState('');
    const [headers, setHeaders] = useState<HeaderItem[]>([]);
    
    // Settings
    const [retryEnabled, setRetryEnabled] = useState(false);
    const [maxRetries, setMaxRetries] = useState(String(DEFAULT_MCP_FORM_CONFIG.retries));
    const [retryDelay, setRetryDelay] = useState('1000');
    const [statusEnabled, setStatusEnabled] = useState<boolean>(DEFAULT_MCP_FORM_CONFIG.enabled);

    const [jsonContent, setJsonContent] = useState('');
    const { toast } = useToast();
    const createMcpServer = useCreateMcpServer();
    const updateMcpServer = useUpdateMcpServer();
    const testMcpServer = useTestMcpServer();

    // Sync Form -> JSON when switching tabs
    useEffect(() => {
        if (mode === 'json') {
            const config = {
                name,
                transport,
                address,
                headers: headers.reduce((acc, h) => ({ ...acc, [h.key]: h.value }), {}),
                retry: retryEnabled ? { maxRetries: Number(maxRetries), delay: Number(retryDelay) } : undefined,
                enabled: statusEnabled
            };
            setJsonContent(JSON.stringify(config, null, 2));
        }
    }, [mode, name, transport, address, headers, retryEnabled, maxRetries, retryDelay, statusEnabled]);

    // Load editing server data or reset form
    useEffect(() => {
        if (open && editingServer) {
            const editData = serverToEditData(editingServer);
            setName(editData.name);
            setTransport(editData.transport as 'streamable-http' | 'sse' | 'stdio');
            setAddress(editData.url || '');
            setHeaders(
                Object.entries(editData.headers || {}).map(([key, value]) => ({
                    key,
                    value: String(value),
                }))
            );
            setStatusEnabled(editData.enabled ?? DEFAULT_MCP_FORM_CONFIG.enabled);
            if (editData.timeout) {
                setRetryEnabled(true);
                setMaxRetries(String(DEFAULT_MCP_FORM_CONFIG.retries));
                setRetryDelay(String(Math.floor((editData.timeout || DEFAULT_MCP_FORM_CONFIG.timeout) / DEFAULT_MCP_FORM_CONFIG.retries)));
            }
        } else if (!open) {
            // Reset form
            setName('');
            setTransport(DEFAULT_MCP_FORM_CONFIG.transport);
            setAddress('');
            setHeaders([]);
            setRetryEnabled(false);
            setMaxRetries(String(DEFAULT_MCP_FORM_CONFIG.retries));
            setRetryDelay('1000');
            setStatusEnabled(DEFAULT_MCP_FORM_CONFIG.enabled);
            setJsonContent('');
        }
    }, [open, editingServer]);

    const handleHeaderAdd = () => {
        setHeaders([...headers, { key: '', value: '' }]);
    };

    const handleHeaderRemove = (index: number) => {
        setHeaders(headers.filter((_, i) => i !== index));
    };

    const handleHeaderChange = (index: number, field: 'key' | 'value', value: string) => {
        const newHeaders = [...headers];
        newHeaders[index] = { ...newHeaders[index], [field]: value };
        setHeaders(newHeaders);
    };

    const handleSave = async () => {
        if (!name.trim() || !address.trim()) {
            toast({
                title: t('settings.validationError'),
                description: t('settings.fillRequiredFields'),
                variant: 'destructive',
            });
            return;
        }

        try {
            // 1) Test connection first to avoid saving incorrect address/transport configuration
            // Note: backend supports both 'sse' and 'streamable-http' transport methods, do not convert
            const testResult = await testMcpServer.mutateAsync({
                transport: transport,
                url: transport !== 'stdio' ? address.trim() : undefined,
                headers: headers.reduce((acc, h) => {
                    if (h.key.trim() && h.value.trim()) {
                        acc[h.key.trim()] = h.value.trim();
                    }
                    return acc;
                }, {} as Record<string, string>),
                timeout: retryEnabled ? Number(retryDelay) * Number(maxRetries) : 30000,
            });

            if (!testResult.success) {
                toast({
                    title: t('settings.connectionFailed'),
                    description: testResult.error || t('settings.connectionFailedDescription'),
                    variant: 'destructive',
                });
                return;
            }

            // 2) Save configuration after test passes
            // Map form data to API format
            const config = {
                name: name.trim(),
                transport: transport,
                url: transport !== 'stdio' ? address.trim() : undefined,
                headers: headers.reduce((acc, h) => {
                    if (h.key.trim() && h.value.trim()) {
                        acc[h.key.trim()] = h.value.trim();
                    }
                    return acc;
                }, {} as Record<string, string>),
                timeout: retryEnabled ? Number(retryDelay) * Number(maxRetries) : 30000,
                enabled: statusEnabled,
            };

            if (isEditMode && editingServer) {
                await updateMcpServer.mutateAsync({
                    serverId: editingServer.id,
                    updates: config,
                });
                toast({
                    title: t('settings.success'),
                    description: t('settings.serverUpdated', { name }),
                });
            } else {
                await createMcpServer.mutateAsync({ config });
                toast({
                    title: t('settings.success'),
                    description: t('settings.serverCreated', { name }),
                });
            }

            onOpenChange(false);
        } catch (error) {
            toast({
                title: t('settings.error'),
                description: error instanceof Error ? error.message : t('settings.failedToCreate'),
                variant: 'destructive',
            });
        }
    };

    const isSaving = createMcpServer.isPending || updateMcpServer.isPending;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-xl p-0 gap-0 overflow-hidden bg-[#F9F9FA] shadow-2xl border-0 sm:rounded-2xl" hideCloseButton>
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 bg-white border-b border-gray-100">
                    <DialogTitle className="text-base font-bold text-gray-900">
                        {isEditMode ? t('settings.editMcpServer') : t('settings.addMcpServer')}
                    </DialogTitle>
                    <DialogDescription className="sr-only">
                        {isEditMode 
                            ? t('settings.editMcpServerDescription')
                            : t('settings.addMcpServerDescription')}
                    </DialogDescription>
                    <button 
                        onClick={() => onOpenChange(false)} 
                        className="text-gray-400 hover:text-gray-600 hover:bg-gray-100 p-1 rounded-full transition-colors"
                    >
                        <X size={18} />
                    </button>
                </div>

                {/* Tabs */}
                <div className="flex px-6 border-b border-gray-100 bg-white">
                    <button 
                        onClick={() => setMode('form')}
                        className={cn(
                            "flex items-center gap-2 px-4 py-3 text-xs font-semibold border-b-2 transition-colors focus:outline-none",
                            mode === 'form' ? "border-emerald-500 text-emerald-600" : "border-transparent text-gray-500 hover:text-gray-700"
                        )}
                    >
                        <SquarePen size={14} /> {t('settings.formMode')}
                    </button>
                    <button 
                        onClick={() => setMode('json')}
                        className={cn(
                            "flex items-center gap-2 px-4 py-3 text-xs font-semibold border-b-2 transition-colors focus:outline-none",
                            mode === 'json' ? "border-emerald-500 text-emerald-600" : "border-transparent text-gray-500 hover:text-gray-700"
                        )}
                    >
                        <FileJson size={14} /> {t('settings.jsonMode')}
                    </button>
                </div>

                {/* Content */}
                <div className="p-6 space-y-6 max-h-[60vh] overflow-y-auto custom-scrollbar bg-[#F9F9FA]">
                    {mode === 'form' ? (
                        <>
                            {/* Basic Info */}
                            <div className="space-y-4">
                                <div className="space-y-1.5">
                                    <Label className="text-xs font-semibold text-gray-700 flex items-center gap-1">
                                        <span className="text-red-500">*</span> {t('settings.name')}
                                    </Label>
                                    <Input 
                                        value={name}
                                        onChange={(e) => setName(e.target.value)}
                                        placeholder={t('settings.namePlaceholder')} 
                                        className="h-10 bg-white border-gray-200 text-sm focus-visible:ring-emerald-500/20 focus-visible:border-emerald-500" 
                                    />
                                </div>

                                <div className="space-y-1.5">
                                    <Label className="text-xs font-semibold text-gray-700 flex items-center gap-1">
                                        <span className="text-red-500">*</span> {t('settings.type')} <Info size={12} className="text-gray-400" />
                                    </Label>
                                    <Select value={transport} onValueChange={(v) => setTransport(v as typeof transport)}>
                                        <SelectTrigger className="h-10 bg-white border-gray-200 text-sm focus:ring-emerald-500/20 focus:border-emerald-500">
                                            <SelectValue placeholder={t('settings.selectType')} />
                                        </SelectTrigger>
                                        <SelectContent position="popper" className="z-[10000001]">
                                            <SelectItem value="streamable-http">{t('settings.streamableHttp')}</SelectItem>
                                            <SelectItem value="sse">{t('settings.sse')}</SelectItem>
                                            <SelectItem value="stdio">{t('settings.stdio')}</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>

                                <div className="space-y-1.5">
                                    <Label className="text-xs font-semibold text-gray-700 flex items-center gap-1">
                                        <span className="text-red-500">*</span> {t('settings.addressCommand')}
                                    </Label>
                                    <Input 
                                        value={address}
                                        onChange={(e) => setAddress(e.target.value)}
                                        placeholder={t('settings.addressCommandPlaceholder')} 
                                        className="h-10 bg-white border-gray-200 text-sm focus-visible:ring-emerald-500/20 focus-visible:border-emerald-500 font-mono text-xs" 
                                    />
                                </div>
                            </div>

                            {/* Request Headers */}
                            <div className="space-y-2">
                                <Label className="text-xs font-semibold text-gray-700">{t('settings.requestHeaders')}</Label>
                                <div className="space-y-2">
                                    {headers.map((header, idx) => (
                                        <div key={idx} className="flex gap-2 items-center animate-in fade-in slide-in-from-left-2 duration-200">
                                            <Input 
                                                placeholder={t('settings.headerKey')} 
                                                className="h-9 flex-1 bg-white text-xs font-mono"
                                                value={header.key}
                                                onChange={(e) => handleHeaderChange(idx, 'key', e.target.value)}
                                            />
                                            <span className="text-gray-300">:</span>
                                            <Input 
                                                placeholder={t('settings.headerValue')} 
                                                className="h-9 flex-1 bg-white text-xs font-mono"
                                                value={header.value}
                                                onChange={(e) => handleHeaderChange(idx, 'value', e.target.value)}
                                            />
                                            <Button 
                                                variant="ghost" 
                                                size="icon" 
                                                className="h-9 w-9 text-gray-400 hover:text-red-500 hover:bg-red-50"
                                                onClick={() => handleHeaderRemove(idx)}
                                            >
                                                <Trash2 size={14} />
                                            </Button>
                                        </div>
                                    ))}
                                    <Button 
                                        variant="outline" 
                                        onClick={handleHeaderAdd}
                                        className="w-full h-9 border-dashed border-gray-300 text-gray-500 hover:text-emerald-600 hover:border-emerald-300 hover:bg-emerald-50/50 gap-2 text-xs"
                                    >
                                        <Plus size={14} /> {t('settings.addHeader')}
                                    </Button>
                                </div>
                            </div>

                            {/* Retry Settings */}
                            <div className="p-4 bg-white rounded-xl border border-gray-100 space-y-4 shadow-sm">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <Label className="text-sm font-medium text-gray-900 cursor-pointer" onClick={() => setRetryEnabled(!retryEnabled)}>{t('settings.retryPolicy')}</Label>
                                        <Info size={12} className="text-gray-400" />
                                    </div>
                                    <Switch checked={retryEnabled} onCheckedChange={setRetryEnabled} />
                                </div>
                                
                                {retryEnabled && (
                                    <div className="grid grid-cols-2 gap-4 animate-in slide-in-from-top-1 fade-in duration-200 pt-2 border-t border-gray-50">
                                        <div className="space-y-1.5">
                                            <Label className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">{t('settings.maxRetries')}</Label>
                                            <Input 
                                                type="number" 
                                                value={maxRetries}
                                                onChange={(e) => setMaxRetries(e.target.value)}
                                                className="h-8 bg-gray-50 border-gray-200 text-xs" 
                                            />
                                        </div>
                                        <div className="space-y-1.5">
                                            <Label className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">{t('settings.delayMs')}</Label>
                                            <Input 
                                                type="number"
                                                value={retryDelay}
                                                onChange={(e) => setRetryDelay(e.target.value)} 
                                                className="h-8 bg-gray-50 border-gray-200 text-xs" 
                                            />
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* Status */}
                            <div className="p-4 bg-white rounded-xl border border-gray-100 flex items-center justify-between shadow-sm">
                                <div className="space-y-0.5">
                                    <Label className="text-sm font-medium text-gray-900">{t('settings.activeStatus')}</Label>
                                    <p className="text-xs text-gray-400">{t('settings.activeStatusDescription')}</p>
                                </div>
                                <Switch checked={statusEnabled} onCheckedChange={setStatusEnabled} />
                            </div>
                        </>
                    ) : (
                        <div className="h-full flex flex-col space-y-2">
                            <Label className="text-xs font-semibold text-gray-700">{t('settings.configurationJson')}</Label>
                            <Textarea 
                                value={jsonContent}
                                onChange={(e) => setJsonContent(e.target.value)}
                                className="flex-1 min-h-[300px] font-mono text-xs bg-white border-gray-200 resize-none p-4 leading-relaxed"
                                placeholder={t('settings.jsonPlaceholder')}
                                spellCheck={false}
                            />
                            <p className="text-[10px] text-gray-400">
                                {t('settings.jsonHint')}
                            </p>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="p-6 bg-white border-t border-gray-100 flex items-center justify-end gap-3">
                    <Button 
                        variant="ghost" 
                        onClick={() => onOpenChange(false)} 
                        className="text-gray-500 hover:text-gray-900"
                        disabled={isSaving}
                    >
                        {t('settings.cancel')}
                    </Button>
                    <Button 
                        onClick={handleSave}
                        className="bg-emerald-600 hover:bg-emerald-700 text-white shadow-emerald-200 shadow-lg px-6 gap-2"
                        disabled={isSaving || (!name && mode === 'form')}
                    >
                        {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                        {isSaving ? t('settings.saving') : isEditMode ? t('settings.updateServer') : t('settings.createServer')}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
};

