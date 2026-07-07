import test from 'node:test'
import assert from 'node:assert/strict'
import { analyzeResourceLoad, generateSchedule, instantiateTemplateForInsertion, levelResourceConflicts, recalculateTasks } from '../src/engine/schedule.ts'
import { BASE_TEMPLATES, DEFAULT_PROJECT } from '../src/data/templates.ts'
import { defaultDimensions, PROJECT_TYPES, templatesForProject } from '../src/data/projectTemplates.ts'
import type { ProjectData, ProjectType, RelationType, Task, TaskDependency, TaskTemplate } from '../src/types.ts'

const project:ProjectData={...DEFAULT_PROJECT,startDate:'2026-07-01',calendar:{weekendWork:true,holidayWork:true,shutdownPeriods:[],weatherSensitivePeriods:[]}}
const task=(id:string,duration:number,predecessors:string[]=[],relationType:RelationType='FS',lag=0):Task=>({
  id,name:id,phase:'测试',discipline:'测试',duration,predecessors,relationType,lag,wbsCode:id,
  compressibility:'部分可压缩',responsibleParty:'测试',startDate:project.startDate,endDate:project.startDate,
  status:'未开始',progress:0,isCritical:false,totalFloat:0,source:'规则生成',startConditions:[],generationBasis:'测试',
})

test('FS 关系按前置完成后开始',()=>{
  const result=recalculateTasks(project,[task('A',3),task('B',2,['A'])])
  assert.equal(result[0].startDate,'2026-07-01')
  assert.equal(result[0].endDate,'2026-07-03')
  assert.equal(result[1].startDate,'2026-07-04')
  assert.equal(result[1].endDate,'2026-07-05')
})

test('SS、FF、SF 与 Lag 正确计算',()=>{
  const ss=recalculateTasks(project,[task('A',5),task('B',2,['A'],'SS',1)])
  assert.equal(ss[1].startDate,'2026-07-02')
  const ff=recalculateTasks(project,[task('A',5),task('B',2,['A'],'FF',0)])
  assert.equal(ff[1].startDate,'2026-07-04')
  assert.equal(ff[1].endDate,'2026-07-05')
  const sf=recalculateTasks(project,[task('A',5),task('B',2,['A'],'SF',5)])
  assert.equal(sf[1].startDate,'2026-07-04')
})

test('同一任务的每条依赖可独立使用关系类型和 Lag',()=>{
  const dependencies:TaskDependency[]=[
    {predecessorId:'A',relationType:'SS',lag:1},
    {predecessorId:'B',relationType:'FF',lag:0},
  ]
  const result=recalculateTasks(project,[task('A',10),task('B',5),{...task('C',2,['A','B']),dependencies}])
  const c=result.find(item=>item.id==='C')!
  assert.equal(c.startDate,'2026-07-04')
  assert.deepEqual(c.dependencies,dependencies)
  assert.deepEqual(c.predecessors,['A','B'])
})

test('逆排计算总时差和关键路径',()=>{
  const result=recalculateTasks(project,[task('A',3),task('B',2,['A']),task('C',2)])
  assert.equal(result.find(t=>t.id==='A')?.totalFloat,0)
  assert.equal(result.find(t=>t.id==='B')?.isCritical,true)
  assert.equal(result.find(t=>t.id==='C')?.totalFloat,3)
  assert.equal(result.find(t=>t.id==='C')?.isCritical,false)
})

test('循环依赖会被拒绝',()=>{
  assert.throws(()=>recalculateTasks(project,[task('A',2,['B']),task('B',2,['A'])]),/循环依赖/)
})

test('施工日历跳过周末和停工期',()=>{
  const calendarProject={...project,startDate:'2026-07-03',calendar:{weekendWork:false,holidayWork:false,shutdownPeriods:[{name:'停工',startDate:'2026-07-07',endDate:'2026-07-08'}],weatherSensitivePeriods:[]}}
  const result=recalculateTasks(calendarProject,[task('A',4)])
  assert.equal(result[0].startDate,'2026-07-03')
  assert.equal(result[0].endDate,'2026-07-10')
})

test('资源负荷识别并行超载',()=>{
  const tasks=recalculateTasks(project,[task('A',3),task('B',3)])
  const load=analyzeResourceLoad(project,tasks).find(x=>x.resource==='测试')
  assert.equal(load?.peak,2)
  assert.equal(load?.capacity,1)
  assert.equal(load?.overloadedDays,3)
})

test('项目可覆盖默认资源容量',()=>{
  const tasks=recalculateTasks(project,[task('A',3),task('B',3)])
  const load=analyzeResourceLoad({...project,resourceCapacities:{测试:2}},tasks).find(x=>x.resource==='测试')
  assert.equal(load?.capacity,2)
  assert.equal(load?.overloadedDays,0)
})

test('自动错峰会顺延任务并消除可处理的冲突',()=>{
  const tasks=recalculateTasks(project,[task('A',3),task('B',3)])
  const result=levelResourceConflicts(project,tasks)
  assert.equal(result.beforeConflicts,1)
  assert.equal(result.afterConflicts,0)
  assert.equal(result.shifted.reduce((n,x)=>n+x.days,0),3)
  assert.equal(analyzeResourceLoad(project,result.tasks).find(x=>x.resource==='测试')?.overloadedDays,0)
})

test('工序计划按楼栋和楼层展开并保留空间、工程量与对应依赖',()=>{
  const detailed=generateSchedule({...project,buildingCount:2,floorsAboveGround:3,planLevel:'工序计划'},BASE_TEMPLATES)
  const structures=detailed.filter(t=>t.name.includes('主体结构施工')&&t.building)
  assert.equal(structures.length,6)
  const structure=structures.find(t=>t.building==='1#楼'&&t.floor==='2层')
  const masonry=detailed.find(t=>t.name.includes('砌体及二次结构')&&t.building==='1#楼'&&t.floor==='2层')
  assert.ok(structure)
  assert.ok(masonry)
  assert.ok(masonry.predecessors.includes(structure.id))
  assert.equal(masonry.workArea,'第2流水段')
  assert.ok((masonry.quantity??0)>0)
  assert.ok((masonry.materialNodes?.length??0)>0)
})

test('总控计划保持阶段级任务而不展开楼层',()=>{
  const summary=generateSchedule({...project,buildingCount:2,floorsAboveGround:3,planLevel:'总控计划'},BASE_TEMPLATES)
  assert.equal(summary.some(t=>t.building||t.floor),false)
  assert.equal(summary.filter(t=>t.name==='主体结构施工').length,1)
})

test('所有内置项目类型都能生成无循环的计划',()=>{
  for(const projectType of PROJECT_TYPES){
    const generic={...project,projectType,planLevel:'工序计划' as const,spatialDimensions:defaultDimensions(projectType,project)}
    const tasks=generateSchedule(generic,templatesForProject(generic))
    assert.ok(tasks.length>=2,projectType)
    assert.ok(tasks.at(-1)?.endDate,projectType)
    assert.equal(new Set(tasks.map(t=>t.id)).size,tasks.length,projectType)
  }
})

test('道路模板按标段与施工区段展开空间路径',()=>{
  const projectType:ProjectType='道路工程'
  const road={...project,projectType,planLevel:'工序计划' as const,spatialDimensions:defaultDimensions(projectType,project)}
  const tasks=generateSchedule(road,templatesForProject(road))
  const roadbed=tasks.filter(t=>t.name.includes('路基开挖与填筑'))
  assert.equal(roadbed.length,2)
  assert.deepEqual(roadbed[0].spacePath,{标段:'一标段',施工区段:'K0+000～K0+500'})
  assert.equal(roadbed[0].unit,'m³')
})

test('自定义模板按用户空间维度展开并进入计划',()=>{
  const projectType:ProjectType='自定义工程'
  const customProject={...project,projectType,planLevel:'工序计划' as const,spatialDimensions:[{id:'zone',name:'区域',values:['东区','西区']},{id:'face',name:'作业面',values:['A面','B面']}]}
  const custom:TaskTemplate={id:'CUSTOM-TEST',name:'专项施工',phase:'专项工程',discipline:'专业分包',duration:3,predecessorNames:['项目启动'],relationType:'FS',lag:0,compressibility:'部分可压缩',responsibleParty:'专业分包',projectType,isCustom:true,expansionDimensions:['区域','作业面'],quantityUnit:'项'}
  const tasks=generateSchedule(customProject,templatesForProject(customProject,[custom]))
  const expanded=tasks.filter(t=>t.id.startsWith('CUSTOM-TEST'))
  assert.equal(expanded.length,4)
  assert.equal(expanded.every(t=>t.spacePath?.区域&&t.spacePath?.作业面),true)
  const completion=tasks.find(t=>t.name==='项目完成')
  assert.ok(completion)
  assert.equal(expanded.filter(t=>t.spacePath?.作业面==='B面').every(t=>completion.predecessors.includes(t.id)),true)
})

test('模板插入当前计划时按空间维度批量展开并建立组内流水依赖',()=>{
  const customProject={...project,projectType:'自定义工程' as const,planLevel:'工序计划' as const,spatialDimensions:[{id:'zone',name:'区域',values:['东区','西区']},{id:'face',name:'作业面',values:['A面','B面']}]}
  const template:TaskTemplate={id:'CUSTOM-INSERT',name:'专项施工',phase:'专项工程',discipline:'专业分包',duration:3,predecessorNames:[],relationType:'SS',lag:2,compressibility:'部分可压缩',responsibleParty:'专业分包',projectType:'自定义工程',isCustom:true,expansionDimensions:['区域','作业面'],quantityUnit:'项'}
  const base=task('BASE',1)
  const inserted=instantiateTemplateForInsertion(customProject,template,base,'TEST')
  assert.equal(inserted.length,4)
  assert.equal(inserted.every(item=>item.spacePath?.区域&&item.spacePath?.作业面),true)
  const eastA=inserted.find(item=>item.spacePath?.区域==='东区'&&item.spacePath?.作业面==='A面')!
  const eastB=inserted.find(item=>item.spacePath?.区域==='东区'&&item.spacePath?.作业面==='B面')!
  assert.deepEqual(eastA.dependencies,[{predecessorId:'BASE',relationType:'SS',lag:2}])
  assert.deepEqual(eastB.dependencies,[{predecessorId:eastA.id,relationType:'FS',lag:0}])
  assert.doesNotThrow(()=>recalculateTasks(customProject,[base,...inserted]))
})
