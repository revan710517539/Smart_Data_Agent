import type { ModelIntegration } from "./systemConfigApi";

export type PersistedTextModelSelection = {
  integrationId: string;
  selectedModelName: string;
};

export type TextModelOption = PersistedTextModelSelection & {
  id: string;
  label: string;
  model: ModelIntegration;
};

function storageKey(tenantId: string, userId: string) {
  void tenantId;
  return `smart-data-agent:text-model-selection:account:${userId}`;
}

function legacyStorageKey(tenantId: string, userId: string) {
  return `smart-data-agent:text-model-selection:${tenantId}:${userId}`;
}

function candidateNames(model: ModelIntegration) {
  const names = model.enabledModels?.length
    ? model.enabledModels
    : model.availableModels?.length
      ? model.availableModels
      : model.selectedModelName
        ? [model.selectedModelName]
        : model.modelName
          ? [model.modelName]
          : [];
  return Array.from(new Set(names.map((name) => name.trim()).filter(Boolean)));
}

/**
 * Returns only configured text-model choices. Speech integrations are a
 * separate API type and never enter this list.
 */
export function configuredTextModelOptions(models: ModelIntegration[]): TextModelOption[] {
  return models
    .filter((model) => ["available", "draft"].includes(model.status) && Boolean(model.id))
    .flatMap((model) => candidateNames(model).map((selectedModelName) => ({
      id: `${model.id}::${selectedModelName}`,
      integrationId: model.id,
      selectedModelName,
      label: model.name === selectedModelName ? selectedModelName : `${model.name} · ${selectedModelName}`,
      model,
    })));
}

export function readPersistedTextModelSelection(tenantId: string, userId: string): PersistedTextModelSelection | null {
  try {
    const raw = window.localStorage.getItem(storageKey(tenantId, userId))
      || window.localStorage.getItem(legacyStorageKey(tenantId, userId));
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<PersistedTextModelSelection>;
    if (!value.integrationId || !value.selectedModelName) return null;
    const selection = { integrationId: value.integrationId, selectedModelName: value.selectedModelName };
    window.localStorage.setItem(storageKey(tenantId, userId), JSON.stringify(selection));
    return selection;
  } catch {
    return null;
  }
}

export const textModelSelectionEvent = "smart-data-agent:text-model-selection";

export function persistTextModelSelection(
  tenantId: string,
  userId: string,
  selection: PersistedTextModelSelection,
) {
  try {
    window.localStorage.setItem(storageKey(tenantId, userId), JSON.stringify(selection));
  } catch {
    // Selection persistence is a UI preference: an unavailable browser store
    // must not block a configured model from being used in the current page.
  }
  window.dispatchEvent(new CustomEvent(textModelSelectionEvent, { detail: { tenantId, userId, ...selection } }));
}

export function findConfiguredTextModel(
  models: ModelIntegration[],
  selection: PersistedTextModelSelection | null,
): ModelIntegration | null {
  if (!selection) return null;
  const option = configuredTextModelOptions(models).find(
    (candidate) => candidate.integrationId === selection.integrationId
      && candidate.selectedModelName === selection.selectedModelName,
  );
  if (!option) return null;
  return {
    ...option.model,
    name: option.label,
    selectedModelName: option.selectedModelName,
    enabledModels: [option.selectedModelName],
  };
}
