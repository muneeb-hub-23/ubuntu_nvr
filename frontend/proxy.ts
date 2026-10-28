import {NextRequest, NextResponse} from 'next/server';
export async function proxy(req: NextRequest) {
  if(['POST','PUT','DELETE'].includes(req.method)) {
    const origin=req.headers.get('origin');
    if(req.headers.get('sec-fetch-site')==='cross-site' || (origin && new URL(origin).host!==req.headers.get('host'))) return new NextResponse('Forbidden',{status:403});
  }
  if(req.nextUrl.pathname.startsWith('/api/') || req.nextUrl.pathname==='/login') return NextResponse.next();
  const token=req.cookies.get('nvr_session')?.value;
  if(token) {
    try {
      const response=await fetch(`${process.env.BACKEND_URL || 'http://localhost:8000'}/auth/me`,{headers:{'x-nvr-key':process.env.NVR_SECRET || '', 'x-nvr-session':token}, cache:'no-store', signal:AbortSignal.timeout(5000)});
      if(response.ok && !(await response.json()).must_change) return NextResponse.next();
    } catch {return new NextResponse('Recorder unavailable. Please try again shortly.',{status:503})}
  }
  return NextResponse.redirect(new URL('/login',req.url));
}
export const config={matcher:['/((?!_next/static|_next/image|favicon.ico).*)']};
