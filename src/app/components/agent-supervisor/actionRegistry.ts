export type AgentActionRisk = "low" | "medium" | "high";

export type AgentActionDefinition = {
  id: string;
  label: string;
  description: string;
  risk?: AgentActionRisk;
  execute: () => void | Promise<void>;
};

class AgentActionRegistry {
  private actions = new Map<string, AgentActionDefinition>();
  private listeners = new Set<() => void>();

  register(action: AgentActionDefinition) {
    this.actions.set(action.id, action);
    this.emit();
    return () => {
      if (this.actions.get(action.id) === action) {
        this.actions.delete(action.id);
        this.emit();
      }
    };
  }

  list() {
    return Array.from(this.actions.values()).sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
  }

  get(id: string) {
    return this.actions.get(id);
  }

  subscribe(listener: () => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private emit() {
    this.listeners.forEach((listener) => listener());
  }
}

export const agentActionRegistry = new AgentActionRegistry();
