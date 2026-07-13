import { type FormEvent, useEffect, useState } from 'react'
import { adminLoginAccount, bindAccountPhone, changeAccountPassword, deleteAccountData, exportAccountData, loadIntegrationStatus, loginAccount, loginWithPhoneCode, logoutAccount, registerAccount, requestPhoneCode } from '../api'
import type { AuthStatus } from '../api'

type AuthMode='login'|'register'|'admin'|'phone'

export function AuthDialog({open,auth,onClose,onChange}:{open:boolean;auth:AuthStatus;onClose:()=>void;onChange:(next:AuthStatus)=>void}){
  const [phoneAuthEnabled,setPhoneAuthEnabled]=useState(import.meta.env.VITE_PUBLIC_DEPLOYMENT!=='true')
  const [mode,setMode]=useState<AuthMode>('login')
  const [email,setEmail]=useState(''),[password,setPassword]=useState(''),[name,setName]=useState('')
  const [busy,setBusy]=useState(false),[message,setMessage]=useState('')
  const [currentPassword,setCurrentPassword]=useState(''),[newPassword,setNewPassword]=useState('')
  const [phone,setPhone]=useState(''),[phoneCode,setPhoneCode]=useState(''),[phoneHint,setPhoneHint]=useState('')

  useEffect(()=>{if(open){setMessage('');setPassword('');if(!auth.authenticated)setMode('login')}},[open,auth.authenticated])
  useEffect(()=>{if(open)loadIntegrationStatus().then(status=>setPhoneAuthEnabled(status.phoneAuth.enabled)).catch(()=>{})},[open])
  if(!open)return null

  const submit=async(event:FormEvent)=>{
    event.preventDefault()
    setBusy(true);setMessage('')
    try{
      const next=mode==='register'
        ? await registerAccount({email,password,name})
        : mode==='admin'
          ? await adminLoginAccount({email,password})
          : mode==='phone'&&phoneAuthEnabled
            ? await loginWithPhoneCode({phone,code:phoneCode})
            : await loginAccount({email,password})
      onChange(next);onClose()
    }catch(error){setMessage(error instanceof Error?error.message:'登录失败')}
    finally{setBusy(false)}
  }
  const logout=async()=>{setBusy(true);try{onChange(await logoutAccount());onClose()}catch(error){setMessage(error instanceof Error?error.message:'退出失败')}finally{setBusy(false)}}
  const exportMine=async()=>{
    setBusy(true);setMessage('')
    try{
      const data=await exportAccountData()
      const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'})
      const url=URL.createObjectURL(blob)
      const link=document.createElement('a')
      link.href=url;link.download=`schedule-ai-account-${new Date().toISOString().slice(0,10)}.json`;link.click()
      URL.revokeObjectURL(url)
      setMessage(`已导出 ${data.projects.length} 个项目和 ${data.templates.length} 个模板。`)
    }catch(error){setMessage(error instanceof Error?error.message:'导出失败')}
    finally{setBusy(false)}
  }
  const changePassword=async()=>{
    setBusy(true);setMessage('')
    try{
      const next=await changeAccountPassword({currentPassword,newPassword})
      onChange(next);setCurrentPassword('');setNewPassword('');setMessage('密码已修改，已重新签发当前登录会话。')
    }catch(error){setMessage(error instanceof Error?error.message:'修改密码失败')}
    finally{setBusy(false)}
  }
  const sendPhoneCode=async()=>{
    setBusy(true);setMessage('');setPhoneHint('')
    try{
      const result=await requestPhoneCode({phone})
      setPhone(result.phone);setPhoneHint(result.devCode?`本地测试验证码：${result.devCode}`:'验证码已发送，请查看短信。')
    }catch(error){setMessage(error instanceof Error?error.message:'发送验证码失败')}
    finally{setBusy(false)}
  }
  const bindPhone=async()=>{
    setBusy(true);setMessage('')
    try{
      const next=await bindAccountPhone({phone,code:phoneCode})
      onChange(next);setPhoneCode('');setPhoneHint('');setMessage('手机号已绑定，后续可使用验证码登录。')
    }catch(error){setMessage(error instanceof Error?error.message:'绑定手机号失败')}
    finally{setBusy(false)}
  }
  const deleteMine=async()=>{
    if(!window.confirm('确定删除当前账号、项目、模板和会话吗？此操作不可恢复。建议先导出账号数据。'))return
    setBusy(true);setMessage('')
    try{
      const result=await deleteAccountData()
      onChange({authenticated:false,user:null});setMessage(`账号已删除，同时删除 ${result.projects} 个项目、${result.templates} 组模板。`)
    }catch(error){setMessage(error instanceof Error?error.message:'删除账号失败')}
    finally{setBusy(false)}
  }

  return <div className="modal-backdrop auth-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget)onClose()}}>
    <section className="auth-dialog">
      <header><div><small>账号与项目隔离</small><h2>{auth.authenticated?'当前账号':mode==='register'?'注册账号':mode==='admin'?'管理员登录':mode==='phone'?'验证码登录':'登录账号'}</h2></div><button onClick={onClose}>×</button></header>
      {auth.authenticated
        ? <div className="auth-profile">
            <b>{auth.user?.name}</b>
            <p>{auth.user?.email}{auth.user?.role==='admin'?' · 管理员':''}{auth.user?.phone?` · ${auth.user.phone}`:''}</p>
            <small>项目保存时会归属到这个账号；你可以导出自己的账号数据，也可以删除账号及其服务端数据。</small>
            <div className="password-box">
              <b>修改密码</b>
              <input type="password" value={currentPassword} onChange={event=>setCurrentPassword(event.target.value)} placeholder="当前密码"/>
              <input type="password" value={newPassword} onChange={event=>setNewPassword(event.target.value)} placeholder="新密码，至少 8 位"/>
              <button className="btn" disabled={busy||!currentPassword||newPassword.length<8} onClick={changePassword}>修改密码</button>
            </div>
            {phoneAuthEnabled
              ? <div className="password-box">
                  <b>手机号绑定</b>
                  <small>{auth.user?.phone?`已绑定：${auth.user.phone}`:'绑定后可用验证码登录。当前本地测试会直接显示验证码。'}</small>
                  <input value={phone} onChange={event=>setPhone(event.target.value)} placeholder="手机号，例如 13800138000"/>
                  <div className="button-row"><input value={phoneCode} onChange={event=>setPhoneCode(event.target.value)} placeholder="6 位验证码"/><button className="btn" disabled={busy||phone.length<11} onClick={sendPhoneCode}>获取验证码</button></div>
                  {phoneHint&&<small>{phoneHint}</small>}
                  <button className="btn" disabled={busy||phone.length<11||phoneCode.length<4} onClick={bindPhone}>绑定手机号</button>
                </div>
              : <div className="password-box"><b>手机号绑定</b><small>公网验证码登录暂未开放，请使用邮箱密码登录。</small></div>}
            <div className="button-row"><button className="btn" onClick={onClose}>继续使用</button><button className="btn" disabled={busy} onClick={exportMine}>{busy?'处理中…':'导出我的数据'}</button><button className="btn danger" disabled={busy} onClick={logout}>{busy?'处理中…':'退出登录'}</button></div>
            <button className="auth-delete" disabled={busy} onClick={deleteMine}>删除账号与服务端数据</button>
            {message&&<p className="auth-message">{message}</p>}
          </div>
        : <form onSubmit={submit}>
            <p>登录后，服务端项目库会按账号隔离。本地管理员可用默认密码 177099；公网部署需配置 ADMIN_DEFAULT_PASSWORD。{phoneAuthEnabled?'手机号需先在账号内绑定。':'公网验证码登录暂未开放。'}</p>
            <div className="button-row">
              <button type="button" className={`btn ${mode==='login'?'primary':''}`} onClick={()=>setMode('login')}>邮箱登录</button>
              <button type="button" className={`btn ${mode==='register'?'primary':''}`} onClick={()=>setMode('register')}>注册</button>
              <button type="button" className={`btn ${mode==='admin'?'primary':''}`} onClick={()=>setMode('admin')}>管理员</button>
              {phoneAuthEnabled&&<button type="button" className={`btn ${mode==='phone'?'primary':''}`} onClick={()=>setMode('phone')}>验证码</button>}
            </div>
            {mode==='register'&&<label>姓名 / 昵称<input value={name} onChange={event=>setName(event.target.value)} placeholder="例如：项目经理"/></label>}
            {mode==='phone'&&phoneAuthEnabled
              ? <><label>手机号<input value={phone} onChange={event=>setPhone(event.target.value)} placeholder="13800138000" required/></label><div className="button-row"><label>验证码<input value={phoneCode} onChange={event=>setPhoneCode(event.target.value)} placeholder="6 位验证码" required/></label><button type="button" className="btn" disabled={busy||phone.length<11} onClick={sendPhoneCode}>获取验证码</button></div>{phoneHint&&<p className="status-note">{phoneHint}</p>}</>
              : <><label>邮箱<input type="email" value={email} onChange={event=>setEmail(event.target.value)} placeholder="you@example.com" required/></label><label>{mode==='admin'?'管理员密码':'密码'}<input type="password" value={password} onChange={event=>setPassword(event.target.value)} placeholder={mode==='admin'?'本地默认 177099；公网需配置':'至少 8 位'} minLength={mode==='admin'?1:8} required/></label></>}
            {message&&<p className="auth-message">{message}</p>}
            <button className="btn primary block" disabled={busy}>{busy?'处理中…':mode==='register'?'注册并登录':mode==='admin'?'管理员登录':mode==='phone'?'验证码登录':'登录'}</button>
          </form>}
    </section>
  </div>
}
