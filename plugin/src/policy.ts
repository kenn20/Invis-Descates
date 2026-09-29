export interface LocalPolicy { paused: boolean; cooldownUntil: number; dailyNudges: number; }
export const canEvaluate = (policy: LocalPolicy, now: number): boolean => !policy.paused && policy.dailyNudges < 3 && now >= policy.cooldownUntil;
export const recordNudge = (policy: LocalPolicy, now: number): LocalPolicy => ({ ...policy, dailyNudges: policy.dailyNudges + 1, cooldownUntil: now + 20 * 60_000 });
