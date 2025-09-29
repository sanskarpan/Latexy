import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  try {
    const response = await fetch(`${BACKEND_URL}/byok/api-keys`, {
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
      total_count: data.length || 0,
      api_keys: data || []
    };

    return NextResponse.json(transformedData);
  } catch (error) {
    console.error('Error fetching API keys:', error);
    return NextResponse.json(
      { 
        success: false, 
        error: 'Failed to fetch API keys',
        total_count: 0,
        api_keys: []
      },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    
    const response = await fetch(`${BACKEND_URL}/byok/api-keys`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Backend responded with ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json({
      success: true,
      ...data
    });
  } catch (error) {
    console.error('Error adding API key:', error);
    return NextResponse.json(
      { 
        success: false, 
        error: error instanceof Error ? error.message : 'Failed to add API key'
      },
      { status: 500 }
    );
  }
}
