import { request } from './request'
export interface ResourceCollection { id: number; name: string; count: number; online: number; created_at: string }
export interface AccountAudit { id: number; action: string; target: string; result: string; detail: string; username: string; created_at: string }
export interface Inspection { id: number; name: string; total: number; valid: number; invalid: number; status: string; created_at: string; results: { account_id: number; session_valid: boolean; status: string; reason: string }[] }
export interface ExportRecord { id: number; filename: string; account_ids: string; created_at: string; status: string }
export const workspaceApi = {
  groups: (kind: 'account' | 'proxy') => request<ResourceCollection[]>({ url: '/workspace/groups', params: { kind } }),
  saveGroup: (kind: string, name: string, id?: number) => request({ url: '/workspace/groups' + (id ? `/${id}` : ''), method: id ? 'put' : 'post', data: { kind, name } }),
  deleteGroup: (id: number) => request({ url: `/workspace/groups/${id}`, method: 'delete' }),
  assignGroup: (kind: string, ids: number[], group_id: number | null) => request({ url: '/workspace/group-members', method: 'post', data: { kind, ids, group_id } }),
  logs: (page: number, keyword: string) => request<{ total: number; list: AccountAudit[] }>({ url: '/workspace/account-logs', params: { page, size: 20, keyword } }),
  imports: (archive: string, group_id: number | null, account_type: string) => request<{ imported: number; ids: number[] }>({ url: '/workspace/session-import', method: 'post', data: { archive, group_id, account_type }, timeout: 120000 }),
  inspections: () => request<Inspection[]>({ url: '/workspace/inspections' }),
  inspect: (name: string, ids: number[]) => request<Inspection>({ url: '/workspace/inspections', method: 'post', data: { name, ids }, timeout: 120000 }),
  exports: () => request<ExportRecord[]>({ url: '/workspace/exports' }),
  download: (id: number) => request<Blob>({ url: `/workspace/exports/${id}/download`, responseType: 'blob', timeout: 120000 }),
}
