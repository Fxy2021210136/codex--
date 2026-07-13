import { useEffect, useState } from 'react'
import { loadAdminOverview, loadReadinessStatus } from '../api'
import type { AdminOverview, ReadinessStatus } from '../api'

function Metric({label,value}:{label:string,value:string|number}){return <div className="metric"><span>{label}</span><strong>{value}</strong></div>}

function AdminList({title,empty,items}:{title:string;empty:string;items:{key:string;label:string;meta:string}[]}){
  return <div className="admin-recent"><b>{title}</b>{items.length?items.map(item=><p key={item.key}><span>{item.label}</span><small>{item.meta}</small></p>):<p><span>{empty}</span><small>-</small></p>}</div>
}

export function ReadinessPanel(){
  const [status,setStatus]=useState<ReadinessStatus|null>(null),[adminToken,setAdminToken]=useState(''),[loading,setLoading]=useState(false),[message,setMessage]=useState('上线检查需要本机管理员权限或 ADMIN_TOKEN。')
  const refresh=async()=>{setLoading(true);try{const data=await loadReadinessStatus(adminToken.trim()||undefined);setStatus(data);setMessage(data.ready?`核心检查通过，${data.warningCount} 项建议优化。`:'发现必须修复的问题，请先处理红色项目。')}catch(e){setStatus(null);setMessage(e instanceof Error?e.message:'上线检查失败')}finally{setLoading(false)}}
  useEffect(()=>{refresh()},[])
  return <div className={`readiness-panel ${status?.ready?'ok':'warning'}`}><div className="admin-overview-head"><div><b>上线健康检查</b><p>{message}</p></div><div className="admin-token"><input type="password" value={adminToken} onChange={e=>setAdminToken(e.target.value)} placeholder="ADMIN_TOKEN（本机可留空）"/><button className="btn" onClick={refresh} disabled={loading}>{loading?'检查中…':'重新检查'}</button></div></div>{status&&<div className="readiness-list">{status.checks.map(item=><article className={item.level} key={item.key}><strong>{item.level==='ok'?'✓':item.level==='warning'?'!':'×'}</strong><span><b>{item.label}{item.required?' · 必需':' · 建议'}</b><small>{item.detail}</small></span></article>)}</div>}</div>
}

export function AdminOverviewPanel(){
  const [overview,setOverview]=useState<AdminOverview|null>(null),[adminToken,setAdminToken]=useState(''),[loading,setLoading]=useState(false),[message,setMessage]=useState('管理员概览需要本机管理员权限或 ADMIN_TOKEN。')
  const refresh=async()=>{setLoading(true);try{const data=await loadAdminOverview(adminToken.trim()||undefined);setOverview(data);setMessage(`已更新：${new Date(data.generatedAt).toLocaleString('zh-CN')}`)}catch(e){setOverview(null);setMessage(e instanceof Error?e.message:'运营概览加载失败')}finally{setLoading(false)}}
  useEffect(()=>{refresh()},[])
  const size=overview?`${Math.max(1,Math.round(overview.storage.sizeBytes/1024))} KB`:'-'
  return <div className="admin-overview">
    <div className="admin-overview-head"><div><b>运营概览</b><p>{message}</p></div><div className="admin-token"><input type="password" value={adminToken} onChange={e=>setAdminToken(e.target.value)} placeholder="ADMIN_TOKEN（本机可留空）"/><button className="btn" onClick={refresh} disabled={loading}>{loading?'刷新中…':'刷新'}</button></div></div>
    {overview&&<>
      <div className="summary-cards"><Metric label="注册用户" value={overview.counts.users}/><Metric label="项目总数" value={overview.counts.projects}/><Metric label="今日 AI" value={`${overview.aiUsage.todaySuccess}/${overview.aiUsage.todayTotal}`}/><Metric label="自定义模板" value={overview.counts.customTemplates}/></div>
      <div className="admin-storage"><span><b>{overview.storage.engine.toUpperCase()}</b>{overview.storage.label}</span><span>数据库大小：{size}</span><span>项目上限：{overview.limits.projectLimitPerOwner} / AI 日上限：{overview.limits.aiDailyLimitPerOwner}</span><span>AI：{overview.integrations.aiConfigured?'已配置':'未配置'} · Codex：{overview.integrations.codexReady?'可用':'未开放'}</span></div>
      <div className="admin-grid">
        <AdminList title="最近用户" empty="暂无注册用户" items={overview.recentUsers.map(item=>({key:item.id,label:`${item.name||item.email} · ${item.role==='admin'?'管理员':'普通用户'}`,meta:item.createdAt?new Date(item.createdAt).toLocaleString('zh-CN'):'-' }))}/>
        <AdminList title="最近项目" empty="暂无服务端项目" items={overview.recentProjects.map(item=>({key:`${item.owner}:${item.id}`,label:item.name||item.id,meta:item.updatedAt?new Date(item.updatedAt).toLocaleString('zh-CN'):'-' }))}/>
        <AdminList title="最近模板库" empty="暂无自定义模板" items={overview.recentTemplates.map(item=>({key:item.owner,label:`${item.owner} · ${item.count} 项模板`,meta:item.updatedAt?new Date(item.updatedAt).toLocaleString('zh-CN'):'-' }))}/>
        <AdminList title="最近 AI 调用" empty="暂无 AI 调用记录" items={overview.aiUsage.recent.map((item,index)=>({key:`${item.createdAt}:${index}`,label:`${item.success?'成功':'失败'} · ${item.provider}/${item.model}`,meta:`${item.durationMs}ms · ${item.status}${item.errorType?` · ${item.errorType}`:''}`}))}/>
      </div>
    </>}
  </div>
}
