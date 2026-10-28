import {NextRequest} from 'next/server';
export const dynamic='force-dynamic';
async function handle(req: NextRequest, context: {params: Promise<{path:string[]}>}) {
 const {path}=await context.params;
 if(path.some(p=>p==='..'||p==='.'||p.includes('/')||p.includes('\\'))) return new Response('Invalid path',{status:400});
 const headers=new Headers({'x-nvr-key':process.env.NVR_SECRET || ''});
 if(req.headers.has('content-type')) headers.set('content-type',req.headers.get('content-type')!);
 try {
 const result=await fetch(`${process.env.BACKEND_URL || 'http://localhost:8000'}/${path.map(encodeURIComponent).join('/')}${req.nextUrl.search}`,{method:req.method, headers, body:['GET','HEAD'].includes(req.method)?undefined:await req.arrayBuffer(),cache:'no-store',signal:AbortSignal.timeout(30000)});
 const output=new Headers({'Cache-Control':'no-store'});
 for(const key of ['content-type','content-disposition']) if(result.headers.has(key)) output.set(key,result.headers.get(key)!);
 return new Response(result.body,{status:result.status,headers:output});
 } catch {return Response.json({detail:'Recorder backend unavailable'},{status:502})}
}
export {handle as GET,handle as POST,handle as PUT,handle as DELETE};
