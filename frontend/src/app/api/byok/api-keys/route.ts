import { NextRequest, NextResponse } from 'next/server';

import { BACKEND_URL, authHeaders, forwardError } from '../_forward';

export async function GET(request: NextRequest) {
  try {
    const response = await fetch(`${BACKEND_URL}/byok/api-keys`, {
      method: 'GET',
      headers: authHeaders(request),
    });

    if (!response.ok) {
      return forwardError(response, 'Error fetching API keys', {
        total_count: 0,
        api_keys: [],
      });
    }

    const data = await response.json();

    // The backend already returns { success, api_keys: [...], total_count }.
    // Older code assumed a bare array (data.length / api_keys: data), which put
    // the whole object into api_keys and crashed the client's .map(). Normalise
    // defensively for both shapes.
    const list = Array.isArray(data)
      ? data
      : (Array.isArray(data?.api_keys) ? data.api_keys : []);

    return NextResponse.json({
      success: true,
      total_count: list.length,
      api_keys: list,
    });
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
      headers: authHeaders(request),
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      return forwardError(response, 'Error adding API key');
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
