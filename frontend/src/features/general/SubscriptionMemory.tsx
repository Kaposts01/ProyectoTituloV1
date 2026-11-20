import { useMemo, useState, type ReactNode } from "react";
import { SubscriptionMemory, type SavedSubscriptionContext } from "./subscriptionContext";

/** Memory is limited to this authenticated UI tree: no URL, browser storage or module-level cache of searches. */
export function SubscriptionMemoryProvider({ children }: { children: ReactNode }) {
  const [saved, save] = useState<SavedSubscriptionContext | null>(null);
  const value = useMemo(() => ({ saved, save }), [saved]);
  return <SubscriptionMemory.Provider value={value}>{children}</SubscriptionMemory.Provider>;
}
