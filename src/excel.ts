import { analyzeResourceLoad, dateDiff, reviewSchedule, taskDependencies } from './engine/schedule.ts'
import type { PlanBaseline, ProjectData, Task } from './types.ts'

type XlsxModule=typeof import('xlsx')
const asDate=(value?:string)=>value?new Date(`${value}T00:00:00`):''
const setWidths=(sheet:import('xlsx').WorkSheet,widths:number[])=>{sheet['!cols']=widths.map(wch=>({wch}))}
const addSheet=(XLSX:XlsxModule,workbook:import('xlsx').WorkBook,name:string,rows:unknown[][],widths:number[])=>{
  const sheet=XLSX.utils.aoa_to_sheet(rows,{cellDates:true})
  setWidths(sheet,widths)
  if(rows.length>1&&rows[0].length>1)sheet['!autofilter']={ref:XLSX.utils.encode_range({s:{r:0,c:0},e:{r:rows.length-1,c:rows[0].length-1}})}
  XLSX.utils.book_append_sheet(workbook,sheet,name)
  return sheet
}

function createProjectWorkbook(XLSX:XlsxModule,project:ProjectData,tasks:Task[],baselines:PlanBaseline[]=[]){
  const workbook=XLSX.utils.book_new()
  workbook.Props={Title:`${project.projectName}施工进度计划`,Subject:'施工进度计划、资源负荷与风险审查',Author:'Schedule AI',CreatedDate:new Date()}
  addSheet(XLSX,workbook,'项目概览',[
    ['项目指标','数据'],['项目名称',project.projectName],['项目类型',project.projectType],['建设地点',project.location],['空间层级',project.spatialDimensions?.map(d=>`${d.name}：${d.values.join('、')}`).join('；')??'-'],
    ['结构/系统',project.projectType==='房建工程'?project.structureType:'按项目空间层级组织'],['规模指标',project.grossFloorArea],
    ['计划开工',asDate(project.startDate)],['目标竣工',asDate(project.plannedCompletionDate)],['当前计算完工',asDate(tasks.at(-1)?.endDate)],
    ['任务总数',tasks.length],['关键任务',tasks.filter(t=>t.isCritical).length],['当前总工期(天)',tasks.length?dateDiff(project.startDate,tasks.at(-1)!.endDate)+1:0],
  ],[24,38])
  const wbsRows:unknown[][]=[['WBS','任务名称','阶段','专业','空间路径','工程量','单位','资源投入','材料节点','状态','工期(天)','计划开始','计划完成','实际开始','实际完成','偏差(天)','前置任务','关系','总时差','关键','责任单位','风险提示','生成依据']]
  tasks.forEach((t,index)=>{const row=index+2,space=t.spacePath?Object.entries(t.spacePath).map(([k,v])=>`${k}：${v}`).join(' / '):[t.building,t.floor,t.workArea].filter(Boolean).join(' / '),dependencies=taskDependencies(t);wbsRows.push([t.wbsCode,t.name,t.phase,t.discipline,space,t.quantity??'',t.unit??'',t.resourceDemand?.join('；')??'',t.materialNodes?.join('；')??'',t.status,t.duration,asDate(t.startDate),asDate(t.endDate),asDate(t.actualStartDate),asDate(t.actualEndDate),{f:`IF(O${row}="","",MAX(0,O${row}-M${row}))`,v:t.actualEndDate?Math.max(0,dateDiff(t.endDate,t.actualEndDate)):0,t:'n'},dependencies.map(edge=>edge.predecessorId).join(';'),dependencies.map(edge=>`${edge.relationType}${edge.lag>=0?'+':''}${edge.lag}`).join(';'),t.totalFloat,t.isCritical?'是':'否',t.responsibleParty,t.riskNote??'',t.generationBasis])})
  addSheet(XLSX,workbook,'WBS计划',wbsRows,[10,30,16,16,32,12,8,22,30,14,10,13,13,13,13,10,22,10,10,8,18,28,30])
  const loads=analyzeResourceLoad(project,tasks)
  addSheet(XLSX,workbook,'资源负荷',[['资源池','容量','峰值','利用率','峰值日期','超载天数','峰值任务'],...loads.map(x=>[x.resource,x.capacity,x.peak,x.peak/x.capacity,asDate(x.peakDate),x.overloadedDays,x.activeTasks.join('、')])],[18,10,10,12,14,12,50])
  const risks=reviewSchedule(project,tasks)
  addSheet(XLSX,workbook,'风险审查',[['等级','类别','风险事项','影响','处理建议'],...risks.map(x=>[x.level,x.category,x.title,x.impact,x.suggestion])],[10,16,34,48,48])
  addSheet(XLSX,workbook,'计划基准',[['基准名称','创建时间','任务','计划开始','计划完成','工期(天)'],...baselines.flatMap(b=>b.tasks.map(t=>[b.name,new Date(b.createdAt),t.name,asDate(t.startDate),asDate(t.endDate),t.duration]))],[20,20,28,14,14,12])
  return workbook
}

export async function buildProjectWorkbook(project:ProjectData,tasks:Task[],baselines:PlanBaseline[]=[]){
  const XLSX=await import('xlsx')
  return createProjectWorkbook(XLSX,project,tasks,baselines)
}

export async function exportProjectExcel(project:ProjectData,tasks:Task[],baselines:PlanBaseline[]=[]){
  const XLSX=await import('xlsx')
  const data=XLSX.write(createProjectWorkbook(XLSX,project,tasks,baselines),{bookType:'xlsx',type:'array',cellDates:true,compression:true})
  const a=document.createElement('a')
  a.href=URL.createObjectURL(new Blob([data],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}))
  a.download=`${project.projectName||'施工进度计划'}-${new Date().toISOString().slice(0,10)}.xlsx`
  a.click();URL.revokeObjectURL(a.href)
}
