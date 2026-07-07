import test from 'node:test'
import assert from 'node:assert/strict'
import { buildProjectWorkbook } from '../src/excel.ts'
import { BASE_TEMPLATES, DEFAULT_PROJECT } from '../src/data/templates.ts'
import { generateSchedule } from '../src/engine/schedule.ts'

test('Excel 工作簿包含完整业务工作表和偏差公式',async()=>{
  const tasks=generateSchedule(DEFAULT_PROJECT,BASE_TEMPLATES)
  const workbook=await buildProjectWorkbook(DEFAULT_PROJECT,tasks,[])
  assert.deepEqual(workbook.SheetNames,['项目概览','WBS计划','资源负荷','风险审查','计划基准'])
  assert.equal(workbook.Sheets['WBS计划']['P2'].f,'IF(O2="","",MAX(0,O2-M2))')
  assert.equal(workbook.Sheets['项目概览']['B2'].v,DEFAULT_PROJECT.projectName)
  assert.ok(workbook.Sheets['资源负荷']['!ref'])
  const XLSX=await import('xlsx')
  const binary=XLSX.write(workbook,{bookType:'xlsx',type:'buffer'})
  const reopened=XLSX.read(binary,{type:'buffer',cellDates:true})
  assert.deepEqual(reopened.SheetNames,workbook.SheetNames)
  assert.equal(reopened.Sheets['WBS计划']['P2'].f,'IF(O2="","",MAX(0,O2-M2))')
})
