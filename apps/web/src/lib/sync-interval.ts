export function normalizeSyncInterval(minutes: number): 180 | 360 | 720 | 1440 {
  if (minutes === 180 || minutes === 360 || minutes === 720 || minutes === 1440) return minutes;
  return 360;
}

export function isRollingFixedSchedule(system: {
  sync_engine_version?: string;
  initial_index_completed_at?: string | null;
}): boolean {
  return system.sync_engine_version === "1.1" && Boolean(system.initial_index_completed_at);
}
