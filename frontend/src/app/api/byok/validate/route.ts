import { NextRequest, NextResponse } from 'next/server';

import { BACKEND_URL, authHeaders } from '../_forward';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    
    const response = await fetch(`${BACKEND_URL}/byok/validate`, {
      method: 'POST',
      headers: authHeaders(request),
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error validating API key:', error);
    return NextResponse.json(
      { 
        success: false, 
        message: 'Failed to validate API key',
        error: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    );
  }
}
