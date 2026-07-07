import type { ProjectData, ProjectType, ReviewItem, TaskTemplate } from '../types.ts'
import { generateSchedule, reviewSchedule } from './schedule.ts'

export interface TemplateCandidate extends TaskTemplate {
  reason: string
  confidence: number
}

export interface PipelineAudit {
  taskCount: number
  criticalCount: number
  finishDate: string
  pendingConditions: number
  risks: ReviewItem[]
}

export function validateProject(project:ProjectData):string[]{
  const errors:string[]=[]
  if(!project.projectName.trim())errors.push('请填写项目名称')
  if(!project.location.trim())errors.push('请填写建设地点')
  if(!project.startDate||!project.plannedCompletionDate)errors.push('请填写计划开工和竣工日期')
  else if(project.startDate>project.plannedCompletionDate)errors.push('计划竣工日期不能早于开工日期')
  if(project.planLevel==='工序计划'){
    if(!project.spatialDimensions?.length)errors.push('工序计划至少需要一个空间维度')
    project.spatialDimensions?.forEach(d=>{if(!d.name.trim())errors.push('空间维度名称不能为空');if(!d.values.length)errors.push(`空间维度“${d.name||'未命名'}”至少需要一个取值`)})
  }
  if(project.projectType==='房建工程'){
    if(project.buildingCount<1)errors.push('楼栋数量至少为 1')
    if(project.floorsAboveGround<1)errors.push('地上层数至少为 1')
  }
  return [...new Set(errors)]
}

export function projectConfidence(project:ProjectData,description:string){
  const checks=[project.projectType,project.projectName.trim(),project.location.trim(),project.startDate,project.plannedCompletionDate,(project.spatialDimensions?.length??0)>0,description.trim().length>=12]
  return Math.round(checks.filter(Boolean).length/checks.length*100)
}

const candidate=(projectType:ProjectType,id:string,name:string,phase:string,discipline:string,duration:number,predecessorNames:string[],reason:string,confidence:number,extra:Partial<TaskTemplate>={}):TemplateCandidate=>({
  id,name,phase,discipline,duration,predecessorNames,reason,confidence,projectType,isCustom:true,version:1,
  relationType:'FS',lag:0,compressibility:'部分可压缩',responsibleParty:'总包单位',quantityUnit:'项',...extra,
})

export function suggestTemplatesLocally(project:ProjectData,description:string,existing:TaskTemplate[]):TemplateCandidate[]{
  const hit=(pattern:RegExp)=>pattern.test(description)
  const suggestions:Record<ProjectType,TemplateCandidate[]>={
    房建工程:[
      candidate('房建工程','AI-H-01','BIM综合深化确认','前期准备','技术管理',10,['施工组织设计审批'],'减少机电、结构与装修界面碰撞',hit(/BIM|深化|碰撞/)?88:62,{materialNodes:['综合模型会审完成']}),
      candidate('房建工程','AI-H-02','人防专项验收','竣工验收','验收移交',7,['联合调试'],'补齐专项验收与竣工验收之间的接口',hit(/人防|专项验收/)?91:66,{compressibility:'不可压缩'}),
    ],
    道路工程:[
      candidate('道路工程','AI-R-01','交通导改实施','前期准备','交通组织',5,['施工组织设计审批'],'道路施工通常需要分阶段交通组织',hit(/导改|保通|交通组织/)?92:68,{expansionDimensions:['标段']}),
      candidate('道路工程','AI-R-02','软基处理与检测','路基工程','地基处理',12,['清表与临时排水'],'避免软弱地基影响路基沉降和交工质量',hit(/软基|换填|搅拌桩/)?91:58,{expansionDimensions:['标段','施工区段'],quantityUnit:'m³'}),
    ],
    桥梁工程:[
      candidate('桥梁工程','AI-B-01','施工监控与线形复核','上部结构','测量监控',6,['梁板架设'],'控制架设过程线形、标高和结构状态',hit(/监控|线形|连续梁/)?90:65,{expansionDimensions:['桥梁']}),
      candidate('桥梁工程','AI-B-02','支架预压与验收','上部结构','临时结构',7,['盖梁施工'],'现浇或支架体系需要预压和验收闭环',hit(/支架|现浇|预压/)?92:56,{expansionDimensions:['桥梁','墩台']}),
    ],
    市政管网:[
      candidate('市政管网','AI-P-01','既有管线保护与导改','前期准备','管线迁改',6,['管线交底与测量放线'],'降低既有管线冲突和停运风险',hit(/导改|迁改|既有管线/)?93:71,{expansionDimensions:['片区']}),
      candidate('市政管网','AI-P-02','冲洗消毒与水质检测','试验验收','试验检测',4,['闭水或压力试验'],'给水系统投用前需要形成检测闭环',hit(/给水|消毒|水质/)?91:61,{expansionDimensions:['片区','管段'],compressibility:'不可压缩'}),
    ],
    工业安装:[
      candidate('工业安装','AI-I-01','大件设备吊装方案审批','前期准备','吊装管理',8,['装置区移交'],'提前锁定吊装路径、机具和安全条件',hit(/大件|吊装|超限/)?94:72,{expansionDimensions:['装置区']}),
      candidate('工业安装','AI-I-02','保温防腐施工','管道安装','防腐保温',8,['管道试压与吹扫'],'补齐试压后防腐保温与交付接口',hit(/保温|防腐/)?90:67,{expansionDimensions:['装置区','系统'],quantityUnit:'m²'}),
    ],
    自定义工程:[
      candidate('自定义工程','AI-C-01','专项施工方案审批','项目管理','技术管理',5,['项目启动'],'为自定义工程建立技术启动条件',76),
      candidate('自定义工程','AI-C-02','分项验收与移交','验收移交','质量管理',3,['专项施工方案审批'],'形成施工、验收和移交闭环',72,{compressibility:'不可压缩'}),
    ],
  }
  const names=new Set(existing.map(t=>t.name))
  return suggestions[project.projectType].filter(t=>!names.has(t.name))
}

export function auditCandidatePlan(project:ProjectData,templates:TaskTemplate[]):PipelineAudit{
  const tasks=generateSchedule(project,templates)
  return{taskCount:tasks.length,criticalCount:tasks.filter(t=>t.isCritical).length,finishDate:tasks.at(-1)?.endDate??'',pendingConditions:tasks.reduce((n,t)=>n+t.startConditions.filter(c=>c.status==='待确认').length,0),risks:reviewSchedule(project,tasks)}
}
