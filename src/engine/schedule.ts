import type { ProjectData, ResourceLevelingResult, ResourceLoad, ReviewItem, Task, TaskDependency, TaskTemplate } from '../types'

const day = 86400000
export const parseDate = (s:string) => new Date(`${s}T00:00:00`)
export const fmtDate = (d:Date) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
export const addDays = (s:string,n:number) => fmtDate(new Date(parseDate(s).getTime()+n*day))
export const dateDiff = (a:string,b:string) => Math.round((parseDate(b).getTime()-parseDate(a).getTime())/day)
export const isWorkingDate=(date:Date,calendar:ProjectData['calendar'])=>{
  const value=fmtDate(date)
  if(calendar?.shutdownPeriods.some(p=>value>=p.startDate&&value<=p.endDate))return false
  if(calendar&&!calendar.weekendWork&&(date.getDay()===0||date.getDay()===6))return false
  return true
}
const workDateFromOffset=(start:string,offset:number,calendar:ProjectData['calendar'])=>{
  const date=parseDate(start)
  while(!isWorkingDate(date,calendar))date.setDate(date.getDate()+1)
  let completed=0
  while(completed<offset){date.setDate(date.getDate()+1);if(isWorkingDate(date,calendar))completed++}
  return fmtDate(date)
}
export const shiftWorkingDate=(value:string,offset:number,calendar:ProjectData['calendar'])=>{
  if(offset===0)return value
  const date=parseDate(value),direction=offset>0?1:-1
  let remaining=Math.abs(offset)
  while(remaining>0){date.setDate(date.getDate()+direction);if(isWorkingDate(date,calendar))remaining--}
  return fmtDate(date)
}

export function taskDependencies(task:Pick<Task,'predecessors'|'relationType'|'lag'|'dependencies'>):TaskDependency[]{
  const source=task.dependencies??task.predecessors.map(predecessorId=>({predecessorId,relationType:task.relationType||'FS',lag:Math.round(task.lag||0)}))
  const seen=new Set<string>()
  return source.filter(edge=>edge.predecessorId&&!seen.has(edge.predecessorId)&&(seen.add(edge.predecessorId),true)).map(edge=>({
    predecessorId:edge.predecessorId,
    relationType:edge.relationType||'FS',
    lag:Math.round(edge.lag||0),
  }))
}

const applicable = (tpl:TaskTemplate,p:ProjectData) => {
  if (tpl.scope && !p[tpl.scope]) return false
  if (tpl.name==='普通装修及收口' && p.hasFineDecoration) return false
  if (tpl.name==='桩基施工' && !p.foundationType.includes('桩')) return false
  if (tpl.name==='基坑支护' && !p.hasDeepFoundationPit) return false
  return true
}

export function generateSchedule(project:ProjectData,templates:TaskTemplate[]):Task[] {
  const selected=templates.filter(x=>applicable(x,project))
  const byName=new Map(selected.map(x=>[x.name,x]))
  const instances=new Map(selected.map((tpl,index)=>[tpl.id,expandTemplate(tpl,index,project)]))
  const raw=selected.flatMap((tpl,index)=>{
    const current=instances.get(tpl.id)!
    return current.map((item):Task=>{
      const external=tpl.predecessorNames.flatMap(name=>{
        const pred=byName.get(name)
        return pred?matchPredecessors(item,instances.get(pred.id)!):[]
      })
      const previous=item.sequence!==undefined&&item.sequence>0&&tpl.name!=='机电预留预埋'
        ?current.find(x=>x.sequenceGroup===item.sequenceGroup&&x.sequence===item.sequence!-1)
        :undefined
      const predecessors=[...new Set([...external,...(previous?[previous.id]:[])])]
      const detailed=Boolean(item.spacePath)
      const relationType=detailed?(tpl.name==='机电预留预埋'?'SS':'FS'):tpl.relationType
      const lag=detailed?0:tpl.lag
      const dependencies:TaskDependency[]=predecessors.map(predecessorId=>({
        predecessorId,
        relationType:previous?.id===predecessorId?'FS':relationType,
        lag:previous?.id===predecessorId?0:lag,
      }))
      return {...tpl,id:item.id,name:item.name,wbsCode:item.wbsCode,duration:item.duration,
        predecessors,dependencies,startDate:project.startDate,endDate:project.startDate,status:'未开始',progress:0,
        relationType,lag,isCritical:false,totalFloat:0,source:'规则生成',
        generationBasis:detailed?`${tpl.isCustom?'自定义':'标准'}工序库 · 按空间维度展开 · ${project.planLevel}`:`${tpl.isCustom?'自定义':'标准'}工序库 · ${project.planLevel}`,
        building:item.building,floor:item.floor,workArea:item.workArea,quantity:item.quantity,unit:item.unit,
        spacePath:item.spacePath,resourceDemand:tpl.resourceDemand??resourceDemandFor(tpl),materialNodes:tpl.materialNodes??materialNodesFor(tpl),
        startConditions:tpl.predecessorNames.slice(0,2).map((n,i)=>({id:`${item.id}-C${i+1}`,name:`${n}完成并移交`,type:'工作面条件',status:'待确认',strength:'强制依赖'}))}
    })
  })
  return recalculateTasks(project,raw)
}

interface TemplateInstance {
  id:string
  name:string
  wbsCode:string
  duration:number
  building?:string
  floor?:string
  workArea?:string
  quantity?:number
  unit?:string
  buildingNumber?:number
  floorNumber?:number
  spacePath?:Record<string,string>
  sequence?:number
  sequenceGroup?:string
}

const FLOOR_EXPANDED_TASKS=new Set([
  '主体结构施工','砌体及二次结构','机电预留预埋','管线综合安装',
  '抹灰及基层施工','室内精装修','普通装修及收口','厨卫防水与闭水试验',
])

function expandTemplate(tpl:TaskTemplate,index:number,project:ProjectData):TemplateInstance[]{
  const base=String(index+1).padStart(2,'0')
  const duration=scaledDuration(tpl,project)
  if(project.planLevel!=='工序计划')return [{id:tpl.id,name:tpl.name,wbsCode:`${base}.00`,duration}]
  const dimensions=(project.spatialDimensions??[]).filter(d=>tpl.expansionDimensions?.includes(d.name)&&d.values.length)
  if(tpl.expansionDimensions?.length&&dimensions.length){
    const combinations=dimensions.reduce<Record<string,string>[]>((items,dimension)=>items.flatMap(item=>dimension.values.map(value=>({...item,[dimension.name]:value}))),[{}])
    const lastDimension=dimensions.at(-1)!
    return combinations.map((spacePath,position)=>{
      const sequence=lastDimension.values.indexOf(spacePath[lastDimension.name])
      const sequenceGroup=dimensions.slice(0,-1).map(d=>spacePath[d.name]).join('|')||'all'
      const label=dimensions.map(d=>spacePath[d.name]).join(' ')
      const quantity=tpl.defaultQuantity??project.grossFloorArea/Math.max(1,combinations.length)
      return{id:`${tpl.id}-S${String(position+1).padStart(4,'0')}`,name:`${label} · ${tpl.name}`,wbsCode:`${base}.${String(position+1).padStart(3,'0')}`,
        duration,spacePath,sequence,sequenceGroup,building:spacePath['楼栋'],floor:spacePath['楼层'],workArea:spacePath[lastDimension.name],
        quantity:Math.round(quantity),unit:tpl.quantityUnit??'项'}
    })
  }
  if(!FLOOR_EXPANDED_TASKS.has(tpl.name))return [{id:tpl.id,name:tpl.name,wbsCode:`${base}.00`,duration}]
  const buildings=Math.max(1,Math.round(project.buildingCount)),floors=Math.max(1,Math.round(project.floorsAboveGround))
  const floorArea=project.grossFloorArea/Math.max(1,buildings*(floors+Math.max(0,project.floorsUnderground)))
  const unitDuration=detailDuration(tpl.name,duration,floors,project.standardFloorCycleDays)
  const result:TemplateInstance[]=[]
  for(let building=1;building<=buildings;building++)for(let floor=1;floor<=floors;floor++){
    const quantity=quantityFor(tpl.name,floorArea)
    result.push({id:`${tpl.id}-B${String(building).padStart(2,'0')}-F${String(floor).padStart(3,'0')}`,
      name:`${building}#楼 ${floor}层 · ${tpl.name}`,wbsCode:`${base}.${String(building).padStart(2,'0')}.${String(floor).padStart(2,'0')}`,
      duration:unitDuration,building:`${building}#楼`,floor:`${floor}层`,
      workArea:`第${(floor-1)%Math.max(1,project.constructionSectionCount)+1}流水段`,quantity:Math.round(quantity),unit:'㎡',buildingNumber:building,floorNumber:floor,
      spacePath:{楼栋:`${building}#楼`,楼层:`${floor}层`},sequence:floor-1,sequenceGroup:`${building}#楼`})
  }
  return result
}

export function instantiateTemplateForInsertion(project:ProjectData,tpl:TaskTemplate,afterTask:Task,insertionKey:string):Task[]{
  const instances=expandTemplate(tpl,Math.max(0,Number(afterTask.wbsCode.split('.')[0])||0),project)
  const idMap=new Map(instances.map((item,index)=>[item.id,`USER-${insertionKey}-${String(index+1).padStart(4,'0')}`]))
  return instances.map((item,index)=>{
    const previous=item.sequence!==undefined&&item.sequence>0
      ?instances.find(candidate=>candidate.sequenceGroup===item.sequenceGroup&&candidate.sequence===item.sequence!-1)
      :undefined
    const predecessorId=previous?idMap.get(previous.id)!:afterTask.id
    const relationType=previous?'FS':tpl.relationType
    const lag=previous?0:tpl.lag
    return {
      ...tpl,
      id:idMap.get(item.id)!,
      name:item.name,
      wbsCode:`${afterTask.wbsCode}.I${String(index+1).padStart(3,'0')}`,
      duration:item.duration,
      predecessors:[predecessorId],
      dependencies:[{predecessorId,relationType,lag}],
      relationType,
      lag,
      startDate:afterTask.endDate,
      endDate:afterTask.endDate,
      status:'未开始',
      progress:0,
      isMilestone:false,
      isLocked:false,
      isCritical:false,
      totalFloat:0,
      source:'用户输入',
      startConditions:[{id:`USER-${insertionKey}-${index+1}-C1`,name:`${afterTask.name}完成并移交`,type:'工作面条件',status:'待确认',strength:'强制依赖'}],
      generationBasis:`${tpl.isCustom?'自定义':'标准'}模板 · 按空间批量插入`,
      building:item.building,
      floor:item.floor,
      workArea:item.workArea,
      quantity:item.quantity,
      unit:item.unit,
      spacePath:item.spacePath,
      resourceDemand:tpl.resourceDemand??resourceDemandFor(tpl),
      materialNodes:tpl.materialNodes??materialNodesFor(tpl),
    }
  })
}

function matchPredecessors(current:TemplateInstance,candidates:TemplateInstance[]){
  if(!current.spacePath){
    const detailed=candidates.some(x=>x.spacePath)
    if(!detailed)return candidates.map(x=>x.id)
    const groups=new Map<string,TemplateInstance[]>()
    candidates.forEach(item=>groups.set(item.sequenceGroup??'all',[...(groups.get(item.sequenceGroup??'all')??[]),item]))
    return [...groups.values()].map(items=>items.sort((a,b)=>(b.sequence??0)-(a.sequence??0))[0].id)
  }
  const commonMatches=candidates.filter(candidate=>candidate.spacePath&&Object.entries(candidate.spacePath).every(([key,value])=>current.spacePath?.[key]===undefined||current.spacePath[key]===value))
  if(commonMatches.length)return commonMatches.map(x=>x.id)
  const exact=candidates.find(x=>x.buildingNumber===current.buildingNumber&&x.floorNumber===current.floorNumber)
  if(exact)return [exact.id]
  if(candidates.length===1)return [candidates[0].id]
  const sameBuilding=candidates.filter(x=>x.buildingNumber===current.buildingNumber).sort((a,b)=>Math.abs((a.floorNumber??0)-current.floorNumber!)-Math.abs((b.floorNumber??0)-current.floorNumber!))[0]
  return sameBuilding?[sameBuilding.id]:candidates.map(x=>x.id)
}

function detailDuration(name:string,total:number,floors:number,cycle:number){
  if(name==='主体结构施工')return Math.max(1,Math.round(cycle))
  if(name==='机电预留预埋')return Math.max(1,Math.round(cycle*.8))
  const minimum=name.includes('防水')?2:name.includes('管线')?3:4
  return Math.max(minimum,Math.ceil(total/Math.max(1,floors)))
}

function quantityFor(name:string,floorArea:number){
  if(name.includes('砌体'))return floorArea*1.15
  if(name.includes('抹灰'))return floorArea*2.6
  if(name.includes('防水'))return floorArea*.12
  if(name.includes('管线')||name.includes('机电'))return floorArea*.9
  return floorArea
}

function resourceDemandFor(tpl:TaskTemplate){
  const group=tpl.discipline.includes('机电')?'机电安装班组':tpl.discipline.includes('装修')?'装饰装修班组':tpl.discipline.includes('防水')?'防水班组':tpl.discipline.includes('结构')?'土建结构班组':`${tpl.discipline}班组`
  return [`${group} 1组`]
}

function materialNodesFor(tpl:TaskTemplate){
  if(tpl.name.includes('主体结构'))return ['钢筋进场检验','模板体系验收','混凝土供应确认']
  if(tpl.name.includes('砌体'))return ['砌块进场复验','砂浆配合比确认']
  if(tpl.name.includes('机电')||tpl.name.includes('管线'))return ['综合管线深化确认','主要设备材料到场']
  if(tpl.name.includes('防水'))return ['防水材料复验','样板验收']
  if(tpl.name.includes('装修')||tpl.name.includes('抹灰'))return ['施工样板确认','面层材料到场']
  return tpl.riskNote?['关键材料到场确认']:[]
}

export function recalculateTasks(project:ProjectData,tasks:Task[],options:{preserveLockedDates?:boolean}={}):Task[] {
  if(!tasks.length)return []
  const ids=new Set<string>(),byId=new Map(tasks.map(t=>[t.id,t]))
  for(const task of tasks){if(ids.has(task.id))throw new Error(`存在重复任务 ID：${task.id}`);ids.add(task.id)}
  const incoming=new Map<string,TaskDependency[]>(),outgoing=new Map<string,{successorId:string;edge:TaskDependency}[]>()
  tasks.forEach(task=>{
    const valid=taskDependencies(task).filter(edge=>edge.predecessorId!==task.id&&byId.has(edge.predecessorId))
    incoming.set(task.id,valid)
    valid.forEach(edge=>outgoing.set(edge.predecessorId,[...(outgoing.get(edge.predecessorId)??[]),{successorId:task.id,edge}]))
  })
  const indegree=new Map(tasks.map(t=>[t.id,incoming.get(t.id)?.length??0])),queue=tasks.filter(t=>(indegree.get(t.id)??0)===0).map(t=>t.id),order:string[]=[]
  while(queue.length){const id=queue.shift()!;order.push(id);for(const {successorId} of outgoing.get(id)??[]){const degree=(indegree.get(successorId)??0)-1;indegree.set(successorId,degree);if(degree===0)queue.push(successorId)}}
  if(order.length!==tasks.length){const cycle=tasks.filter(t=>!order.includes(t.id)).map(t=>t.name).slice(0,5).join('、');throw new Error(`检测到循环依赖：${cycle}`)}
  const es=new Map<string,number>(),ef=new Map<string,number>()
  for(const id of order){const task=byId.get(id)!,duration=Math.max(1,Math.round(task.duration));let start=0
    for(const edge of incoming.get(id)??[]){const ps=es.get(edge.predecessorId)??0,pe=ef.get(edge.predecessorId)??0,lag=edge.lag;const candidate=edge.relationType==='SS'?ps+lag:edge.relationType==='FF'?pe+lag-duration:edge.relationType==='SF'?ps+lag-duration:pe+lag;start=Math.max(start,candidate)}
    if(options.preserveLockedDates&&task.isLocked&&task.startDate){const locked=workOffsetBetween(project.startDate,task.startDate,project.calendar);if(start>locked)throw new Error(`锁定节点「${task.name}」早于其前置任务可达日期`);start=locked}
    start=Math.max(0,start);es.set(id,start);ef.set(id,start+duration)
  }
  const projectFinish=Math.max(...ef.values()),ls=new Map<string,number>(),lf=new Map<string,number>()
  for(const id of [...order].reverse()){const task=byId.get(id)!,duration=Math.max(1,Math.round(task.duration)),edges=outgoing.get(id)??[];let latestStart=projectFinish-duration
    if(edges.length)latestStart=Math.min(...edges.map(({successorId,edge})=>{const succ=byId.get(successorId)!,succLS=ls.get(successorId)??0,succLF=lf.get(successorId)??succLS+Math.max(1,succ.duration),lag=edge.lag;return edge.relationType==='SS'?succLS-lag:edge.relationType==='FF'?succLF-lag-duration:edge.relationType==='SF'?succLF-lag:succLS-lag-duration}))
    ls.set(id,latestStart);lf.set(id,latestStart+duration)
  }
  return tasks.map(task=>{const start=es.get(task.id)??0,duration=Math.max(1,Math.round(task.duration)),finish=start+duration,float=Math.max(0,(ls.get(task.id)??start)-start),dependencies=incoming.get(task.id)??[];return{...task,predecessors:dependencies.map(edge=>edge.predecessorId),dependencies,duration,startDate:workDateFromOffset(project.startDate,start,project.calendar),endDate:workDateFromOffset(project.startDate,finish-1,project.calendar),totalFloat:float,isCritical:float===0}})
}

function workOffsetBetween(start:string,target:string,calendar:ProjectData['calendar']){
  if(!target||target<=start)return 0
  const date=parseDate(start),end=parseDate(target);let offset=0
  while(date<end){date.setDate(date.getDate()+1);if(isWorkingDate(date,calendar))offset++}
  return offset
}

function scaledDuration(tpl:TaskTemplate,p:ProjectData) {
  let d=tpl.duration
  if(tpl.name==='主体结构施工') d=Math.max(45,Math.round(p.floorsAboveGround*p.standardFloorCycleDays/p.constructionSectionCount*2.2))
  if(tpl.name==='地下室结构施工') d=Math.max(35,Math.round(tpl.duration*(.65+p.floorsUnderground*.35)))
  if(['砌体及二次结构','机电预留预埋','管线综合安装'].includes(tpl.name)) d=Math.round(d*(.7+p.buildingCount*.075))
  if(p.isPrefabricated && tpl.name==='主体结构施工') d=Math.round(d*.86)
  return tpl.isMilestone?1:Math.max(1,d)
}

export function reviewSchedule(project:ProjectData,tasks:Task[]):ReviewItem[] {
  const risks:ReviewItem[]=[]
  const end=tasks.at(-1)?.endDate
  const ids=new Set(tasks.map(task=>task.id))
  const dangling=tasks.flatMap(task=>taskDependencies(task).filter(edge=>!ids.has(edge.predecessorId)).map(edge=>`${task.name} ← ${edge.predecessorId}`))
  if(dangling.length)risks.push({id:'dangling-dependency',level:'高',category:'逻辑完整性',title:`发现 ${dangling.length} 条无效依赖`,impact:`前置任务不存在：${dangling.slice(0,4).join('；')}${dangling.length>4?'…':''}`,suggestion:'重新绑定有效前置任务后再计算关键路径。'})
  const legacyMulti=tasks.filter(task=>task.predecessors.length>1&&!task.dependencies)
  if(legacyMulti.length)risks.push({id:'legacy-multi-dependency',level:'中',category:'数据标准',title:`${legacyMulti.length} 项多前置任务仍使用旧版共用逻辑`,impact:'多个前置任务共用一种关系和 Lag，无法准确表达专业搭接。',suggestion:'在任务调整中逐条确认每个前置任务的 FS/SS/FF/SF 和 Lag。'})
  const successorIds=new Set(tasks.flatMap(task=>taskDependencies(task).map(edge=>edge.predecessorId)))
  const openEnds=tasks.filter(task=>!successorIds.has(task.id)&&!task.isMilestone)
  if(openEnds.length)risks.push({id:'open-ended-tasks',level:'中',category:'逻辑完整性',title:`发现 ${openEnds.length} 项未接入完工节点的末端任务`,impact:`${openEnds.slice(0,5).map(task=>task.name).join('、')}${openEnds.length>5?'等':''}不会影响项目完工日期。`,suggestion:'将其连接到验收、移交或合同里程碑，避免形成开放末端。'})
  const unjustifiedLeads=tasks.flatMap(task=>taskDependencies(task).filter(edge=>edge.lag<0).map(edge=>({task,edge}))).filter(({task})=>task.isLocked||task.compressibility==='不可压缩')
  if(unjustifiedLeads.length)risks.push({id:'hard-constraint-leads',level:'高',category:'逻辑合理性',title:`${unjustifiedLeads.length} 条负 Lag 穿过锁定或不可压缩任务`,impact:'提前量可能掩盖验收、养护、检测或合同节点的真实等待时间。',suggestion:'改用明确的 SS/FF 搭接工序，或补充经批准的提前开工依据。'})
  if(end && end>project.plannedCompletionDate) risks.push({id:'duration',level:'高',category:'总工期',title:`计划超出目标工期 ${dateDiff(project.plannedCompletionDate,end)} 天`,impact:'正排计划无法自然满足锁定竣工日期。',suggestion:'优先检查关键线路，优化流水段、班组和材料供应。'})
  if(project.projectType==='房建工程'&&project.standardFloorCycleDays<4) risks.push({id:'cycle',level:'高',category:'工期合理性',title:'标准层节拍偏紧',impact:'模板、钢筋、混凝土和垂直运输可能无法支撑。',suggestion:'补充模板体系、塔吊和混凝土供应保障。'})
  tasks.filter(t=>t.status==='延期'||(t.actualEndDate&&t.actualEndDate>t.endDate)).forEach(t=>risks.push({id:`delay-${t.id}`,level:t.isCritical?'高':'中',category:'实际偏差',title:`${t.name} 已产生延期`,impact:t.isCritical?'可能影响关键线路或锁定节点。':'可尝试使用自由时差消化。',suggestion:'更新后续任务并形成纠偏措施。'}))
  if(project.dataDate){const dataDate=project.dataDate,overdue=tasks.filter(t=>t.progress<100&&t.endDate<dataDate);if(overdue.length)risks.push({id:'data-date-overdue',level:overdue.some(t=>t.isCritical)?'高':'中',category:'实际偏差',title:`截至 ${dataDate} 有 ${overdue.length} 项任务逾期未完成`,impact:`其中 ${overdue.filter(t=>t.isCritical).length} 项位于关键线路，可能影响后续里程碑。`,suggestion:'批量更新实际进度，针对关键逾期任务形成责任人、资源和纠偏完成日期。'})}
  const missingActualStart=tasks.filter(t=>t.progress>0&&!t.actualStartDate),missingActualEnd=tasks.filter(t=>t.progress===100&&!t.actualEndDate)
  if(missingActualStart.length||missingActualEnd.length)risks.push({id:'actual-date-quality',level:'中',category:'数据质量',title:`实际日期不完整：${missingActualStart.length} 项缺实际开始，${missingActualEnd.length} 项缺实际完成`,impact:'无法准确计算实际偏差、完成趋势和里程碑影响。',suggestion:'使用批量进度更新补齐数据日期和实际日期。'})
  const startedWithPending=tasks.filter(t=>t.status!=='未开始'&&t.startConditions.some(c=>c.status!=='已满足'))
  if(startedWithPending.length)risks.push({id:'started-with-pending',level:'高',category:'前置条件',title:`${startedWithPending.length} 项已开工任务仍有前置条件未闭合`,impact:'现场开工状态与审批、工作面或移交条件不一致。',suggestion:'补齐条件验收记录，或记录批准人和正式豁免依据。'})
  tasks.flatMap(t=>t.startConditions.filter(c=>c.status==='不满足').map(c=>({t,c}))).forEach(({t,c})=>risks.push({id:`condition-${t.id}-${c.id}`,level:'高',category:'前置条件',title:`${t.name}：${c.name}`,impact:'强制条件未满足时不应开工。',suggestion:'先完成条件闭合或记录正式豁免。'}))
  if(project.projectType==='房建工程'&&!tasks.some(t=>t.name.includes('设备到货'))) risks.push({id:'purchase',level:'中',category:'采购计划',title:'缺少长周期材料设备节点',impact:'电梯、消防设备、配电箱等可能脱离总控计划。',suggestion:'增加深化、招采、生产和到货节点。'})
  const required:Partial<Record<ProjectData['projectType'],string[]>>={道路工程:['路床','沥青'],桥梁工程:['桩基检测','梁板架设'],市政管网:['闭水或压力试验'],工业安装:['单机试运','联动试车']}
  const missing=(required[project.projectType]??[]).filter(name=>!tasks.some(t=>t.name.includes(name)))
  if(missing.length)risks.push({id:'type-completeness',level:'高',category:'模板完整性',title:`缺少${project.projectType}关键工序：${missing.join('、')}`,impact:'专业验收链或移交逻辑可能不完整。',suggestion:'从对应模板包补入关键工序，或创建企业自定义模板。'})
  if(project.planLevel==='工序计划'&&(project.spatialDimensions?.length??0)>0&&!tasks.some(t=>t.spacePath))risks.push({id:'space-expansion',level:'中',category:'空间组织',title:'尚无工序按空间层级展开',impact:'计划无法表达不同区域、区段或系统的流水关系。',suggestion:'在自定义模板中勾选一个或多个空间展开维度。'})
  const disconnected=tasks.filter((t,index)=>index>0&&!t.isMilestone&&!t.predecessors.length)
  if(disconnected.length)risks.push({id:'disconnected',level:'中',category:'逻辑完整性',title:`发现 ${disconnected.length} 项无前置关系的独立工序`,impact:'独立工序会默认从项目开工日开始，可能造成不合理并行。',suggestion:'检查自定义模板的前置工序名称是否与模板库完全一致。'})
  if(!tasks.some(t=>t.isMilestone&&t.isLocked))risks.push({id:'locked-milestone',level:'高',category:'节点控制',title:'计划缺少锁定里程碑',impact:'合同交付和关键移交节点可能随普通排程一起漂移。',suggestion:'至少锁定开工、关键移交和最终验收节点。'})
  if(project.projectType==='房建工程'){
    const requiredHouse=['消防专项验收','联合调试','竣工资料闭合','规划与档案预验收'],missingHouse=requiredHouse.filter(name=>!tasks.some(t=>t.name.includes(name)))
    if(missingHouse.length)risks.push({id:'house-acceptance-chain',level:'高',category:'专项验收',title:`房建验收链缺少：${missingHouse.join('、')}`,impact:'竣工验收条件可能无法完整闭合。',suggestion:'补充专项验收、联合调试、资料闭合和档案预验收节点。'})
    const commissioning=tasks.find(t=>t.name.includes('联合调试')),completion=tasks.find(t=>t.name==='竣工验收')
    if(commissioning&&completion&&dateDiff(commissioning.endDate,completion.startDate)<20)risks.push({id:'acceptance-buffer',level:'中',category:'验收缓冲',title:'联合调试至竣工验收的缓冲不足 20 天',impact:'消防、规划、档案和整改工作容易集中挤压最终交付。',suggestion:'复核专项验收并行条件，并预留整改及复验窗口。'})
    const disciplines=new Set(tasks.map(t=>t.discipline));if(disciplines.size<5)risks.push({id:'discipline-interface',level:'高',category:'专业接口',title:'计划专业覆盖不足',impact:'仅有少量专业会造成土建、机电、装修和验收接口失真。',suggestion:'补充机电、外立面、装修、采购和验收专业模板。'})
  }
  project.calendar?.shutdownPeriods.forEach(period=>{const crossed=tasks.filter(t=>t.startDate<=period.endDate&&t.endDate>=period.startDate);if(crossed.length)risks.push({id:`shutdown-${period.name}`,level:crossed.some(t=>t.isCritical)?'高':'中',category:'施工日历',title:`${period.name}穿过 ${crossed.length} 项任务`,impact:'停工期已从有效工作日中剔除，但会拉长任务日历跨度。',suggestion:'复核春节前后人员、材料和复工验收安排。'})})
  project.calendar?.weatherSensitivePeriods.forEach(period=>{const crossed=tasks.filter(t=>t.startDate<=period.endDate&&t.endDate>=period.startDate&&period.affectedPhases.some(p=>t.phase.includes(p)||t.discipline.includes(p)));if(crossed.length)risks.push({id:`weather-${period.name}`,level:crossed.some(t=>t.isCritical)?'高':'中',category:'季节影响',title:`${period.name}影响 ${crossed.length} 项敏感工序`,impact:`涉及${period.affectedPhases.join('、')}等阶段。`,suggestion:'落实雨季施工、材料保护、排水和外立面作业窗口。'})})
  analyzeResourceLoad(project,tasks).filter(load=>load.peak>load.capacity).forEach(load=>risks.push({id:`resource-${load.resource}`,level:load.peak-load.capacity>=2?'高':'中',category:'资源冲突',title:`${load.resource}峰值 ${load.peak}，超过容量 ${load.capacity}`,impact:`${load.peakDate} 同时占用：${load.activeTasks.join('、')}。`,suggestion:'调整流水段、错峰开工或增加班组/设备，并重新计算关键路径。'}))
  return risks
}

export const resourceGroup=(task:Task)=>task.discipline.includes('垂直运输')?'垂直运输':/土建|地基|砌筑|土方|测量/.test(task.discipline)?'土建施工':/机电|消防|电梯/.test(task.discipline)?'机电安装':/装饰|防水/.test(task.discipline)?'装饰装修':/幕墙|门窗|外立面/.test(task.discipline)?'外立面':task.discipline.includes('采购')?'采购管理':task.discipline
export function analyzeResourceLoad(project:ProjectData,tasks:Task[]):ResourceLoad[]{
  const groups=new Map<string,Task[]>();tasks.filter(t=>!t.isMilestone).forEach(t=>{const key=resourceGroup(t);groups.set(key,[...(groups.get(key)??[]),t])})
  const capacity=(resource:string)=>Math.max(1,Math.round(project.resourceCapacities?.[resource]??(resource==='垂直运输'?project.towerCraneCount:resource==='土建施工'?project.constructionSectionCount:['机电安装','装饰装修','外立面'].includes(resource)?2:1)))
  return [...groups].map(([resource,items])=>{const counts=new Map<string,string[]>();items.forEach(task=>{const date=parseDate(task.startDate),end=parseDate(task.endDate);while(date<=end){if(isWorkingDate(date,project.calendar)){const key=fmtDate(date);counts.set(key,[...(counts.get(key)??[]),task.name])}date.setDate(date.getDate()+1)}});let peak=0,peakDate='',activeTasks:string[]=[];counts.forEach((names,date)=>{if(names.length>peak){peak=names.length;peakDate=date;activeTasks=names}});const cap=capacity(resource);return{resource,capacity:cap,peak,peakDate,activeTasks,overloadedDays:[...counts.values()].filter(names=>names.length>cap).length}}).sort((a,b)=>(b.peak-b.capacity)-(a.peak-a.capacity)||b.peak-a.peak)
}

export function levelResourceConflicts(project:ProjectData,tasks:Task[]):ResourceLevelingResult{
  let result=tasks.map(t=>({...t}));const shifted=new Map<string,number>()
  const initial=analyzeResourceLoad(project,result).filter(x=>x.peak>x.capacity)
  for(let attempt=0;attempt<366;attempt++){
    const conflict=analyzeResourceLoad(project,result).find(x=>x.peak>x.capacity)
    if(!conflict)break
    const byId=new Map(result.map(t=>[t.id,t])),successors=new Map<string,string[]>()
    result.forEach(t=>t.predecessors.forEach(id=>successors.set(id,[...(successors.get(id)??[]),t.id])))
    const chain=(id:string)=>{const ids=new Set([id]),queue=[id];while(queue.length){for(const next of successors.get(queue.shift()!)??[]){if(!ids.has(next)){ids.add(next);queue.push(next)}}}return ids}
    const candidates=result.filter(t=>!t.isMilestone&&resourceGroup(t)===conflict.resource&&t.startDate<=conflict.peakDate&&t.endDate>=conflict.peakDate)
      .map(task=>({task,chain:chain(task.id)})).filter(x=>![...x.chain].some(id=>byId.get(id)?.isLocked))
      .sort((a,b)=>Number(a.task.isCritical)-Number(b.task.isCritical)||b.task.totalFloat-a.task.totalFloat||b.task.startDate.localeCompare(a.task.startDate))
    const choice=candidates[0]
    if(!choice)break
    result=result.map(t=>choice.chain.has(t.id)?{...t,startDate:shiftWorkingDate(t.startDate,1,project.calendar),endDate:shiftWorkingDate(t.endDate,1,project.calendar),source:'手动修改'}:t)
    shifted.set(choice.task.id,(shifted.get(choice.task.id)??0)+1)
  }
  const remaining=analyzeResourceLoad(project,result).filter(x=>x.peak>x.capacity)
  return{tasks:result,shifted:[...shifted].map(([taskId,days])=>({taskId,taskName:tasks.find(t=>t.id===taskId)?.name??taskId,days})),beforeConflicts:initial.length,afterConflicts:remaining.length,unresolved:remaining.map(x=>x.resource)}
}

export function exportProjectJson(project:ProjectData,tasks:Task[],baselines:unknown[]=[],customTemplates:TaskTemplate[]=[]){
  const payload={schemaVersion:4,exportedAt:new Date().toISOString(),project,tasks,baselines,customTemplates}
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));a.download=`${project.projectName||'施工计划'}-备份.json`;a.click();URL.revokeObjectURL(a.href)
}

export function exportCsv(tasks:Task[]) {
  const rows=[['WBS','任务名称','阶段','专业','空间路径','工程量','单位','资源投入','材料节点','状态','工期','计划开始','计划结束','实际开始','实际完成','偏差天数','锁定节点','前置任务','逻辑关系','关键线路','责任单位','风险提示','生成依据'],...tasks.map(t=>{const dependencies=taskDependencies(t);return[t.wbsCode,t.name,t.phase,t.discipline,t.spacePath?Object.entries(t.spacePath).map(([k,v])=>`${k}:${v}`).join('/'):[t.building,t.floor,t.workArea].filter(Boolean).join('/'),t.quantity??'',t.unit??'',t.resourceDemand?.join(';')??'',t.materialNodes?.join(';')??'',t.status,t.duration,t.startDate,t.endDate,t.actualStartDate??'',t.actualEndDate??'',t.actualEndDate?Math.max(0,dateDiff(t.endDate,t.actualEndDate)):0,t.isLocked?'是':'否',dependencies.map(edge=>edge.predecessorId).join(';'),dependencies.map(edge=>`${edge.relationType}${edge.lag>=0?'+':''}${edge.lag}`).join(';'),t.isCritical?'是':'否',t.responsibleParty,t.riskNote??'',t.generationBasis]})]
  const csv='\uFEFF'+rows.map(r=>r.map(v=>`"${String(v).replaceAll('"','""')}"`).join(',')).join('\n')
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));a.download='ai-construction-schedule.csv';a.click();URL.revokeObjectURL(a.href)
}
