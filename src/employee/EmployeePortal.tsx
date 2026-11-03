import React, { useState, useEffect } from 'react';
import { useStore } from '../context/StoreContext';
import { apiFetch } from '../services/api';
import { EmployeeViewType } from './types';
import { EmployeeHeader } from './components/EmployeeHeader';
import { EmployeeSidebar } from './components/EmployeeSidebar';
import { EmployeeOverviewView } from './views/EmployeeOverviewView';
import { MyTasksView } from './views/MyTasksView';
import { MyAttendanceView } from './views/MyAttendanceView';
import { MySalaryView } from './views/MySalaryView';
import { MyProjectsView } from './views/MyProjectsView';
import { MyProfileView } from './views/MyProfileView';

interface EmployeePortalProps {
  onExitPreview?: () => void;
  isOwnerPreviewing?: boolean;
}

export const EmployeePortal: React.FC<EmployeePortalProps> = ({
  onExitPreview,
  isOwnerPreviewing = false,
}) => {
  const [currentView, setCurrentView] = useState<EmployeeViewType>('overview');
  const [isOpenMobile, setIsOpenMobile] = useState(false);
  const [pendingTasksCount, setPendingTasksCount] = useState(0);

  useEffect(() => {
    const fetchPendingCount = async () => {
      try {
        const res = await apiFetch('/api/workforce/my-tasks');
        if (res.ok) {
          const tasks = await res.json();
          const count = (tasks || []).filter(
            (t: any) => t.status === 'PENDING' || t.status === 'IN_PROGRESS'
          ).length;
          setPendingTasksCount(count);
        }
      } catch (err) {
        // silent
      }
    };
    fetchPendingCount();
  }, [currentView]);

  const renderView = () => {
    switch (currentView) {
      case 'overview':
        return <EmployeeOverviewView onNavigate={(v) => setCurrentView(v)} />;
      case 'tasks':
        return <MyTasksView />;
      case 'attendance':
        return <MyAttendanceView />;
      case 'salary':
        return <MySalaryView />;
      case 'projects':
        return <MyProjectsView />;
      case 'profile':
        return <MyProfileView />;
      default:
        return <EmployeeOverviewView onNavigate={(v) => setCurrentView(v)} />;
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col antialiased text-slate-800">
      <EmployeeHeader
        onToggleMobileNav={() => setIsOpenMobile((prev) => !prev)}
        onExitPreview={onExitPreview}
        isOwnerPreviewing={isOwnerPreviewing}
      />

      <div className="flex-1 flex w-full">
        <EmployeeSidebar
          currentView={currentView}
          onSelectView={setCurrentView}
          isOpenMobile={isOpenMobile}
          onCloseMobile={() => setIsOpenMobile(false)}
          pendingTasksCount={pendingTasksCount}
        />

        <main className="flex-1 min-w-0 pb-12 overflow-y-auto">
          {renderView()}
        </main>
      </div>
    </div>
  );
};
