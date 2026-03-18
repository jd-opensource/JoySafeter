'use client'

import {
    Settings,
    User,
    Brain,
    Box
} from 'lucide-react';
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

import { useSession } from '@/lib/auth/auth-client';

import { ModelsPage } from './models-page';
import { ProfilePage } from './profile-page';
import { SandboxesPage } from './sandboxes-page';

interface SettingsDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

const MenuItem = ({
    icon: Icon,
    label,
    isActive,
    onClick
}: {
    icon: any,
    label: string,
    isActive: boolean,
    onClick: () => void
}) => (
    <button
        onClick={onClick}
        className={cn(
            "w-full flex items-center gap-3 rounded-2xl px-3 py-3 text-sm font-medium transition-all duration-200",
            isActive
                ? "border border-[var(--border)] bg-white text-[var(--text-primary)] shadow-[0_10px_24px_rgba(15,23,42,0.05)]"
                : "text-[var(--text-secondary)] hover:bg-white/70 hover:text-[var(--text-primary)]"
        )}
    >
        <Icon size={16} className={cn(isActive ? "text-[var(--brand-500)]" : "text-[var(--text-muted)]")} />
        {label}
    </button>
);

export const SettingsDialog: React.FC<SettingsDialogProps> = ({ open, onOpenChange }) => {
    const { t } = useTranslation();
    const { data: session } = useSession();
    const user = session?.user;
    const [activeTab, setActiveTab] = useState('profile');

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="flex h-[720px] max-w-5xl flex-row gap-0 overflow-hidden border border-[var(--border)] bg-[var(--surface-elevated)] p-0 shadow-[0_28px_80px_rgba(15,23,42,0.16)]">
                <DialogTitle className="sr-only">{t('settings.title')}</DialogTitle>
                <DialogDescription className="sr-only">
                    {t('settings.description')}
                </DialogDescription>

                {/* Sidebar Navigation */}
                <div className="flex w-64 flex-shrink-0 flex-col border-r border-[var(--divider)] bg-[linear-gradient(180deg,rgba(255,255,255,0.54),rgba(255,255,255,0.18))] p-5">
                    <div className="mb-6 space-y-3 px-2">
                        <div className="executive-kicker">Control Room</div>
                        <h2 className="text-xl font-semibold tracking-[-0.04em] text-[var(--text-primary)]">{t('settings.title')}</h2>
                        <p className="text-xs leading-5 text-[var(--text-secondary)]">
                            Account, model, and sandbox governance presented in one restrained workspace.
                        </p>
                    </div>

                    <div className="space-y-1 flex-1">
                        <div className="px-3 mb-2 mt-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-muted)]">{t('settings.account')}</div>
                        <MenuItem icon={User} label={t('settings.profile')} isActive={activeTab === 'profile'} onClick={() => setActiveTab('profile')} />

                        <div className="px-3 mb-2 mt-6 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-muted)]">{t('settings.workspace')}</div>
                        <MenuItem icon={Brain} label={t('settings.models')} isActive={activeTab === 'models'} onClick={() => setActiveTab('models')} />

                        <MenuItem icon={Box} label={t('settings.sandboxes.title')} isActive={activeTab === 'sandboxes'} onClick={() => setActiveTab('sandboxes')} />
                    </div>
                </div>

                {/* Main Content Area */}
                <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-transparent">
                    {activeTab === 'models' && (
                        <div className="flex-1 overflow-hidden p-6">
                            <ModelsPage />
                        </div>
                    )}
                    {activeTab === 'profile' && <ProfilePage />}
                    {activeTab === 'sandboxes' && (
                        <div className="flex-1 overflow-hidden p-6">
                            <SandboxesPage />
                        </div>
                    )}
                </div>

            </DialogContent>
        </Dialog>
    );
};
