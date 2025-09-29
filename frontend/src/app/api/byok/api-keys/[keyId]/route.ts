import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

export async function DELETE(
  request: NextRequest,
  { params }: { params: { keyId: string } }
) {
  try {
    const { keyId } = params;
    
    const response = await fetch(`${BACKEND_URL}/byok/api-keys/${keyId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      if (response.status === 404) {
        return NextResponse.json(
          { success: false, error: 'API key not found' },
          { status: 404 }
        );
      }
      throw new Error(`Backend responded with ${response.status}`);
    }

    return NextResponse.json({
      success: true,
      message: 'API key deleted successfully'
    });
  } catch (error) {
    console.error('Error deleting API key:', error);
    return NextResponse.json(
      { 
        success: false, 
        error: 'Failed to delete API key'
      },
      { status: 500 }
    );
  }
}

export async function PUT(
  request: NextRequest,
  { params }: { params: { keyId: string } }
) {
  try {
    const { keyId } = params;
    const body = await request.json();
    
    const response = await fetch(`${BACKEND_URL}/byok/api-keys/${keyId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      if (response.status === 404) {
        return NextResponse.json(
          { success: false, error: 'API key not found' },
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
    console.error('Error updating API key:', error);
    return NextResponse.json(
      { 
        success: false, 
        error: 'Failed to update API key'
      },
      { status: 500 }
    );
  }
}
