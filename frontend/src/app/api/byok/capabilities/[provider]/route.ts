import { NextRequest, NextResponse } from 'next/server';

import { BACKEND_URL, authHeaders } from '../../_forward';

export async function GET(
  request: NextRequest,
  { params }: { params: { provider: string } }
) {
  try {
    const { provider } = params;
    
    const response = await fetch(`${BACKEND_URL}/byok/capabilities/${provider}`, {
      method: 'GET',
      headers: authHeaders(request),
    });

    if (!response.ok) {
      if (response.status === 404) {
        return NextResponse.json(
          { success: false, error: `Provider '${provider}' not found` },
          { status: 404 }
        );
      }
      throw new Error(`Backend responded with ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json({
      success: true,
      ...data
    });
  } catch (error) {
    console.error('Error fetching provider capabilities:', error);
    return NextResponse.json(
      { 
        success: false, 
        error: 'Failed to fetch provider capabilities'
      },
      { status: 500 }
    );
  }
}
