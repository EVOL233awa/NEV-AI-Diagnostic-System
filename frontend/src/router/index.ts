import { createRouter, createWebHistory } from 'vue-router'
import { auth } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      name: 'home',
      component: () => import('../views/HomeView.vue'),
    },
    {
      path: '/chat',
      name: 'chat',
      component: () => import('../views/ChatView.vue'),
    },
    // 车主端（阶段 4）
    {
      path: '/my-vehicles',
      name: 'my-vehicles',
      component: () => import('../views/MyVehiclesView.vue'),
      meta: { roles: ['owner'] },
    },
    {
      path: '/appointments',
      name: 'my-appointments',
      component: () => import('../views/MyAppointmentsView.vue'),
      meta: { roles: ['owner'] },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsView.vue'),
    },
    // 店员端（阶段 4）
    {
      path: '/staff/appointments',
      name: 'staff-appointments',
      component: () => import('../views/StaffAppointmentsView.vue'),
      meta: { roles: ['staff', 'admin'] },
    },
    {
      path: '/staff/vehicles',
      name: 'staff-vehicles',
      component: () => import('../views/StaffVehicleSearchView.vue'),
      meta: { roles: ['staff', 'admin'] },
    },
    {
      path: '/cases',
      name: 'cases',
      component: () => import('../views/CasesView.vue'),
      meta: { roles: ['staff', 'admin'] },
    },
    // 管理端（阶段 4）
    {
      path: '/admin/kb',
      name: 'admin-kb',
      component: () => import('../views/KbView.vue'),
      meta: { roles: ['admin'] },
    },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: () => import('../views/AdminUsersView.vue'),
      meta: { roles: ['admin'] },
    },
    {
      path: '/admin/stats',
      name: 'admin-stats',
      component: () => import('../views/AdminStatsView.vue'),
      meta: { roles: ['admin'] },
    },
    {
      path: '/admin/audit',
      name: 'admin-audit',
      component: () => import('../views/AdminAuditView.vue'),
      meta: { roles: ['admin'] },
    },
    // 调试后台（superadmin 专属：供应商/Agent 参数在线配置）
    {
      path: '/superadmin',
      name: 'superadmin-config',
      component: () => import('../views/SuperadminView.vue'),
      meta: { roles: ['superadmin'] },
    },
    // 报告打印页（店员/管理员）
    {
      path: '/report/appointment/:id',
      name: 'appointment-report',
      component: () => import('../views/ReportView.vue'),
      meta: { roles: ['staff', 'admin'] },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  if (!to.meta.public && !auth.token) {
    return { name: 'login' }
  }
  if (to.name === 'login' && auth.token) {
    return { name: 'home' }
  }
  const roles = to.meta.roles as string[] | undefined
  if (roles && auth.user && !roles.includes(auth.user.role)) {
    return { name: 'home' }
  }
  return true
})

export { router }
