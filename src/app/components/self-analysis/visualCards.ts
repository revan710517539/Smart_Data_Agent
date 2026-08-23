import { noteItemsFromText } from "../notes/richNote";
import type { VisualizationCardConfig } from "../visualization/visualizationDataModel";
import { visualizationLabel, type ResultVisualKey, type VisualizationType } from "./domain";

export type VisualCardInstance = {
  id: string;
  key?: ResultVisualKey;
  title: string;
  type: VisualizationType;
  config?: VisualizationCardConfig;
};

export function defaultVisualizationCards(types: Record<ResultVisualKey, VisualizationType>): VisualCardInstance[] {
  return [
    { id: "primary", key: "primary", title: `主分析视图 · ${visualizationLabel(types.primary)}`, type: types.primary },
    { id: "secondary", key: "secondary", title: `补充分析视图 · ${visualizationLabel(types.secondary)}`, type: types.secondary },
  ];
}

export function documentSummaryCards(summary: string): VisualCardInstance[] {
  const noteBody = summary.trim();
  const config: VisualizationCardConfig = {
    metricFields: [],
    dimensionFields: [],
    filters: {},
    filterGroups: [],
    sumFilteredRows: false,
    comboLineFields: [],
    noteTitle: "文本总结",
    noteBody,
    noteItems: noteItemsFromText(noteBody, "visual_note"),
  };
  return [{ id: "primary", key: "primary", title: "文本总结", type: "text", config }];
}
