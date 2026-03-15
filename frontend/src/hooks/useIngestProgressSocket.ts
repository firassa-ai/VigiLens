import { useEffect } from "react";

import { buildIngestWsUrl, parseIngestProgress } from "../api/client";
import { useVigilensStore } from "../store/useVigilensStore";

const reconnectDelaysMs = [500, 1000, 2000, 4000, 8000];
const heartbeatMs = 15000;

export function useIngestProgressSocket(drugId: string): void {
  const setIngestProgress = useVigilensStore((state) => state.setIngestProgress);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let closedIntentionally = false;
    let reconnectIndex = 0;
    let reconnectTimer: number | null = null;
    let heartbeatTimer: number | null = null;

    const clearHeartbeat = (): void => {
      if (heartbeatTimer !== null) {
        window.clearInterval(heartbeatTimer);
        heartbeatTimer = null;
      }
    };

    const connect = (): void => {
      socket = new WebSocket(buildIngestWsUrl(drugId));

      socket.onopen = () => {
        reconnectIndex = 0;
        clearHeartbeat();
        heartbeatTimer = window.setInterval(() => {
          if (!socket || socket.readyState !== WebSocket.OPEN) {
            return;
          }
          try {
            socket.send("ping");
          } catch {
            // Reconnect path is handled by onclose.
          }
        }, heartbeatMs);
      };

      socket.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data) as unknown;
          const progress = parseIngestProgress(parsed);
          if (progress) {
            setIngestProgress(progress.message);
          }
        } catch {
          // Ignore malformed websocket payloads to keep the UI responsive.
        }
      };

      socket.onclose = () => {
        clearHeartbeat();
        if (closedIntentionally) {
          return;
        }
        const delay = reconnectDelaysMs[Math.min(reconnectIndex, reconnectDelaysMs.length - 1)];
        reconnectIndex += 1;
        reconnectTimer = window.setTimeout(() => {
          connect();
        }, delay);
      };

      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();

    return () => {
      closedIntentionally = true;
      clearHeartbeat();
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      if (socket) {
        socket.close();
      }
    };
  }, [drugId, setIngestProgress]);
}
