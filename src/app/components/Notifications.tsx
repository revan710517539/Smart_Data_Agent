import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router";
import {
  AlertTriangle,
  Bell,
  BellRing,
  CheckCircle2,
  Clock,
  Edit3,
  Mail,
  MessageSquare,
  Plus,
  Smartphone,
  ToggleLeft,
  ToggleRight,
} from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { fetchMarketBundle, type MarketBundle, type MarketRule } from "../services/marketApi";
import {
  fetchNotificationBundle,
  updateNotificationSubscription,
  type NotificationBundle,
  type NotificationDelivery,
  type NotificationSubscription,
} from "../services/notificationApi";
import { apiErrorMessage } from "../services/apiClient";

type NotificationSection = "alerts" | "subscriptions" | "history";

function getNotificationSection(pathname: string): NotificationSection {
  if (pathname.endsWith("/subscriptions")) return "subscriptions";
  if (pathname.endsWith("/history")) return "history";
  return "alerts";
}

const EMPTY_NOTIFICATIONS: NotificationBundle = {
  tenant_id: "",
  subscriptions: [],
  in_app_deliveries: [],
  count: { subscriptions: 0, in_app_deliveries: 0 },
};

const EMPTY_MARKET: MarketBundle = {
  tenant_id: "",
  sources: [],
  entities: [],
  observations: [],
  rules: [],
  events: [],
};

export function Notifications() {
  const location = useLocation();
  const { tenantId, userId } = usePlatformContext();
  const activeTab = getNotificationSection(location.pathname);
  const [notifications, setNotifications] = useState(EMPTY_NOTIFICATIONS);
  const [market, setMarket] = useState(EMPTY_MARKET);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNotice("");
    Promise.all([fetchNotificationBundle({ tenantId, userId }), fetchMarketBundle({ tenantId, userId })])
      .then(([notificationBundle, marketBundle]) => {
        if (cancelled) return;
        setNotifications(notificationBundle);
        setMarket(marketBundle);
      })
      .catch((error) => {
        if (cancelled) return;
        setNotifications(EMPTY_NOTIFICATIONS);
        setMarket(EMPTY_MARKET);
        setNotice(apiErrorMessage(error, "推送与订阅数据加载失败。"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId]);

  const stats = useMemo(() => {
    const activeRules = market.rules.filter((rule) => rule.status === "active").length;
    const today = new Date().toDateString();
    const deliveredToday = notifications.in_app_deliveries.filter(
      (delivery) => delivery.status === "delivered" && new Date(delivery.delivered_at || delivery.created_at).toDateString() === today,
    ).length;
    return [
      { label: "活跃预警规则", value: String(activeRules), icon: BellRing },
      { label: "今日已送达", value: String(deliveredToday), icon: Bell },
      { label: "我的订阅", value: String(notifications.subscriptions.length), icon: Mail },
      { label: "投递记录", value: String(notifications.in_app_deliveries.length), icon: MessageSquare },
    ];
  }, [market.rules, notifications]);

  const unsupported = (message: string) => setNotice(message);
  const manageSubscription = async (subscription: NotificationSubscription) => {
    const nextStatus = subscription.status === "active" ? "paused" : "active";
    setNotice(nextStatus === "paused" ? "正在暂停订阅…" : "正在启用订阅…");
    try {
      const response = await updateNotificationSubscription({
        tenantId,
        userId,
        subscriptionId: subscription.subscription_id,
        expectedLockVersion: subscription.lock_version,
        changes: { status: nextStatus },
      });
      setNotifications((current) => ({
        ...current,
        subscriptions: current.subscriptions.map((item) =>
          item.subscription_id === response.subscription.subscription_id ? response.subscription : item,
        ),
      }));
      setNotice(nextStatus === "paused" ? "订阅已暂停，后续事件不会再生成投递。" : "订阅已启用，后续事件将按原渠道投递。");
    } catch (error) {
      setNotice(apiErrorMessage(error, "订阅状态更新失败。"));
    }
  };

  return (
    <div className="p-7">
      <div className="flex items-center justify-between mb-7">
        <div>
          <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">推送与订阅</h2>
          <p className="text-[13px] text-[#aeaeb2] mt-1">智能预警规则 · 定期报告订阅 · 推送记录追踪</p>
        </div>
        <button
          onClick={() => unsupported("当前页面只展示已审核的监控规则；请在市场监控或自动化任务中创建规则后再配置订阅。")}
          className="flex items-center gap-1.5 px-4 py-2 bg-[#1d1d1f] text-white rounded-lg text-[13px] hover:bg-[#2c2c2e] transition-colors"
        >
          <Plus className="w-4 h-4" />
          新建规则
        </button>
      </div>

      {notice && <div className="mb-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-3 text-[12px] text-[#636366]">{notice}</div>}

      <div className="grid grid-cols-4 gap-4 mb-6">
        {stats.map((item) => (
          <div key={item.label} className="bg-white p-4 rounded-xl border border-[#f0f0f2]">
            <item.icon className="w-4 h-4 text-[#636366] mb-2" />
            <div className="text-[22px] text-gray-900 tracking-tight">{loading ? "—" : item.value}</div>
            <div className="text-[12px] text-gray-400 mt-0.5">{item.label}</div>
          </div>
        ))}
      </div>

      {activeTab === "alerts" && (
        <div className="space-y-2">
          {market.rules.map((rule) => (
            <AlertRuleCard
              key={rule.market_rule_id}
              rule={rule}
              subscriptions={notifications.subscriptions}
              triggerCount={market.events.filter((event) => event.market_rule_id === rule.market_rule_id).length}
              lastTrigger={market.events.find((event) => event.market_rule_id === rule.market_rule_id)?.detected_at}
              onUnsupported={unsupported}
            />
          ))}
          {!loading && market.rules.length === 0 && <EmptyState text="暂无已配置且有权限查看的真实预警规则。" />}
        </div>
      )}

      {activeTab === "subscriptions" && (
        <div className="space-y-2">
          {notifications.subscriptions.map((subscription) => (
            <SubscriptionCard key={subscription.subscription_id} subscription={subscription} onManage={manageSubscription} />
          ))}
          {!loading && notifications.subscriptions.length === 0 && <EmptyState text="暂无订阅。创建订阅后，事件才会进入相应投递渠道。" />}
        </div>
      )}

      {activeTab === "history" && (
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-gray-400 text-[11px]">
                <th className="text-left py-2.5 px-3">时间</th>
                <th className="text-left py-2.5 px-3">标题</th>
                <th className="text-center py-2.5 px-3">类型</th>
                <th className="text-left py-2.5 px-3">渠道</th>
                <th className="text-center py-2.5 px-3">真实状态</th>
                <th className="text-center py-2.5 px-3">回执</th>
              </tr>
            </thead>
            <tbody>
              {notifications.in_app_deliveries.map((delivery) => <DeliveryRow key={delivery.delivery_id} delivery={delivery} />)}
            </tbody>
          </table>
          {!loading && notifications.in_app_deliveries.length === 0 && <div className="py-10 text-center text-[12px] text-[#aeaeb2]">暂无真实投递记录。</div>}
        </div>
      )}
    </div>
  );
}

function AlertRuleCard({
  rule,
  subscriptions,
  triggerCount,
  lastTrigger,
  onUnsupported,
}: {
  rule: MarketRule;
  subscriptions: NotificationSubscription[];
  triggerCount: number;
  lastTrigger?: string;
  onUnsupported: (message: string) => void;
}) {
  const enabled = rule.status === "active";
  const channels = subscriptions
    .filter((subscription) => subscription.status === "active" && subscription.event_types.includes("market.monitoring.triggered"))
    .map((subscription) => subscription.channel_type);
  return (
    <div className="bg-white rounded-xl border border-[#f0f0f2] p-5 hover:border-[#d1d1d6] transition-colors">
      <div className="flex items-start gap-4">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 bg-[#f2f2f7]">
          <AlertTriangle className={`w-4 h-4 ${enabled ? "text-[#636366]" : "text-[#c7c7cc]"}`} />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[14px] text-gray-900">{rule.rule_name}</span>
            <span className="text-[10px] px-2 py-0.5 rounded bg-[#f2f2f7] text-[#636366]">{enabled ? "已启用" : rule.status}</span>
          </div>
          <div className="flex items-center gap-4 text-[11px] text-gray-400 mb-2">
            <span>指标：{rule.metric_code}</span>
            <span>条件：{formatCondition(rule.condition_expression)}</span>
            <span>级别：{rule.severity}</span>
          </div>
          <div className="flex items-center gap-3">
            {channels.map((channel) => <ChannelBadge key={channel} channel={channel} />)}
            {channels.length === 0 && <span className="text-[10px] text-[#aeaeb2]">尚未绑定订阅渠道</span>}
            <span className="text-[10px] text-gray-400 ml-auto">触发 {triggerCount} 次 · 最近 {formatTime(lastTrigger)}</span>
          </div>
        </div>
        <div className="flex gap-1.5">
          <button onClick={() => onUnsupported("规则编辑需要回到市场监控的证据与口径审核流程。")} className="p-2 bg-[#f5f5f7] rounded-lg hover:bg-[#f0f0f2]">
            <Edit3 className="w-3.5 h-3.5 text-gray-400" />
          </button>
          <button onClick={() => onUnsupported("规则状态不能在展示页直接切换，请通过有审计记录的规则管理接口处理。") } className="p-2 bg-[#f5f5f7] rounded-lg hover:bg-[#f0f0f2]">
            {enabled ? <ToggleRight className="w-3.5 h-3.5 text-[#34c759]" /> : <ToggleLeft className="w-3.5 h-3.5 text-gray-400" />}
          </button>
        </div>
      </div>
    </div>
  );
}

function SubscriptionCard({ subscription, onManage }: { subscription: NotificationSubscription; onManage: (subscription: NotificationSubscription) => void }) {
  return (
    <div className="bg-white rounded-xl border border-[#f0f0f2] p-5 hover:border-[#d1d1d6] transition-colors">
      <div className="flex items-center gap-4">
        <div className="w-9 h-9 rounded-lg bg-[#f2f2f7] flex items-center justify-center shrink-0"><Mail className="w-4 h-4 text-[#636366]" /></div>
        <div className="flex-1">
          <div className="text-[14px] text-gray-900 mb-1">{subscription.subscription_name}</div>
          <div className="flex items-center gap-4 text-[11px] text-gray-400">
            <span className="flex items-center gap-1"><Clock className="w-3 h-3" />事件触发</span>
            <span>{subscription.event_types.join("、")}</span>
            <span>渠道：{channelLabel(subscription.channel_type)}</span>
            <span>状态：{subscription.status}</span>
          </div>
        </div>
        <button onClick={() => onManage(subscription)} className="px-3 py-1.5 border border-[#e5e5ea] rounded-lg text-[11px] text-[#636366] hover:bg-[#f2f2f7]">{subscription.status === "active" ? "暂停" : "启用"}</button>
      </div>
    </div>
  );
}

function DeliveryRow({ delivery }: { delivery: NotificationDelivery }) {
  const delivered = delivery.status === "delivered";
  const title = String(delivery.payload.summary || delivery.payload.task_name || delivery.event_type);
  return (
    <tr className="border-t border-gray-50 text-gray-700 hover:bg-[#f5f5f7]">
      <td className="py-3 px-3 text-gray-400">{formatTime(delivery.delivered_at || delivery.created_at)}</td>
      <td className="py-3 px-3 text-gray-800">{title}</td>
      <td className="py-3 px-3 text-center"><span className="text-[10px] px-2 py-0.5 rounded-full bg-[#007aff]/8 text-[#007aff]">{delivery.event_type}</span></td>
      <td className="py-3 px-3">{channelLabel(delivery.channel_type)}</td>
      <td className="py-3 px-3 text-center">
        <span className={`text-[10px] px-2 py-0.5 rounded flex items-center gap-0.5 w-fit mx-auto ${delivered ? "text-[#34a853] bg-[#34a853]/6" : "text-[#8a8a8e] bg-[#f2f2f7]"}`}>
          {delivered && <CheckCircle2 className="w-3 h-3" />}{deliveryStatusLabel(delivery.status)}
        </span>
      </td>
      <td className="py-3 px-3 text-center text-gray-600">{delivery.provider_message_id || delivery.error_code || "—"}</td>
    </tr>
  );
}

function ChannelBadge({ channel }: { channel: string }) {
  const Icon = channel === "email" ? Mail : channel === "webhook" ? Smartphone : MessageSquare;
  return <span className="text-[10px] text-gray-500 bg-[#f5f5f7] px-2 py-0.5 rounded-full flex items-center gap-1"><Icon className="w-3 h-3" />{channelLabel(channel)}</span>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-xl border border-[#f0f0f2] bg-white px-5 py-10 text-center text-[12px] text-[#aeaeb2]">{text}</div>;
}

function formatCondition(condition: { operator?: string; threshold?: number }) {
  const labels: Record<string, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤", eq: "=", change_pct_gt: "变化率 >", change_pct_lt: "变化率 <" };
  return `${labels[String(condition.operator)] || condition.operator || "—"} ${condition.threshold ?? "—"}`;
}

function channelLabel(channel: string) {
  return ({ in_app: "站内信", email: "邮件", webhook: "Webhook" } as Record<string, string>)[channel] || channel;
}

function deliveryStatusLabel(status: string) {
  return ({ queued: "排队中", sending: "发送中", delivered: "已送达", failed: "失败待重试", suppressed: "已抑制", dead_letter: "死信" } as Record<string, string>)[status] || status;
}

function formatTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}
