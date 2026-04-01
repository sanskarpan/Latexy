import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8030';

export async function GET(request: NextRequest) {
  try {
    const response = await fetch(`${BACKEND_URL}/byok/providers`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}`);
    }

    const data = await response.json();
    // Backend already returns { success, providers: [...], total_count } — pass through
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching providers:', error);
    return NextResponse.json(
      {
        success: false,
        error: 'Failed to fetch providers',
        total_count: 0,
        providers: []
      },
      { status: 500 }
    );
  }
}
