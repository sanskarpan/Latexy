// Device fingerprinting and trial tracking for freemium model

interface DeviceFingerprint {
  fingerprint: string;
  sessionId: string;
  userAgent: string;
  screen: string;
  timezone: string;
  language: string;
}

interface TrialStatus {
  usageCount: number;
  remainingUses: number;
  isBlocked: boolean;
  lastUsed: Date | null;
}

const TRIAL_LIMIT = 3;
const STORAGE_KEY = 'latexy_trial_data';

/**
 * Generate a device fingerprint based on browser characteristics
 */
export function generateDeviceFingerprint(): DeviceFingerprint {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const navigatorWithMemory = navigator as Navigator & { readonly deviceMemory?: number };
  if (ctx) {
    ctx.textBaseline = 'top';
    ctx.font = '14px Arial';
    ctx.fillText('Device fingerprint', 2, 2);
  }

  const fingerprint = btoa(
    [
      navigator.userAgent,
      navigator.language,
      screen.width + 'x' + screen.height,
      screen.colorDepth,
      new Date().getTimezoneOffset(),
      canvas.toDataURL(),
      navigator.hardwareConcurrency || 0,
      navigatorWithMemory.deviceMemory ?? 0,
    ].join('|')
  ).slice(0, 32);

  return {
    fingerprint,
    sessionId: generateSessionId(),
    userAgent: navigator.userAgent,
    screen: `${screen.width}x${screen.height}`,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    language: navigator.language,
  };
}

/**
 * Generate a session ID
 */
function generateSessionId(): string {
  return Math.random().toString(36).substring(2, 15) +
         Math.random().toString(36).substring(2, 15);
}

/**
 * Get current trial status from localStorage
 */
export function getTrialStatus(): TrialStatus {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const data = JSON.parse(stored);
      return {
        usageCount: data.usageCount || 0,
        remainingUses: Math.max(0, TRIAL_LIMIT - (data.usageCount || 0)),
        isBlocked: data.isBlocked || false,
        lastUsed: data.lastUsed ? new Date(data.lastUsed) : null,
      };
    }
  } catch (error) {
    console.warn('Failed to parse trial data from localStorage:', error);
  }

  return {
    usageCount: 0,
    remainingUses: TRIAL_LIMIT,
    isBlocked: false,
    lastUsed: null,
  };
}

/**
 * Update trial usage count
 */
export function updateTrialUsage(): TrialStatus {
  const current = getTrialStatus();
  const newUsageCount = current.usageCount + 1;
  const newStatus: TrialStatus = {
    usageCount: newUsageCount,
    remainingUses: Math.max(0, TRIAL_LIMIT - newUsageCount),
    isBlocked: newUsageCount >= TRIAL_LIMIT,
    lastUsed: new Date(),
  };

  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      usageCount: newStatus.usageCount,
      isBlocked: newStatus.isBlocked,
      lastUsed: newStatus.lastUsed?.toISOString(),
    }));
  } catch (error) {
    console.warn('Failed to save trial data to localStorage:', error);
  }

  return newStatus;
}

/**
 * Check if user can use trial
 */
export function canUseTrial(): boolean {
  const status = getTrialStatus();
  return !status.isBlocked && status.remainingUses > 0;
}

/**
 * Track usage with backend
 */
export async function trackUsage(action: string, resourceType?: string): Promise<void> {
  const deviceInfo = generateDeviceFingerprint();

  try {
    await fetch('/api/public/track-usage', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        deviceFingerprint: deviceInfo.fingerprint,
        sessionId: deviceInfo.sessionId,
        action,
        resourceType,
        userAgent: deviceInfo.userAgent,
        metadata: {
          screen: deviceInfo.screen,
          timezone: deviceInfo.timezone,
          language: deviceInfo.language,
        },
      }),
    });
  } catch (error) {
    console.warn('Failed to track usage:', error);
  }
}

/**
 * Get trial status from backend
 */
export async function getBackendTrialStatus(): Promise<TrialStatus | null> {
  const deviceInfo = generateDeviceFingerprint();

  try {
    const response = await fetch(`/api/public/trial-status?fingerprint=${encodeURIComponent(deviceInfo.fingerprint)}`);
    if (response.ok) {
      const data = await response.json();
      return {
        usageCount: data.usageCount || 0,
        remainingUses: Math.max(0, TRIAL_LIMIT - (data.usageCount || 0)),
        isBlocked: data.blocked || false,
        lastUsed: data.lastUsed ? new Date(data.lastUsed) : null,
      };
    }
  } catch (error) {
    console.warn('Failed to get backend trial status:', error);
  }

  return null;
}
