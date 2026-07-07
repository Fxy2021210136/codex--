import type { AiSettings, ProjectData, Task, TaskTemplate } from './types'
import type { TemplateCandidate } from './engine/agentPipeline'
import { apiUrl, getClientId } from './api'

async function request(settings:AiSettings,system:string,user:string) {
  const r=await fetch(apiUrl('/api/ai/chat'),{method:'POST',headers:{'Content-Type':'application/json','X-Client-Id':getClientId()},body:JSON.stringify({messages:[{role:'system',content:system},{role:'user',content:user}]})})
  const result=await r.json().catch(()=>({}))
  if(!r.ok)throw new Error((result as {error?:string}).error||`AI 服务请求失败：HTTP ${r.status}`)
  return result
}

export async function parseProjectWithAi(text:string,settings:AiSettings):Promise<Partial<ProjectData>> {
  const result=await request(settings,'你是通用工程进度计划工程师。只返回有效 JSON，不得虚构未提供的日期和工程量。projectType 只能是房建工程、道路工程、桥梁工程、市政管网、工业安装、自定义工程之一。',`从以下项目描述提取 projectType,projectName,location,grossFloorArea,startDate,plannedCompletionDate,spatialDimensions；如果是房建工程再提取 buildingCount,floorsAboveGround,floorsUnderground,structureType,foundationType,standardFloorCycleDays,hasDeepFoundationPit,hasFineDecoration,hasCurtainWall,isPrefabricated。spatialDimensions 格式为 [{"id":"...","name":"标段/楼栋/区域等","values":["..."]}]：\n${text}`)
  return result.projectData??result
}

export async function generateTemplateCandidatesWithAi(text:string,project:ProjectData,templates:TaskTemplate[],settings:AiSettings):Promise<TemplateCandidate[]> {
  const result=await request(settings,'你是工程计划模板专家。只返回 JSON：{"candidates":[{"name":"...","phase":"...","discipline":"...","duration":数字,"predecessorNames":["现有工序名称"],"relationType":"FS","lag":0,"compressibility":"部分可压缩","responsibleParty":"...","expansionDimensions":["空间维度名称"],"quantityUnit":"...","resourceDemand":["..."],"materialNodes":["..."],"reason":"...","confidence":0到100}]}。最多返回3项，前置名称必须来自现有工序。',`项目描述：${text}\n项目：${JSON.stringify(project)}\n空间维度：${JSON.stringify(project.spatialDimensions??[])}\n现有模板：${JSON.stringify(templates.map(t=>({name:t.name,phase:t.phase,discipline:t.discipline})))}`)
  const rows=Array.isArray(result.candidates)?result.candidates:[]
  const existingNames=new Set(templates.map(t=>t.name)),dimensionNames=new Set((project.spatialDimensions??[]).map(d=>d.name))
  return rows.slice(0,3).filter((x:Record<string,unknown>)=>typeof x.name==='string'&&x.name.trim()&&!existingNames.has(x.name)).map((x:Record<string,unknown>,index:number)=>({
    id:`AI-${Date.now()}-${index+1}`,name:String(x.name).trim(),phase:typeof x.phase==='string'?x.phase:'专项工程',discipline:typeof x.discipline==='string'?x.discipline:'专项工程',duration:Math.max(1,Math.round(Number(x.duration)||5)),
    predecessorNames:Array.isArray(x.predecessorNames)?x.predecessorNames.filter((n:unknown):n is string=>typeof n==='string'&&existingNames.has(n)):[],relationType:['FS','SS','FF','SF'].includes(String(x.relationType))?x.relationType as TaskTemplate['relationType']:'FS',lag:Math.round(Number(x.lag)||0),
    compressibility:['可压缩','部分可压缩','不可压缩'].includes(String(x.compressibility))?x.compressibility as TaskTemplate['compressibility']:'部分可压缩',responsibleParty:typeof x.responsibleParty==='string'?x.responsibleParty:'总包单位',
    projectType:project.projectType,isCustom:true,version:1,expansionDimensions:Array.isArray(x.expansionDimensions)?x.expansionDimensions.filter((n:unknown):n is string=>typeof n==='string'&&dimensionNames.has(n)):[],quantityUnit:typeof x.quantityUnit==='string'?x.quantityUnit:'项',
    resourceDemand:Array.isArray(x.resourceDemand)?x.resourceDemand.filter((n:unknown):n is string=>typeof n==='string'):[],materialNodes:Array.isArray(x.materialNodes)?x.materialNodes.filter((n:unknown):n is string=>typeof n==='string'):[],reason:typeof x.reason==='string'?x.reason:'AI 建议补充的专项工序',confidence:Math.min(100,Math.max(0,Math.round(Number(x.confidence)||70))),
  }))
}

export async function explainSchedule(prompt:string,project:ProjectData,tasks:Task[],settings:AiSettings) {
  const result=await request(settings,'你是通用工程总进度计划专家。返回 {"summary":"...","recommendations":["..."]}。',`${prompt}\n项目：${JSON.stringify(project)}\n任务：${JSON.stringify(tasks)}`)
  return [result.summary,...(result.recommendations??[])].filter(Boolean).join('\n')
}

export async function modifyScheduleWithAi(prompt:string,project:ProjectData,tasks:Task[],settings:AiSettings) {
  const result=await request(settings,'你是施工总进度计划专家。只返回 JSON：{"summary":"变更说明","taskPatches":[{"id":"任务ID","changes":{"startDate":"YYYY-MM-DD","endDate":"YYYY-MM-DD","duration":数字,"status":"状态","progress":数字}}]}。只能使用输入中存在的任务 ID；不得修改 ID；锁定节点除非用户明确要求否则不能移动。',`${prompt}\n项目：${JSON.stringify(project)}\n当前任务：${JSON.stringify(tasks)}`)
  const validIds=new Set(tasks.map(t=>t.id))
  const allowed=new Set(['startDate','endDate','duration','status','progress','actualStartDate','actualEndDate','riskNote','responsibleParty'])
  const patches=Array.isArray(result.taskPatches)?result.taskPatches.filter((p:{id?:string})=>p&&typeof p.id==='string'&&validIds.has(p.id)).map((p:{id:string;changes?:Record<string,unknown>})=>({id:p.id,changes:Object.fromEntries(Object.entries(p.changes??{}).filter(([key])=>allowed.has(key))) as Partial<Task>})):[]
  return {summary:typeof result.summary==='string'?result.summary:'AI 已生成计划调整。',patches}
}

export function parseProjectLocally(text:string):Partial<ProjectData> {
  const result:Partial<ProjectData>={}
  if(/道路|公路|路基|路面|桩号/.test(text))result.projectType='道路工程'
  else if(/桥梁|墩台|桥面|架梁/.test(text))result.projectType='桥梁工程'
  else if(/管网|管道|检查井|管段/.test(text))result.projectType='市政管网'
  else if(/装置区|工业安装|工艺管道|联动试车/.test(text))result.projectType='工业安装'
  else if(/住宅|办公楼|商业楼|楼栋|建筑面积/.test(text))result.projectType='房建工程'
  const buildings=text.match(/(\d+)\s*栋/), floors=text.match(/(?:地上)?\s*(\d+)\s*层/), underground=text.match(/地下\s*(\d+)\s*层/), area=text.match(/(?:建面|建筑面积|总建面)(?:约)?\s*([\d.]+)\s*(万)?/)
  if(buildings) result.buildingCount=Number(buildings[1]);if(floors) result.floorsAboveGround=Number(floors[1]);if(underground) result.floorsUnderground=Number(underground[1]);if(area) result.grossFloorArea=Math.round(Number(area[1])*(area[2]?10000:1))
  if(text.includes('剪力墙')) result.structureType='剪力墙结构';else if(text.includes('框架')) result.structureType='框架结构';if(text.includes('桩')) result.foundationType='桩基础'
  result.hasFineDecoration=text.includes('精装修');result.hasCurtainWall=text.includes('幕墙');result.hasDeepFoundationPit=text.includes('深基坑')||Number(result.floorsUnderground)>1;result.isPrefabricated=text.includes('装配式')
  return result
}
