import test from 'node:test'
import assert from 'node:assert/strict'
import { auditCandidatePlan, projectConfidence, suggestTemplatesLocally, validateProject } from '../src/engine/agentPipeline.ts'
import { DEFAULT_PROJECT } from '../src/data/templates.ts'
import { defaultDimensions, templatesForProject } from '../src/data/projectTemplates.ts'

test('项目校验阻止缺少空间维度和倒置日期',()=>{
  const invalid={...DEFAULT_PROJECT,projectName:'',startDate:'2027-01-01',plannedCompletionDate:'2026-01-01',spatialDimensions:[]}
  const errors=validateProject(invalid)
  assert.ok(errors.some(x=>x.includes('项目名称')))
  assert.ok(errors.some(x=>x.includes('竣工日期')))
  assert.ok(errors.some(x=>x.includes('空间维度')))
})

test('候选模板根据项目类型和描述给出可确认工序',()=>{
  const project={...DEFAULT_PROJECT,projectType:'道路工程' as const,spatialDimensions:defaultDimensions('道路工程',DEFAULT_PROJECT)}
  const existing=templatesForProject(project)
  const candidates=suggestTemplatesLocally(project,'道路保通施工，需要进行交通导改和软基换填',existing)
  assert.equal(candidates.length,2)
  assert.ok(candidates.find(x=>x.name==='交通导改实施')!.confidence>=90)
  assert.equal(candidates.every(x=>x.isCustom&&x.projectType==='道路工程'),true)
})

test('Agent 试排会将候选工序纳入任务和风险审查',()=>{
  const project={...DEFAULT_PROJECT,projectType:'市政管网' as const,spatialDimensions:defaultDimensions('市政管网',DEFAULT_PROJECT)}
  const base=templatesForProject(project),candidates=suggestTemplatesLocally(project,'给水管网需要冲洗消毒与水质检测',base)
  const baseAudit=auditCandidatePlan(project,base),candidateAudit=auditCandidatePlan(project,[...base,...candidates])
  assert.ok(candidateAudit.taskCount>baseAudit.taskCount)
  assert.ok(candidateAudit.finishDate)
  assert.ok(candidateAudit.pendingConditions>0)
})

test('输入置信度随关键字段和描述完整度提高',()=>{
  const complete={...DEFAULT_PROJECT,spatialDimensions:defaultDimensions('房建工程',DEFAULT_PROJECT)}
  assert.equal(projectConfidence(complete,'四栋十八层住宅项目，目标工期540天'),100)
  assert.ok(projectConfidence({...complete,location:''},'短')<100)
})
