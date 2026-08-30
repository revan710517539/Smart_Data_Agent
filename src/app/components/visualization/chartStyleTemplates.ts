import { normalizeVisualizationChartStyle, type VisualizationChartStyleConfig } from "./visualizationDataModel";

export type BuiltInChartTemplate = {
  id: string;
  name: string;
  sourceLabel: string;
  style: VisualizationChartStyleConfig;
};

const chart = (id: string, name: string, sourceLabel: string, value: Omit<VisualizationChartStyleConfig, "templateId">): BuiltInChartTemplate => ({
  id,
  name,
  sourceLabel,
  style: normalizeVisualizationChartStyle({ templateId: id, ...value }),
});

export const builtInChartTemplates: BuiltInChartTemplate[] = [
  chart("chart-jade", "玉衡清朗", "SDA · 默认", { backgroundColor: "#FBFDFC", plotBackgroundColor: "#FFFFFF", textColor: "#34443C", mutedTextColor: "#7F8F87", gridColor: "#E7EEE9", axisColor: "#CFDAD3", palette: ["#287557", "#5F8173", "#617988", "#84958B", "#526F65", "#A18B62", "#8C9992", "#A1ABA5"], fontFamily: "system", chartHeight: "standard", lineWidth: 2, pointRadius: 2.5, barRadius: 4, barWidth: "standard", areaOpacity: 0.1 }),
  chart("chart-deep-sea", "深海金融", "Excel · 金融蓝", { backgroundColor: "#F7FAFC", plotBackgroundColor: "#FFFFFF", textColor: "#243B4D", mutedTextColor: "#708390", gridColor: "#DCE7F0", axisColor: "#BDCDDA", palette: ["#2D6694", "#5C8DB5", "#78A7C9", "#A2BED3", "#447B72", "#779B70", "#B89B5A", "#8B7BA6"], fontFamily: "humanist", chartHeight: "expanded", lineWidth: 2.4, pointRadius: 2.8, barRadius: 3, barWidth: "standard", areaOpacity: 0.13 }),
  chart("chart-cloud-blue", "云端协作", "Feishu / Semi · 参考", { backgroundColor: "#F8FAFD", plotBackgroundColor: "#FFFFFF", textColor: "#273142", mutedTextColor: "#737C89", gridColor: "#E6EAF0", axisColor: "#C9D0DA", palette: ["#3370FF", "#38A7A0", "#6F7FD9", "#67A04B", "#C68A3A", "#A86F9F", "#4F93C5", "#8992A0"], fontFamily: "system", chartHeight: "standard", lineWidth: 2.2, pointRadius: 2.6, barRadius: 5, barWidth: "standard", areaOpacity: 0.1 }),
  chart("chart-graphite", "现代石墨", "GitHub Primer · 参考", { backgroundColor: "#F8F9FA", plotBackgroundColor: "#FFFFFF", textColor: "#30383F", mutedTextColor: "#737D85", gridColor: "#E3E7EA", axisColor: "#C6CDD2", palette: ["#3B6C91", "#607D8B", "#728B74", "#8A7D66", "#826E89", "#5B8790", "#9A7469", "#91989D"], fontFamily: "system", chartHeight: "compact", lineWidth: 1.8, pointRadius: 2, barRadius: 2, barWidth: "slim", areaOpacity: 0.08 }),
  chart("chart-celadon", "青瓷水色", "Semi · 青色系", { backgroundColor: "#F7FAF9", plotBackgroundColor: "#FFFFFF", textColor: "#2A403D", mutedTextColor: "#728783", gridColor: "#DEEBE8", axisColor: "#BED1CD", palette: ["#287E78", "#57A59D", "#78B8AF", "#4D7B8A", "#73956D", "#A28B5B", "#8B7592", "#879B96"], fontFamily: "humanist", chartHeight: "standard", lineWidth: 2.2, pointRadius: 2.4, barRadius: 6, barWidth: "wide", areaOpacity: 0.12 }),
  chart("chart-pine", "松柏经营", "Excel · 绿色系", { backgroundColor: "#F8FAF8", plotBackgroundColor: "#FFFFFF", textColor: "#314037", mutedTextColor: "#758079", gridColor: "#E2E9E4", axisColor: "#C6D1C9", palette: ["#426D52", "#6C9276", "#8AA98F", "#587687", "#8B815F", "#A36F5F", "#737C95", "#919A92"], fontFamily: "humanist", chartHeight: "expanded", lineWidth: 2, pointRadius: 2.5, barRadius: 3, barWidth: "standard", areaOpacity: 0.1 }),
  chart("chart-slate-amber", "铅灰暖金", "Excel · 暖色系", { backgroundColor: "#FAF9F6", plotBackgroundColor: "#FFFFFF", textColor: "#403E37", mutedTextColor: "#817D72", gridColor: "#EBE6DA", axisColor: "#D5CDBC", palette: ["#9A7135", "#62717D", "#8A8B6B", "#B08B52", "#6E8792", "#8E736B", "#7D7A8B", "#A0A097"], fontFamily: "humanist", chartHeight: "standard", lineWidth: 2.1, pointRadius: 2.3, barRadius: 4, barWidth: "standard", areaOpacity: 0.11 }),
  chart("chart-terracotta", "陶土冷灰", "AntV · 参考", { backgroundColor: "#FAF8F7", plotBackgroundColor: "#FFFFFF", textColor: "#423A37", mutedTextColor: "#817570", gridColor: "#ECE4E1", axisColor: "#D5C8C3", palette: ["#A45645", "#667A88", "#7F8E72", "#C0785B", "#7F7390", "#51908C", "#9D8C66", "#96908D"], fontFamily: "system", chartHeight: "standard", lineWidth: 2.2, pointRadius: 2.6, barRadius: 5, barWidth: "wide", areaOpacity: 0.12 }),
  chart("chart-night", "夜航蓝", "ECharts dark · 参考", { backgroundColor: "#18232D", plotBackgroundColor: "#18232D", textColor: "#E7EFF4", mutedTextColor: "#9FB0BC", gridColor: "#31414D", axisColor: "#465966", palette: ["#66A7E8", "#56B6A6", "#91A9E8", "#8DBB6D", "#D5A65B", "#C688B2", "#5AB3C3", "#A4B0B8"], fontFamily: "system", chartHeight: "expanded", lineWidth: 2.3, pointRadius: 2.8, barRadius: 4, barWidth: "standard", areaOpacity: 0.16 }),
  chart("chart-monochrome", "纸白黑", "shadcn-admin · 参考", { backgroundColor: "#FAFAFA", plotBackgroundColor: "#FFFFFF", textColor: "#262B2F", mutedTextColor: "#72797E", gridColor: "#E7E9EA", axisColor: "#C9CDCF", palette: ["#30363B", "#5D666D", "#7A8389", "#98A0A5", "#4A5962", "#68757D", "#899196", "#A5AAAD"], fontFamily: "mono", chartHeight: "compact", lineWidth: 1.6, pointRadius: 1.8, barRadius: 1, barWidth: "slim", areaOpacity: 0.07 }),
];

export function chartTemplateById(id: string | null | undefined) {
  return builtInChartTemplates.find((template) => template.id === id) || builtInChartTemplates[0];
}
