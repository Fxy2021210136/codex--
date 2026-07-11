import type { PlanBaseline, ProjectData, Task, TaskTemplate } from './types'
import type { AiSettings } from './types'

const API_BASE=(import.meta.env.VITE_API_BASE_URL??'').replace(/\/$/,'')
export const apiUrl=(path:string)=>`${API_BASE}${path}`
const CLIENT_KEY='construction_schedule_client_id'
export const getClientId=()=>{let id=localStorage.getItem(CLIENT_KEY);if(!id){id=`web-${globalThis.crypto?.randomUUID?.()??Date.now()}`;localStorage.setItem(CLIENT_KEY,id)}return id}

export interface SavedProjectPayload {
  project: ProjectData
  tasks: Task[]
  baselines: PlanBaseline[]
  customTemplates?: TaskTemplate[]
}

export interface SavedProjectRecord extends SavedProjectPayload {
  id: string
  createdAt: string
  updatedAt: string
  projectQuota?: ProjectQuota
}

export interface ProjectSummary {
  id: string
  name: string
  location: string
  updatedAt: string
  createdAt: string
  taskCount: number
  completionDate: string
}

async function request<T>(url:string,options?:RequestInit):Promise<T>{
  const response=await fetch(apiUrl(url),{...options,credentials:'include',headers:{'Content-Type':'application/json','X-Client-Id':getClientId(),...(options?.headers??{})}})
  const data=await response.json().catch(()=>({}))
  if(!response.ok)throw new Error((data as {error?:string}).error||`服务端请求失败 (${response.status})`)
  return data as T
}

export interface AuthUser {
  id: string
  email: string
  name: string
  role?: 'user' | 'admin'
  createdAt: string
}

export interface ProjectQuota {
  limit: number
  used: number
  remaining: number | null
  exempt: boolean
}

export interface AuthStatus {
  authenticated: boolean
  user: AuthUser | null
  owner?: string
  projectQuota?: ProjectQuota
}

export function loadAuthStatus(){
  return request<AuthStatus>('/api/auth/me')
}

export function registerAccount(payload:{email:string;password:string;name?:string}){
  return request<AuthStatus>('/api/auth/register',{method:'POST',body:JSON.stringify(payload)})
}

export function loginAccount(payload:{email:string;password:string}){
  return request<AuthStatus>('/api/auth/login',{method:'POST',body:JSON.stringify(payload)})
}

export function logoutAccount(){
  return request<AuthStatus>('/api/auth/logout',{method:'POST'})
}

export async function listSavedProjects(){
  return (await request<{projects:ProjectSummary[]}>('/api/projects')).projects
}

export function loadSavedProject(id:string){
  return request<SavedProjectRecord>(`/api/projects/${encodeURIComponent(id)}`)
}

export function saveProjectToServer(id:string,payload:SavedProjectPayload){
  return request<SavedProjectRecord>(`/api/projects/${encodeURIComponent(id)}`,{method:'PUT',body:JSON.stringify(payload)})
}

export function deleteSavedProject(id:string){
  return request<{deleted:boolean}>(`/api/projects/${encodeURIComponent(id)}`,{method:'DELETE'})
}

export async function loadServerCustomTemplates(){
  return (await request<{templates:TaskTemplate[];updatedAt?:string}>('/api/templates')).templates
}

export async function saveServerCustomTemplates(templates:TaskTemplate[]){
  return (await request<{templates:TaskTemplate[];updatedAt:string}>('/api/templates',{method:'PUT',body:JSON.stringify({templates})})).templates
}

export interface ServerAiConfig extends AiSettings {
  configured: boolean
  maskedKey: string
  mode: 'server'
}

export async function loadServerAiConfig():Promise<ServerAiConfig>{
  const config=await request<Omit<ServerAiConfig,'mode'>>('/api/settings/ai')
  return {...config,mode:'server'}
}

export async function saveServerAiConfig(settings:Required<Pick<AiSettings,'provider'|'model'>>&{apiKey?:string}):Promise<ServerAiConfig>{
  const config=await request<Omit<ServerAiConfig,'mode'>>('/api/settings/ai',{method:'PUT',body:JSON.stringify(settings)})
  return {...config,mode:'server'}
}

export function clearServerAiConfig(){
  return request<{deleted:boolean}>('/api/settings/ai',{method:'DELETE'})
}

export interface IntegrationStatus {
  ai: {configured:boolean;provider:AiSettings['provider'];model:string;maskedKey:string}
  codex: {enabled:boolean;available:boolean;ready:boolean;model:string;sandbox:'read_only'|'workspace_write';adminOnly:boolean;runtime:'python-sdk'|'cli'|'test-runner'|'unavailable'}
}

export function loadIntegrationStatus(){
  return request<IntegrationStatus>('/api/integrations')
}

export function runCodexAnalysis(prompt:string,options:{sandbox?:'read_only'|'workspace_write';adminToken?:string}={}){
  return request<{finalResponse:string;model?:string;sandbox?:string}>('/api/codex/run',{
    method:'POST',
    headers:options.adminToken?{'X-Admin-Token':options.adminToken}:undefined,
    body:JSON.stringify({prompt,sandbox:options.sandbox??'read_only'}),
  })
}

export interface ConnectivityDiagnostics {
  ok: boolean
  checkedAt: string
  checks: {host:string;dns:boolean;tcp443:boolean;addresses:string[];error?:string}[]
}

export function loadConnectivityDiagnostics(adminToken?:string){
  return request<ConnectivityDiagnostics>('/api/diagnostics/connectivity',{headers:adminToken?{'X-Admin-Token':adminToken}:undefined})
}

export interface AdminOverview {
  generatedAt: string
  storage: {engine:'sqlite'|'json';label:string;path:string;exists:boolean;sizeBytes:number;updatedAt:string}
  counts: {users:number;projects:number;activeSessions:number;templateOwners:number;customTemplates:number}
  limits: {projectLimitPerOwner:number}
  integrations: {aiConfigured:boolean;codexReady:boolean;codexRuntime:string}
  recentProjects: {id:string;owner:string;name:string;updatedAt:string}[]
}

export function loadAdminOverview(adminToken?:string){
  return request<AdminOverview>('/api/admin/overview',{headers:adminToken?{'X-Admin-Token':adminToken}:undefined})
}
