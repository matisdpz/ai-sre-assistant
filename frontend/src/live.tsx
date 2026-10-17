import { createContext, useContext, useState, type ReactNode } from "react";

interface Live {
  paused: boolean;
  setPaused: (paused: boolean) => void;
}

const LiveContext = createContext<Live>({ paused: false, setPaused: () => {} });

/** Global auto-refresh switch, like the live/pause toggle of Grafana dashboards. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const [paused, setPaused] = useState(false);
  return <LiveContext.Provider value={{ paused, setPaused }}>{children}</LiveContext.Provider>;
}

export const useLive = () => useContext(LiveContext);
