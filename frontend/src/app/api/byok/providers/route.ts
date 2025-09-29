import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

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
    
    // Transform the data to match frontend expectations
    const transformedData = {
      success: true,
      total_count: Object.keys(data).length,
      providers: data
    };

    return NextResponse.json(transformedData);
  } catch (error) {
    console.error('Error fetching providers:', error);
    return NextResponse.json(
      { 
        success: false, 
        error: 'Failed to fetch providers',
        total_count: 0,
        providers: {}
      },
      { status: 500 }
    );
  }
}
