import { createContext, type Dispatch, type SetStateAction } from "react";

export type SubscriptionFilters = { channel: string; status: string; field: string; query: string; offset: number };
export type SavedSubscriptionContext = { search: string; filters: SubscriptionFilters; focusKey?: string };
export const SubscriptionMemory = createContext<{
  saved: SavedSubscriptionContext | null;
  save: Dispatch<SetStateAction<SavedSubscriptionContext | null>>;
} | null>(null);
