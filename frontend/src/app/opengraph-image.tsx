import { ImageResponse } from 'next/og'
import { BrandMark } from '@/components/brand/BrandLogo'

export const alt = 'Latexy — Your experience. A stronger résumé.'
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

export default function OpenGraphImage() {
  return new ImageResponse(
    <div style={{ display: 'flex', width: '100%', height: '100%', background: '#FBFAF6', color: '#1B1815', padding: '64px', flexDirection: 'column', fontFamily: 'sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: 32, fontWeight: 700 }}><BrandMark width={52} height={52} style={{ color: '#1C3F6E' }} />Latexy</div>
      <div style={{ display: 'flex', flexDirection: 'column', marginTop: 58, fontSize: 76, fontWeight: 700, letterSpacing: '-3px', lineHeight: 1.08 }}><span>Your experience.</span><span style={{ color: '#1C3F6E' }}>A stronger résumé.</span></div>
      <div style={{ display: 'flex', marginTop: 36, fontSize: 28, color: '#4A443C' }}>Build visually. Tailor thoughtfully. Send with confidence.</div>
      <div style={{ display: 'flex', marginTop: 'auto', paddingTop: 28, borderTop: '1px solid #D8D2C4', justifyContent: 'space-between', fontSize: 23, color: '#4A443C' }}><span>Visual editing · AI suggestions · PDF export</span><span>latexy.xyz</span></div>
    </div>,
    size,
  )
}
