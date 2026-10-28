import {NextRequest,NextResponse} from 'next/server';
export const dynamic='force-dynamic';
async function handle(req: NextRequest, context: {params: Promise<{path:string[]}>}) {
 const {path}=await context.params;
 if(path.some(p=>p==='..'||p==='.'||p.includes('/')||p.includes('\\'))) return new Response('Invalid path',{status:400});
 const headers=new Headers({'x-nvr-key':process.env.NVR_SECRET || ''});
 headers.set('x-nvr-session',req.cookies.get('nvr_session')?.value || '');
 if(req.headers.has('content-type')) headers.set('content-type',req.headers.get('content-type')!);
 try {
 const result=await fetch(`${process.env.BACKEND_URL || 'http://localhost:8000'}/${path.map(encodeURIComponent).join('/')}${req.nextUrl.search}`,{method:req.method, headers, body:['GET','HEAD'].includes(req.method)?undefined:await req.arrayBuffer(),cache:'no-store',signal:AbortSignal.timeout(30000)});
 const output=new Headers({'Cache-Control':'no-store'});
 if(path[0]==='auth' && ['login','password'].includes(path[1]) && result.ok) {
   const {token,...user}=await result.json();
   const response=NextResponse.json(user,{headers:output});
   response.cookies.set('nvr_session',token,{httpOnly:true,sameSite:'strict',secure:process.env.COOKIE_SECURE==='true',maxAge:43200,path:'/'});
   return response;
 }
 if(path[0]==='auth' && path[1]==='logout') {
   const response=NextResponse.json({ok:true},{headers:output});
   response.cookies.set('nvr_session','',{httpOnly:true,sameSite:'strict',maxAge:0,path:'/'});
   return response;
 }
 for(const key of ['content-type','content-disposition']) if(result.headers.has(key)) output.set(key,result.headers.get(key)!);
 return new Response(result.body,{status:result.status,headers:output});
 } catch {return Response.json({detail:'Recorder backend unavailable'},{status:502})}
}
export {handle as GET,handle as POST,handle as PUT,handle as DELETE};
