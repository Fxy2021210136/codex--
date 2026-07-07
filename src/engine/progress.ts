import type { Task, TaskStatus } from '../types.ts'

export interface BatchProgressRequest {
  taskIds: string[]
  dataDate: string
  status?: TaskStatus
  progress?: number
  setActualStart?: boolean
  setActualEnd?: boolean
}

export interface ProgressImpact {
  updatedCount: number
  completedCount: number
  overdueCount: number
  overdueCriticalCount: number
  affectedMilestones: string[]
}

const completionFloor:Partial<Record<TaskStatus,number>>={实体完成:90,自检完成:95,监理验收通过:100,移交下道工序:100,资料闭合:100}

export function applyBatchProgress(tasks:Task[],request:BatchProgressRequest):{tasks:Task[];impact:ProgressImpact}{
  const selected=new Set(request.taskIds),dataDate=request.dataDate
  const updated=tasks.map(task=>{
    if(!selected.has(task.id))return task
    const status=request.status??task.status
    let progress=request.progress===undefined?task.progress:Math.min(100,Math.max(0,Math.round(request.progress)))
    if(status==='未开始')progress=0
    if(status==='施工中'&&progress===0)progress=1
    progress=Math.max(progress,completionFloor[status]??0)
    const actualStartDate=request.setActualStart&&!task.actualStartDate?dataDate:task.actualStartDate
    const actualEndDate=request.setActualEnd?dataDate:task.actualEndDate
    if(actualEndDate)progress=100
    return{...task,status,progress,actualStartDate,actualEndDate,source:'手动修改' as const}
  })
  const overdue=updated.filter(task=>task.progress<100&&task.endDate<dataDate)
  const delayedIds=new Set(overdue.map(task=>task.id)),byId=new Map(updated.map(task=>[task.id,task])),successors=new Map<string,string[]>()
  updated.forEach(task=>task.predecessors.forEach(id=>successors.set(id,[...(successors.get(id)??[]),task.id])))
  const affected=new Set<string>(),queue=[...delayedIds]
  while(queue.length){for(const next of successors.get(queue.shift()!)??[]){if(!affected.has(next)){affected.add(next);queue.push(next)}}}
  const affectedMilestones=[...affected].map(id=>byId.get(id)).filter((task):task is Task=>Boolean(task?.isMilestone||task?.isLocked)).map(task=>task.name)
  return{tasks:updated,impact:{updatedCount:selected.size,completedCount:updated.filter(t=>selected.has(t.id)&&t.progress===100).length,overdueCount:overdue.length,overdueCriticalCount:overdue.filter(t=>t.isCritical).length,affectedMilestones:[...new Set(affectedMilestones)]}}
}
