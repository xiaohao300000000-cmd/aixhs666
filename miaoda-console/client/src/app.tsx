import React from 'react';
import { Route, Routes } from 'react-router-dom';
import { BriefcaseBusiness, HeartPulse } from 'lucide-react';

import Layout from './components/Layout';
import ComingSoonPage from './pages/ComingSoonPage';
import NotFound from './pages/NotFound/NotFound';
import LeadReviewPage from './pages/LeadReviewPage';
import CustomersPage from './pages/CustomersPage';
import CustomerDetailPage from './pages/CustomerDetailPage';
import TaskCenterPage from './pages/TaskCenterPage';
import TodayWorkbenchPage from './pages/TodayWorkbenchPage';

const RoutesComponent = () => {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<TodayWorkbenchPage />} />
        <Route path="leads" element={<LeadReviewPage />} />
        <Route path="tasks" element={<TaskCenterPage />} />
        <Route path="customers" element={<CustomersPage />} />
        <Route path="customers/:id" element={<CustomerDetailPage />} />
        <Route path="campaigns" element={<ComingSoonPage title="Campaign 中心" description="后续用于管理行业模板、客户配置、Campaign 覆盖、样本测试和版本发布。" icon={BriefcaseBusiness} />} />
        <Route path="health" element={<ComingSoonPage title="系统健康" description="后续汇总 API、Worker、数据库、飞书同步和稳定公网入口的运行状态。" icon={HeartPulse} />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
};

export default RoutesComponent;
