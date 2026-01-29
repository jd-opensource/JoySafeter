'use client'

import { 
    Settings, 
    User, 
    Brain
} from 'lucide-react';
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

import { ModelsPage } from './models-page';
import { ProfilePage } from './profile-page';

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
            "w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200",
            isActive 
                ? "bg-white text-gray-900 shadow-sm ring-1 ring-gray-200" 
                : "text-gray-500 hover:bg-gray-100 hover:text-gray-900"
        )}
    >
        <Icon size={16} className={cn(isActive ? "text-blue-600" : "text-gray-400")} />
        {label}
    </button>
);

export const SettingsDialog: React.FC<SettingsDialogProps> = ({ open, onOpenChange }) => {
    const { t } = useTranslation();
    const [activeTab, setActiveTab] = useState('profile');

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-5xl h-[700px] p-0 gap-0 overflow-hidden bg-white border-0 shadow-2xl flex flex-row">
                <DialogTitle className="sr-only">{t('settings.title')}</DialogTitle>
                <DialogDescription className="sr-only">
                    {t('settings.description')}
                </DialogDescription>
                
                {/* Sidebar Navigation */}
                <div className="w-60 bg-gray-50/80 backdrop-blur-sm border-r border-gray-200 flex flex-col p-4 flex-shrink-0">
                    <div className="mb-6 px-2">
                        <h2 className="text-lg font-bold text-gray-900 tracking-tight">{t('settings.title')}</h2>
                    </div>
                    
                    <div className="space-y-1 flex-1">
                        <div className="px-3 mb-2 mt-4 text-[10px] font-bold text-gray-400 uppercase tracking-wider">{t('settings.account')}</div>
                        <MenuItem icon={User} label={t('settings.profile')} isActive={activeTab === 'profile'} onClick={() => setActiveTab('profile')} />
                        
                        <div className="px-3 mb-2 mt-6 text-[10px] font-bold text-gray-400 uppercase tracking-wider">{t('settings.workspace')}</div>
                        <MenuItem icon={Brain} label={t('settings.models')} isActive={activeTab === 'models'} onClick={() => setActiveTab('models')} />
                    </div>
                </div>

                {/* Main Content Area */}
                <div className="flex-1 flex flex-col bg-white min-w-0 overflow-hidden">
                    {activeTab === 'models' && (
                        <div className="flex-1 overflow-hidden p-6">
                            <ModelsPage />
                        </div>
                    )}
                    {activeTab === 'profile' && <ProfilePage />}
                </div>

            </DialogContent>
        </Dialog>
    );
};

