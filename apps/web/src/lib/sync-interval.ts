export function normalizeSyncInterval(minutes: number): 180 | 360 | 720 | 1440 {
  if (minutes === 180 || minutes === 360 || minutes === 720 || minutes === 1440) return minutes;
  return 360;
}

