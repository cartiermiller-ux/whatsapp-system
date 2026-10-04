// Shared menu and route policy. Server authorization remains authoritative.
export function isAdminRole(role?: string): boolean {
  return role === 'super_admin' || role === 'agent_admin'
}
export function allowedSettingsTabs(role?: string): string[] {
  if (role === 'super_admin') return ['services', 'params', 'users', 'tenants', 'perms']
  return role === 'agent_admin' ? ['users', 'perms'] : []
}
export function canVisitPath(path: string, role?: string): boolean {
  return !['/settings', '/account-assistant', '/downloads'].includes(path) || isAdminRole(role)
}
