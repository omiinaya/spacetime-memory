import { Badge } from '@/components/ui/badge';

const TIER_CONFIG: Record<string, { color: string; label: string }> = {
  CERTAIN: { color: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30', label: 'Certain' },
  HIGH: { color: 'bg-blue-500/10 text-blue-600 border-blue-500/30', label: 'High' },
  MEDIUM: { color: 'bg-yellow-500/10 text-yellow-600 border-yellow-500/30', label: 'Medium' },
  LOW: { color: 'bg-orange-500/10 text-orange-600 border-orange-500/30', label: 'Low' },
  SPECULATIVE: { color: 'bg-gray-500/10 text-gray-500 border-gray-500/30', label: 'Speculative' },
};

interface VeracityBadgeProps {
  tier: string | undefined | null;
}

/** Color-coded badge for the 5 Bayesian veracity tiers. */
export function VeracityBadge({ tier }: VeracityBadgeProps) {
  if (!tier) return null;
  const cfg = TIER_CONFIG[tier] || { color: 'bg-gray-500/10 text-gray-500 border-gray-500/30', label: tier };
  return (
    <Badge variant="outline" className={`text-[10px] shrink-0 ${cfg.color}`} data-testid="veracity-badge">
      {cfg.label}
    </Badge>
  );
}

/** Allowed veracity tier values. */
export const VERACITY_TIERS = ['CERTAIN', 'HIGH', 'MEDIUM', 'LOW', 'SPECULATIVE'] as const;
export type VeracityTierLabel = (typeof VERACITY_TIERS)[number];
