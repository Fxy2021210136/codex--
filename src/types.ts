export type RelationType = 'FS' | 'SS' | 'FF' | 'SF'
export type TaskStatus = '未开始' | '施工中' | '实体完成' | '自检完成' | '监理验收通过' | '移交下道工序' | '资料闭合' | '暂停' | '延期'
export type ProjectType = '房建工程' | '道路工程' | '桥梁工程' | '市政管网' | '工业安装' | '自定义工程'

export interface SpatialDimension {
  id: string
  name: string
  values: string[]
}

export interface ProjectData {
  projectType: ProjectType
  projectName: string
  location: string
  buildingCount: number
  floorsAboveGround: number
  floorsUnderground: number
  grossFloorArea: number
  structureType: string
  foundationType: string
  startDate: string
  plannedCompletionDate: string
  dataDate?: string
  standardFloorCycleDays: number
  constructionSectionCount: number
  towerCraneCount: number
  resourceCapacities?: Record<string, number>
  spatialDimensions?: SpatialDimension[]
  planLevel: '总控计划' | '工序计划'
  hasDeepFoundationPit: boolean
  hasFineDecoration: boolean
  hasCurtainWall: boolean
  isPrefabricated: boolean
  calendar?: {
    weekendWork: boolean
    holidayWork: boolean
    nightWork?: boolean
    shutdownPeriods: { name: string; startDate: string; endDate: string }[]
    weatherSensitivePeriods: { name: string; startDate: string; endDate: string; affectedPhases: string[] }[]
  }
}

export interface PlanBaseline {
  id: string
  name: string
  createdAt: string
  projectName: string
  tasks: Pick<Task,'id'|'name'|'startDate'|'endDate'|'duration'>[]
}

export interface StartCondition {
  id: string
  name: string
  type: string
  status: '已满足' | '待确认' | '不满足'
  strength: '强制依赖' | '建议依赖'
}

export interface TaskDependency {
  predecessorId: string
  relationType: RelationType
  lag: number
}

export interface TaskTemplate {
  id: string
  phase: string
  name: string
  discipline: string
  duration: number
  predecessorNames: string[]
  relationType: RelationType
  lag: number
  compressibility: '可压缩' | '部分可压缩' | '不可压缩'
  responsibleParty: string
  isMilestone?: boolean
  isLocked?: boolean
  scope?: keyof Pick<ProjectData, 'hasDeepFoundationPit' | 'hasFineDecoration' | 'hasCurtainWall' | 'isPrefabricated'>
  riskNote?: string
  projectType?: ProjectType | '通用'
  expansionDimensions?: string[]
  quantityUnit?: string
  defaultQuantity?: number
  resourceDemand?: string[]
  materialNodes?: string[]
  isCustom?: boolean
  version?: number
  updatedAt?: string
}

export interface Task extends Omit<TaskTemplate, 'predecessorNames' | 'scope'> {
  wbsCode: string
  predecessors: string[]
  /** Professional edge-level logic. Legacy predecessors/relationType/lag remain for backup compatibility. */
  dependencies?: TaskDependency[]
  startDate: string
  endDate: string
  actualStartDate?: string
  actualEndDate?: string
  status: TaskStatus
  progress: number
  isCritical: boolean
  totalFloat: number
  source: '规则生成' | 'AI扩展' | '用户输入' | '手动修改'
  startConditions: StartCondition[]
  generationBasis: string
  building?: string
  floor?: string
  workArea?: string
  quantity?: number
  unit?: string
  resourceDemand?: string[]
  materialNodes?: string[]
  spacePath?: Record<string,string>
}

export interface AiSettings {
  provider: 'deepseek' | 'gemini' | 'openai'
  apiKey?: string
  model: string
  configured?: boolean
  maskedKey?: string
  mode?: 'server'
}

export interface ReviewItem {
  id: string
  level: '高' | '中' | '低'
  category: string
  title: string
  impact: string
  suggestion: string
}

export interface ResourceLoad {
  resource: string
  capacity: number
  peak: number
  peakDate: string
  activeTasks: string[]
  overloadedDays: number
}

export interface ResourceLevelingResult {
  tasks: Task[]
  shifted: { taskId: string; taskName: string; days: number }[]
  beforeConflicts: number
  afterConflicts: number
  unresolved: string[]
}
