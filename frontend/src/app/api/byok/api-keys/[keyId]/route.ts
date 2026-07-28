import { NextRequest, NextResponse } from 'next/server';

import { BACKEND_URL, authHeaders, forwardError } from '../../_forward';

export async function DELETE(
  request: NextRequest,
  { params }: { params: { keyId: string } }
) {
  try {
    const { keyId } = params;
    
    const response = await fetch(`${BACKEND_URL}/byok/api-keys/${keyId}`, {
      method: 'DELETE',
      headers: authHeaders(request),
    });

    if (!response.ok) {
      if (response.status === 404) {
        return NextResponse.json(
          { success: false, error: 'API key not found' },
          { status: 404 }
        );
      }
      return forwardError(response, 'Error deleting API key');
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

// Note: there is no PUT handler here — the backend exposes only GET/POST on
// /byok/api-keys and DELETE on /byok/api-keys/{key_id}. Keys are rotated by
// deleting and re-adding them.
