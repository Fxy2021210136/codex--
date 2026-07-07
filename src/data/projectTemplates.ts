import type { ProjectData, ProjectType, SpatialDimension, TaskTemplate } from '../types'
import { BASE_TEMPLATES } from './templates.ts'

const template=(id:string,phase:string,name:string,duration:number,predecessorNames:string[],extra:Partial<TaskTemplate>={}):TaskTemplate=>({
  id,phase,name,duration,predecessorNames,discipline:phase,relationType:'FS',lag:0,
  compressibility:'部分可压缩',responsibleParty:'总包单位',...extra,
})

const ROAD:TaskTemplate[]=[
  template('RD-001','前期准备','场地与控制点移交',1,[],{isMilestone:true,isLocked:true}),
  template('RD-002','前期准备','施工组织设计审批',7,['场地与控制点移交'],{discipline:'技术管理'}),
  template('RD-003','路基工程','清表与临时排水',5,['施工组织设计审批'],{expansionDimensions:['标段','施工区段'],quantityUnit:'m²'}),
  template('RD-004','路基工程','路基开挖与填筑',15,['清表与临时排水'],{expansionDimensions:['标段','施工区段'],quantityUnit:'m³',materialNodes:['填料试验确认','压实设备到位']}),
  template('RD-005','排水工程','雨污水管道施工',12,['清表与临时排水'],{relationType:'SS',lag:2,expansionDimensions:['标段','施工区段'],quantityUnit:'m'}),
  template('RD-006','路基工程','路床整形与验收',4,['路基开挖与填筑','雨污水管道施工'],{expansionDimensions:['标段','施工区段'],quantityUnit:'m²'}),
  template('RD-007','路面工程','水稳基层施工',7,['路床整形与验收'],{expansionDimensions:['标段','施工区段'],quantityUnit:'m²',materialNodes:['水稳配合比审批']}),
  template('RD-008','路面工程','沥青面层施工',4,['水稳基层施工'],{expansionDimensions:['标段','施工区段'],quantityUnit:'m²',materialNodes:['沥青混合料试验确认']}),
  template('RD-009','附属工程','交安与照明施工',6,['沥青面层施工'],{expansionDimensions:['标段','施工区段'],quantityUnit:'m'}),
  template('RD-010','竣工验收','道路工程验收',1,['交安与照明施工'],{isMilestone:true,isLocked:true,compressibility:'不可压缩'}),
]

const BRIDGE:TaskTemplate[]=[
  template('BR-001','前期准备','测量控制网移交',1,[],{isMilestone:true,isLocked:true}),
  template('BR-002','基础工程','桩基施工',18,['测量控制网移交'],{expansionDimensions:['桥梁','墩台'],quantityUnit:'根',materialNodes:['钢筋笼验收','混凝土供应确认']}),
  template('BR-003','基础工程','桩基检测',5,['桩基施工'],{expansionDimensions:['桥梁','墩台'],quantityUnit:'根',compressibility:'不可压缩'}),
  template('BR-004','下部结构','承台施工',8,['桩基检测'],{expansionDimensions:['桥梁','墩台'],quantityUnit:'m³'}),
  template('BR-005','下部结构','墩台身施工',10,['承台施工'],{expansionDimensions:['桥梁','墩台'],quantityUnit:'m³'}),
  template('BR-006','下部结构','盖梁施工',7,['墩台身施工'],{expansionDimensions:['桥梁','墩台'],quantityUnit:'m³'}),
  template('BR-007','上部结构','梁板预制与进场',30,['桩基施工'],{relationType:'SS',lag:5,expansionDimensions:['桥梁'],quantityUnit:'片'}),
  template('BR-008','上部结构','梁板架设',8,['盖梁施工','梁板预制与进场'],{expansionDimensions:['桥梁','墩台'],quantityUnit:'片',materialNodes:['架梁方案审批','支座到场验收']}),
  template('BR-009','桥面工程','桥面系及附属施工',12,['梁板架设'],{expansionDimensions:['桥梁'],quantityUnit:'m²'}),
  template('BR-010','竣工验收','桥梁工程验收',1,['桥面系及附属施工'],{isMilestone:true,isLocked:true,compressibility:'不可压缩'}),
]

const PIPELINE:TaskTemplate[]=[
  template('MW-001','前期准备','管线交底与测量放线',2,[],{isMilestone:true}),
  template('MW-002','沟槽工程','沟槽开挖与支护',6,['管线交底与测量放线'],{expansionDimensions:['片区','管段'],quantityUnit:'m³'}),
  template('MW-003','管道工程','管道基础施工',3,['沟槽开挖与支护'],{expansionDimensions:['片区','管段'],quantityUnit:'m'}),
  template('MW-004','管道工程','管道安装与接口',6,['管道基础施工'],{expansionDimensions:['片区','管段'],quantityUnit:'m',materialNodes:['管材进场复验']}),
  template('MW-005','井室工程','检查井与阀门井施工',5,['管道基础施工'],{relationType:'SS',lag:1,expansionDimensions:['片区','管段'],quantityUnit:'座'}),
  template('MW-006','试验验收','闭水或压力试验',3,['管道安装与接口','检查井与阀门井施工'],{expansionDimensions:['片区','管段'],quantityUnit:'段',compressibility:'不可压缩'}),
  template('MW-007','恢复工程','沟槽回填',4,['闭水或压力试验'],{expansionDimensions:['片区','管段'],quantityUnit:'m³'}),
  template('MW-008','恢复工程','道路及场地恢复',4,['沟槽回填'],{expansionDimensions:['片区','管段'],quantityUnit:'m²'}),
  template('MW-009','竣工验收','管网工程验收',1,['道路及场地恢复'],{isMilestone:true,isLocked:true}),
]

const INDUSTRIAL:TaskTemplate[]=[
  template('IN-001','前期准备','装置区移交',1,[],{isMilestone:true,isLocked:true}),
  template('IN-002','前期准备','施工组织设计与专项方案审批',8,['装置区移交'],{discipline:'技术管理',compressibility:'不可压缩'}),
  template('IN-003','设计管理','图纸会审与三维模型确认',10,['装置区移交'],{discipline:'设计管理',materialNodes:['设备接口条件确认','管口方位确认']}),
  template('IN-004','采购管理','长周期设备采购与制造',75,['图纸会审与三维模型确认'],{discipline:'采购管理',relationType:'SS',lag:2,expansionDimensions:['系统'],quantityUnit:'台',materialNodes:['技术协议签订','制造进度检查','出厂验收']}),
  template('IN-005','土建基础','设备基础施工',18,['施工组织设计与专项方案审批','图纸会审与三维模型确认'],{expansionDimensions:['装置区','系统'],quantityUnit:'m³',materialNodes:['地脚螺栓复核','预留孔洞验收']}),
  template('IN-006','土建基础','预埋件与接地网验收',3,['设备基础施工'],{discipline:'土建与电气接口',expansionDimensions:['装置区','系统'],quantityUnit:'处',compressibility:'不可压缩'}),
  template('IN-007','设备安装','主要设备到货验收',2,['长周期设备采购与制造'],{expansionDimensions:['装置区','系统'],quantityUnit:'台',materialNodes:['装箱清单核验','随机资料移交','开箱验收']}),
  template('IN-008','吊装管理','大件设备吊装方案审批',10,['图纸会审与三维模型确认'],{discipline:'吊装管理',compressibility:'不可压缩'}),
  template('IN-009','设备安装','设备吊装与就位',8,['预埋件与接地网验收','主要设备到货验收','大件设备吊装方案审批'],{expansionDimensions:['装置区','系统'],quantityUnit:'台',resourceDemand:['起重设备 1台','设备安装班组 1组']}),
  template('IN-010','设备安装','设备找正与二次灌浆',7,['设备吊装与就位'],{expansionDimensions:['装置区','系统'],quantityUnit:'台',compressibility:'不可压缩'}),
  template('IN-011','管道安装','工艺管道预制',15,['图纸会审与三维模型确认'],{relationType:'SS',lag:3,expansionDimensions:['装置区','系统'],quantityUnit:'寸径',materialNodes:['焊接工艺评定','材料复验']}),
  template('IN-012','管道安装','工艺管道安装',18,['设备找正与二次灌浆','工艺管道预制'],{expansionDimensions:['装置区','系统'],quantityUnit:'寸径',resourceDemand:['管道安装班组 1组','焊接班组 1组']}),
  template('IN-013','电仪安装','电气盘柜与电缆安装',16,['设备吊装与就位','预埋件与接地网验收'],{relationType:'SS',lag:2,expansionDimensions:['装置区','系统'],quantityUnit:'回路'}),
  template('IN-014','电仪安装','仪表与控制系统安装',15,['设备吊装与就位'],{relationType:'SS',lag:2,expansionDimensions:['装置区','系统'],quantityUnit:'点'}),
  template('IN-015','试压吹扫','管道试压',6,['工艺管道安装'],{expansionDimensions:['装置区','系统'],quantityUnit:'试压包',compressibility:'不可压缩',materialNodes:['试压包批准','压力表校验']}),
  template('IN-016','试压吹扫','管道吹扫与清洗',6,['管道试压'],{expansionDimensions:['装置区','系统'],quantityUnit:'系统',compressibility:'不可压缩'}),
  template('IN-017','防腐保温','防腐保温与标识',10,['管道试压'],{relationType:'SS',lag:1,expansionDimensions:['装置区','系统'],quantityUnit:'m²'}),
  template('IN-018','电仪调试','受送电与电气试验',6,['电气盘柜与电缆安装'],{expansionDimensions:['装置区','系统'],quantityUnit:'系统',compressibility:'不可压缩'}),
  template('IN-019','电仪调试','仪表回路与联锁测试',7,['仪表与控制系统安装'],{expansionDimensions:['装置区','系统'],quantityUnit:'回路',compressibility:'不可压缩'}),
  template('IN-020','中间交接','三查四定与系统中间交接',5,['管道吹扫与清洗','防腐保温与标识','受送电与电气试验','仪表回路与联锁测试'],{expansionDimensions:['装置区','系统'],quantityUnit:'系统',compressibility:'不可压缩'}),
  template('IN-021','调试工程','单机试运',5,['三查四定与系统中间交接'],{expansionDimensions:['装置区','系统'],quantityUnit:'台',compressibility:'不可压缩'}),
  template('IN-022','调试工程','联动试车',7,['单机试运'],{compressibility:'不可压缩',materialNodes:['联动试车方案批准','公用工程条件确认']}),
  template('IN-023','性能考核','投料试车与性能考核',10,['联动试车'],{compressibility:'不可压缩',materialNodes:['原料与产品方案确认','性能考核方案批准']}),
  template('IN-024','资料交付','竣工资料与备品备件移交',10,['三查四定与系统中间交接'],{relationType:'SS',lag:0,discipline:'资料管理'}),
  template('IN-025','竣工验收','装置性能验收',1,['投料试车与性能考核','竣工资料与备品备件移交'],{isMilestone:true,isLocked:true,compressibility:'不可压缩'}),
]

const CUSTOM_STARTER:TaskTemplate[]=[
  template('CU-001','项目管理','项目启动',1,[],{isMilestone:true}),
  template('CU-002','竣工验收','项目完成',1,['项目启动'],{isMilestone:true,isLocked:true}),
]

export const PROJECT_TYPES:ProjectType[]=['房建工程','道路工程','桥梁工程','市政管网','工业安装','自定义工程']
export const TEMPLATE_PACKS:Record<ProjectType,TaskTemplate[]>={
  房建工程:BASE_TEMPLATES,道路工程:ROAD,桥梁工程:BRIDGE,市政管网:PIPELINE,工业安装:INDUSTRIAL,自定义工程:CUSTOM_STARTER,
}

export function defaultDimensions(type:ProjectType,project?:ProjectData):SpatialDimension[]{
  const buildingCount=Math.max(1,project?.buildingCount??1),floors=Math.max(1,project?.floorsAboveGround??1)
  const presets:Record<ProjectType,SpatialDimension[]>={
    房建工程:[{id:'building',name:'楼栋',values:Array.from({length:buildingCount},(_,i)=>`${i+1}#楼`)},{id:'floor',name:'楼层',values:Array.from({length:floors},(_,i)=>`${i+1}层`)}],
    道路工程:[{id:'contract',name:'标段',values:['一标段']},{id:'section',name:'施工区段',values:['K0+000～K0+500','K0+500～K1+000']}],
    桥梁工程:[{id:'bridge',name:'桥梁',values:['主桥']},{id:'pier',name:'墩台',values:['0#台','1#墩','2#墩','3#台']}],
    市政管网:[{id:'area',name:'片区',values:['A区']},{id:'pipeline',name:'管段',values:['A-01','A-02','A-03']}],
    工业安装:[{id:'plant',name:'装置区',values:['主装置区']},{id:'system',name:'系统',values:['工艺系统','公用工程系统']}],
    自定义工程:[{id:'area',name:'区域',values:['区域A']},{id:'workface',name:'作业面',values:['作业面1']}],
  }
  return presets[type]
}

export function templatesForProject(project:ProjectData,customTemplates:TaskTemplate[]=[]){
  const type=project.projectType??'房建工程'
  const builtIn=TEMPLATE_PACKS[type],custom=customTemplates.filter(t=>t.projectType==='通用'||t.projectType===type)
  if(!custom.length)return [...builtIn]
  let finalIndex=-1
  builtIn.forEach((task,index)=>{if(task.isMilestone&&task.isLocked)finalIndex=index})
  if(finalIndex<0)return [...builtIn,...custom]
  const final=builtIn[finalIndex],byName=new Map(custom.map(t=>[t.name,t]))
  const afterFinal=(task:TaskTemplate,seen=new Set<string>()):boolean=>task.predecessorNames.some(name=>name===final.name||(!seen.has(name)&&byName.has(name)&&(seen.add(name),afterFinal(byName.get(name)!,seen))))
  const eligible=custom.filter(t=>!afterFinal(t)),referenced=new Set(eligible.flatMap(t=>t.predecessorNames))
  const terminalNames=eligible.filter(t=>!referenced.has(t.name)).map(t=>t.name)
  const linkedFinal={...final,predecessorNames:[...new Set([...final.predecessorNames,...terminalNames])]}
  return [...builtIn.slice(0,finalIndex),...custom,linkedFinal,...builtIn.slice(finalIndex+1)]
}
