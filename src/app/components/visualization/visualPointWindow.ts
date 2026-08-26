import type { VisualizationType } from "../self-analysis/domain";

export function selectVisibleVisualPoints<T>(points: T[], _type: VisualizationType, _compact?: boolean) {
  return points.slice(-40);
}
