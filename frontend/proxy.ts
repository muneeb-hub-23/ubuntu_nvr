import {NextRequest, NextResponse} from 'next/server';
import {timingSafeEqual} from 'node:crypto';
function same(a: string, b: string) {const x=Buffer.from(a); const y=Buffer.from(b); return x.length===y.length && timingSafeEqual(x,y)}
export function proxy(req: NextRequest) {
  const user=process.env.NVR_USER, password=process.env.NVR_PASSWORD;
  if(!user || !password) return new NextResponse('Configure NVR_USER and NVR_PASSWORD before starting.',{status:503});
  const header=req.headers.get('authorization') || '';
  let decoded=''; try {decoded=Buffer.from(header.startsWith('Basic ')?header.slice(6):'', 'base64').toString()} catch {}
  if(!same(decoded, `${user}:${password}`)) return new NextResponse('Sign in to Luma NVR',{status:401,headers:{'WWW-Authenticate':'Basic realm="Luma NVR", charset="UTF-8"','Cache-Control':'no-store'}});
  if(['POST','PUT','DELETE'].includes(req.method)) {
    const origin=req.headers.get('origin');
    if(req.headers.get('sec-fetch-site')==='cross-site' || (origin && new URL(origin).host!==req.headers.get('host'))) return new NextResponse('Forbidden',{status:403});
  }
  return NextResponse.next();
}
export const config={matcher:['/((?!_next/static|_next/image|favicon.ico).*)']};
