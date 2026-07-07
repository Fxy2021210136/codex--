import test from 'node:test'
import assert from 'node:assert/strict'
import { applyBatchProgress } from '../src/engine/progress.ts'
import { reviewSchedule } from '../src/engine/schedule.ts'
import { DEFAULT_PROJECT } from '../src/data/templates.ts'
import type { Task } from '../src/types.ts'

const task=(id:string,patch:Partial<Task>={}):Task=>({
  id,name:id,phase:'测试',discipline:'测试',duration:3,predecessors:[],relationType:'FS',lag:0,wbsCode:id,
  compressibility:'部分可压缩',responsibleParty:'测试',startDate:'2026-07-01',endDate:'2026-07-03',
  status:'未开始',progress:0,isCritical:false,totalFloat:0,source:'规则生成',startConditions:[],generationBasis:'测试',...patch,
})

test('批量进度更新写入状态、完成率和实际开始日期',()=>{
  const result=applyBatchProgress([task('A'),task('B')],{taskIds:['A'],dataDate:'2026-07-02',status:'施工中',progress:35,setActualStart:true})
  assert.equal(result.tasks[0].status,'施工中')
  assert.equal(result.tasks[0].progress,35)
  assert.equal(result.tasks[0].actualStartDate,'2026-07-02')
  assert.equal(result.tasks[1].status,'未开始')
  assert.equal(result.impact.updatedCount,1)
})

test('数据日期识别逾期关键任务及受影响里程碑',()=>{
  const tasks=[task('A',{isCritical:true}),task('M',{name:'交付节点',isMilestone:true,isLocked:true,predecessors:['A'],startDate:'2026-07-10',endDate:'2026-07-10',duration:1})]
  const result=applyBatchProgress(tasks,{taskIds:['A'],dataDate:'2026-07-08',status:'施工中',progress:60,setActualStart:true})
  assert.equal(result.impact.overdueCount,1)
  assert.equal(result.impact.overdueCriticalCount,1)
  assert.deepEqual(result.impact.affectedMilestones,['交付节点'])
})

test('完成状态自动校正完成率并可写入实际完成日期',()=>{
  const result=applyBatchProgress([task('A')],{taskIds:['A'],dataDate:'2026-07-04',status:'监理验收通过',progress:80,setActualStart:true,setActualEnd:true})
  assert.equal(result.tasks[0].progress,100)
  assert.equal(result.tasks[0].actualEndDate,'2026-07-04')
  assert.equal(result.impact.completedCount,1)
})

test('计划审查纳入数据日期和未闭合开工条件',()=>{
  const project={...DEFAULT_PROJECT,dataDate:'2026-07-10'}
  const tasks=[task('A',{status:'施工中',progress:40,isCritical:true,startConditions:[{id:'C1',name:'工作面移交',type:'工作面',status:'待确认',strength:'强制依赖'}]}),task('M',{name:'竣工验收',isMilestone:true,isLocked:true,predecessors:['A']})]
  const risks=reviewSchedule(project,tasks)
  assert.ok(risks.find(r=>r.id==='data-date-overdue'))
  assert.ok(risks.find(r=>r.id==='started-with-pending'))
})
