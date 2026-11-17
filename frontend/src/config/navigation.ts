import type { Component } from 'vue'
import {
  Calendar,
  ChatDotRound,
  DataAnalysis,
  Document,
  Files,
  HomeFilled,
  List,
  Search,
  Setting,
  Tickets,
  TrendCharts,
  User,
  Van,
} from '@element-plus/icons-vue'
import type { AuthUser } from '../api/client'

export type Role = AuthUser['role']

export interface NavItem {
  label: string
  to: string
  icon: Component
  /** 是否进入移动端底栏（最多 4 个，其余进「更多」） */
  mobile?: boolean
}

export const NAV_BY_ROLE: Record<Role, NavItem[]> = {
  owner: [
    { label: '首页', to: '/', icon: HomeFilled, mobile: true },
    { label: 'AI 诊断', to: '/chat', icon: ChatDotRound, mobile: true },
    { label: '我的车辆', to: '/my-vehicles', icon: Van, mobile: true },
    { label: '我的预约', to: '/appointments', icon: Calendar, mobile: true },
    { label: '设置', to: '/settings', icon: Setting },
  ],
  staff: [
    { label: '首页', to: '/', icon: HomeFilled, mobile: true },
    { label: '诊断台', to: '/chat', icon: ChatDotRound, mobile: true },
    { label: '预约工单', to: '/staff/appointments', icon: Tickets, mobile: true },
    { label: '车辆档案', to: '/staff/vehicles', icon: Van, mobile: true },
    { label: '故障码速查', to: '/staff/dtc', icon: Search },
    { label: '案例库', to: '/cases', icon: Document },
    { label: '设置', to: '/settings', icon: Setting },
  ],
  admin: [
    { label: '首页', to: '/', icon: HomeFilled, mobile: true },
    { label: '诊断质控', to: '/admin/diagnosis', icon: DataAnalysis, mobile: true },
    { label: '统计看板', to: '/admin/stats', icon: TrendCharts, mobile: true },
    { label: '知识库', to: '/admin/kb', icon: Files, mobile: true },
    { label: '成员管理', to: '/admin/users', icon: User },
    { label: '审计日志', to: '/admin/audit', icon: List },
    { label: '诊断台', to: '/chat', icon: ChatDotRound },
    { label: '设置', to: '/settings', icon: Setting },
  ],
  superadmin: [
    { label: '首页', to: '/', icon: HomeFilled, mobile: true },
    { label: '系统配置', to: '/superadmin', icon: Setting, mobile: true },
    { label: '诊断台', to: '/chat', icon: ChatDotRound, mobile: true },
  ],
}

export const ROLE_HOME_LABEL: Record<Role, string> = {
  owner: '车主工作台',
  staff: '服务顾问工作台',
  admin: '运营管理工作台',
  superadmin: '系统配置台',
}

const PATH_TITLES: Record<string, string> = {
  '/login': '登录',
  '/': '首页',
  '/chat': 'AI 智能诊断',
  '/my-vehicles': '我的车辆',
  '/appointments': '我的预约',
  '/settings': '设置',
  '/staff/appointments': '预约工单',
  '/staff/vehicles': '车辆档案检索',
  '/staff/dtc': '故障码速查',
  '/cases': '案例库',
  '/admin/kb': '知识库管理',
  '/admin/users': '成员与角色',
  '/admin/stats': '统计看板',
  '/admin/audit': '审计日志',
  '/admin/diagnosis': '诊断质控',
  '/superadmin': '系统参数配置',
}

export function titleForPath(path: string): string {
  if (path.startsWith('/report/appointment/')) return '诊断报告'
  return PATH_TITLES[path] ?? '新能源汽车 AI 诊断'
}
