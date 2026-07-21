import { Construction } from "lucide-react";

export function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <Construction className="w-12 h-12 text-gray-300 mx-auto mb-3" />
        <h2 className="text-[16px] text-gray-500">{title}</h2>
        <p className="text-[12px] text-gray-400 mt-1">功能开发中，敬请期待</p>
      </div>
    </div>
  );
}
