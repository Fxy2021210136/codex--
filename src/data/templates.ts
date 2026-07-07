import type { ProjectData, TaskTemplate } from '../types'

const t = (id: string, phase: string, name: string, duration: number, predecessorNames: string[], extra: Partial<TaskTemplate> = {}): TaskTemplate => ({
  id, phase, name, duration, predecessorNames, discipline: phase, relationType: 'FS', lag: 0,
  compressibility: '部分可压缩', responsibleParty: '总包单位', ...extra,
})

export const BASE_TEMPLATES: TaskTemplate[] = [
  t('PL-001','前期准备','场地移交',1,[],{isMilestone:true,isLocked:true,compressibility:'不可压缩',riskNote:'场地移交边界不清会造成临建和土方启动反复。'}),
  t('PL-002','前期准备','图纸会审',7,['场地移交'],{discipline:'技术管理',responsibleParty:'总包技术部'}),
  t('PL-003','前期准备','施工组织设计审批',10,['图纸会审'],{discipline:'技术管理',compressibility:'不可压缩'}),
  t('PL-004','前期准备','临建及场地布置',15,['场地移交'],{relationType:'SS',responsibleParty:'总包生产部'}),
  t('PL-005','桩基工程','桩基施工',45,['施工组织设计审批','临建及场地布置'],{discipline:'地基基础',riskNote:'压缩需增加设备班组，并关注检测等待期。'}),
  t('PL-006','桩基工程','桩基检测',12,['桩基施工'],{discipline:'第三方检测',compressibility:'不可压缩'}),
  t('PL-007','地基基础','基坑支护',28,['临建及场地布置'],{relationType:'SS',scope:'hasDeepFoundationPit'}),
  t('PL-008','地基基础','土方开挖',24,['桩基检测','基坑支护'],{discipline:'土方工程'}),
  t('PL-009','地基基础','基坑验槽',2,['土方开挖'],{isMilestone:true,compressibility:'不可压缩'}),
  t('PL-010','地下室结构','地下室底板结构',30,['基坑验槽'],{discipline:'土建结构'}),
  t('PL-011','地下室结构','地下室结构施工',72,['地下室底板结构'],{discipline:'土建结构'}),
  t('PL-012','地下室结构','地下室防水施工',18,['地下室结构施工'],{discipline:'防水',compressibility:'不可压缩'}),
  t('PL-013','地下室结构','地下室顶板移交',1,['地下室结构施工'],{isMilestone:true,isLocked:true}),
  t('PL-014','主体结构','主体结构施工',96,['地下室顶板移交'],{discipline:'土建结构',riskNote:'模板、钢筋、混凝土和垂直运输是主要节拍约束。'}),
  t('PL-015','主体结构','主体结构封顶',1,['主体结构施工'],{isMilestone:true,isLocked:true,compressibility:'不可压缩'}),
  t('PL-016','二次结构','砌体及二次结构',72,['主体结构施工'],{relationType:'SS',lag:24,discipline:'土建砌筑'}),
  t('PL-017','机电安装','机电预留预埋',90,['主体结构施工'],{relationType:'SS',lag:8,discipline:'机电安装'}),
  t('PL-018','机电安装','管线综合安装',95,['砌体及二次结构','机电预留预埋'],{relationType:'SS',lag:12,discipline:'机电安装'}),
  t('PL-019','外立面','幕墙深化与样板',30,['主体结构封顶'],{scope:'hasCurtainWall',discipline:'幕墙外立面'}),
  t('PL-020','外立面','外立面施工',80,['主体结构封顶','幕墙深化与样板'],{discipline:'幕墙外立面'}),
  t('PL-021','装饰装修','抹灰及基层施工',65,['砌体及二次结构'],{relationType:'SS',lag:10,discipline:'装饰装修'}),
  t('PL-022','装饰装修','精装修样板确认',15,['抹灰及基层施工'],{scope:'hasFineDecoration',compressibility:'不可压缩'}),
  t('PL-023','装饰装修','室内精装修',105,['精装修样板确认','管线综合安装'],{scope:'hasFineDecoration',discipline:'装饰装修'}),
  t('PL-024','装饰装修','普通装修及收口',70,['抹灰及基层施工','管线综合安装'],{discipline:'装饰装修'}),
  t('PL-025','室外工程','室外管网施工',45,['地下室防水施工'],{discipline:'室外配套'}),
  t('PL-026','室外工程','道路及景观施工',40,['室外管网施工','外立面施工'],{discipline:'室外配套'}),
  t('PL-033','前期准备','测量控制网建立',5,['场地移交'],{discipline:'测量工程',compressibility:'不可压缩'}),
  t('PL-034','地下室结构','塔吊基础施工',12,['地下室底板结构'],{discipline:'垂直运输',responsibleParty:'设备单位'}),
  t('PL-035','地下室结构','塔吊安装验收',7,['塔吊基础施工'],{discipline:'垂直运输',responsibleParty:'设备单位',compressibility:'不可压缩'}),
  t('PL-036','外立面','门窗深化与样板',24,['主体结构封顶'],{discipline:'门窗工程'}),
  t('PL-037','外立面','门窗材料进场',35,['门窗深化与样板'],{discipline:'采购计划',riskNote:'型材、玻璃和五金加工周期需要提前锁定。'}),
  t('PL-038','外立面','门窗安装',55,['砌体及二次结构','门窗材料进场'],{relationType:'SS',lag:8,discipline:'门窗工程'}),
  t('PL-039','机电安装','电梯深化与采购',90,['主体结构施工'],{relationType:'SS',lag:18,discipline:'采购计划',riskNote:'电梯是长周期设备，应在井道条件完全形成前完成采购。'}),
  t('PL-040','机电安装','电梯安装与调试',55,['主体结构封顶','电梯深化与采购'],{discipline:'电梯工程',compressibility:'部分可压缩'}),
  t('PL-041','机电安装','消防系统安装',65,['管线综合安装'],{relationType:'SS',lag:10,discipline:'消防工程'}),
  t('PL-042','机电安装','配电箱及主要设备到货',50,['机电预留预埋'],{relationType:'SS',lag:12,discipline:'采购计划'}),
  t('PL-043','装饰装修','厨卫防水与闭水试验',18,['抹灰及基层施工'],{relationType:'SS',lag:12,discipline:'防水',compressibility:'不可压缩'}),
  t('PL-027','机电调试','单机调试',22,['管线综合安装','室内精装修','普通装修及收口'],{discipline:'机电调试',compressibility:'不可压缩'}),
  t('PL-028','机电调试','联合调试',18,['单机调试'],{discipline:'机电调试',compressibility:'不可压缩'}),
  t('PL-029','竣工验收','消防专项验收',15,['联合调试'],{discipline:'验收移交',compressibility:'不可压缩'}),
  t('PL-030','竣工验收','分户验收与整改',28,['室内精装修','普通装修及收口'],{discipline:'验收移交'}),
  t('PL-031','竣工验收','竣工资料闭合',20,['联合调试'],{discipline:'资料管理',compressibility:'不可压缩'}),
  t('PL-044','竣工验收','规划与档案预验收',15,['竣工资料闭合','道路及景观施工'],{discipline:'验收移交',compressibility:'不可压缩'}),
  t('PL-032','竣工验收','竣工验收',1,['消防专项验收','分户验收与整改','竣工资料闭合','规划与档案预验收','道路及景观施工'],{isMilestone:true,isLocked:true,discipline:'验收移交',compressibility:'不可压缩'}),
]

export const DEFAULT_PROJECT: ProjectData = {
  projectType:'房建工程',projectName:'长宁住宅项目施工总进度计划', location:'上海市长宁区', buildingCount:4,
  floorsAboveGround:18, floorsUnderground:1, grossFloorArea:82000, structureType:'剪力墙结构',
  foundationType:'桩基础', startDate:'2026-07-01', plannedCompletionDate:'2027-12-22',
  standardFloorCycleDays:6, constructionSectionCount:4, towerCraneCount:2, planLevel:'工序计划',
  hasDeepFoundationPit:true, hasFineDecoration:true, hasCurtainWall:false, isPrefabricated:false,
  calendar:{weekendWork:true,holidayWork:false,nightWork:false,shutdownPeriods:[{name:'春节停工',startDate:'2027-02-01',endDate:'2027-02-20'}],weatherSensitivePeriods:[{name:'华东梅雨季',startDate:'2027-06-10',endDate:'2027-07-10',affectedPhases:['外立面','室外工程','防水']}]},
}

export const PHASE_COLORS: Record<string,string> = {
  前期准备:'#10b981', 桩基工程:'#0ea5e9', 地基基础:'#14b8a6', 地下室结构:'#0f766e',
  主体结构:'#f43f5e', 二次结构:'#8b5cf6', 机电安装:'#06b6d4', 外立面:'#f59e0b',
  装饰装修:'#f97316', 室外工程:'#84cc16', 机电调试:'#3b82f6', 竣工验收:'#64748b',
}
