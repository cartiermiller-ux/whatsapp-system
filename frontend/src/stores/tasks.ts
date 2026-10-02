import { defineStore } from 'pinia'
import { ref } from 'vue'
import { massSendApi } from '@/api'
import type { MassSendProgress } from '@/types/api'

export interface LocalTask {
  task_id: number
  task_name: string
  message_content: string
  link_url: string
  target_count: number
  account_count: number
  status: string
  sent: number
  delivered: number
  read: number
  created_at: string
}

const LS_TASKS = 'wa_tasks'

/**
 * 群发任务本地登记表。
 * 后端只提供「按 id 查询单个任务」接口，没有任务列表接口，
 * 因此前端在本地记录用户本次提交过的任务，再逐个轮询真实进度。
 */
export const useTaskStore = defineStore('tasks', () => {
  const tasks = ref<LocalTask[]>(JSON.parse(localStorage.getItem(LS_TASKS) || '[]'))

  function persist() {
    localStorage.setItem(LS_TASKS, JSON.stringify(tasks.value))
  }

  function addTask(task: LocalTask) {
    tasks.value.unshift(task)
    persist()
  }

  function removeTask(taskId: number) {
    tasks.value = tasks.value.filter((t) => t.task_id !== taskId)
    persist()
  }

  function findByTaskId(taskId: number) {
    return tasks.value.find((t) => t.task_id === taskId)
  }

  /** 拉取真实进度并回填本地登记表 */
  async function refresh(taskId: number): Promise<MassSendProgress | null> {
    const progress = await massSendApi.detail(taskId)
    const task = findByTaskId(taskId)
    if (task) {
      task.status = progress.status
      task.sent = progress.sent
      task.delivered = progress.delivered
      task.read = progress.read
      persist()
    }
    return progress
  }

  return { tasks, addTask, removeTask, findByTaskId, refresh, persist }
})
