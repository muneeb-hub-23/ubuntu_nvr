'use client';
import {useEffect,useState} from 'react';
import {Camera,LockKeyhole,LogOut} from 'lucide-react';

export default function LoginPage(){
 const [username,setUsername]=useState('admin');
 const [password,setPassword]=useState('');
 const [current,setCurrent]=useState('');
 const [next,setNext]=useState('');
 const [confirm,setConfirm]=useState('');
 const [user,setUser]=useState<{username:string;must_change:boolean}|null>(null);
 const [ready,setReady]=useState(false);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 useEffect(()=>{fetch('/api/auth/me').then(async r=>{if(r.ok)setUser(await r.json())}).catch(()=>setError('Recorder unavailable')).finally(()=>setReady(true))},[]);
 async function submit(e:React.FormEvent){
  e.preventDefault();setError('');
  if(user && next!==confirm){setError('New passwords do not match');return}
  setBusy(true);
  try {
   const r=await fetch(user?'/api/auth/password':'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(user?{current_password:current,new_password:next}:{username,password})});
   const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Check your password (at least 10 characters).');
   if(data.must_change){setUser(data);setCurrent(password);setPassword('')}else window.location.assign('/');
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 async function logout(){await fetch('/api/auth/logout',{method:'POST'});setUser(null);setPassword('');setCurrent('');setNext('');setConfirm('')}
 return <main className="auth-page"><section className="auth-card"><a className="brand" href="/"><div className="brand-icon"><Camera size={24}/></div>luma<span>NVR</span></a><div className="section-icon"><LockKeyhole size={23}/></div><h1>{user?'Secure your account':'Welcome back'}</h1><p>{user?.must_change?'Choose a new password to finish setting up your recorder.':user?'Update your administrator password.':'Sign in to your local recorder.'}</p>{!ready?<p>Connecting to recorder…</p>:<form onSubmit={submit}>{!user?<><label>Username<input autoFocus required autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)}/></label><label>Password<input type="password" required autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)}/></label></>:<><label>Current password<input type="password" required autoComplete="current-password" value={current} onChange={e=>setCurrent(e.target.value)}/></label><label>New password<input type="password" required minLength={10} maxLength={500} autoComplete="new-password" value={next} onChange={e=>setNext(e.target.value)}/><small>Use at least 10 characters.</small></label><label>Confirm new password<input type="password" required minLength={10} autoComplete="new-password" value={confirm} onChange={e=>setConfirm(e.target.value)}/></label></>}{error&&<div role="alert" className="alert">{error}</div>}<button className="primary" disabled={busy}>{busy?'Please wait…':user?'Save password':'Sign in'}</button>{!user&&<p className="auth-hint">First installation? Sign in with <strong>admin / admin</strong>.</p>}</form>}{user&&<div className="auth-links">{!user.must_change&&<a href="/">Back to workspace</a>}<button className="secondary" onClick={logout}><LogOut size={14}/> Sign out</button></div>}</section></main>
}
