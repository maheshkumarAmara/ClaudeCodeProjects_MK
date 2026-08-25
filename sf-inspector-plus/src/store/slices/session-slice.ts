import type { StateCreator } from 'zustand';
import type { SessionInfo } from '@/types/messages';

export interface SessionSlice {
  session: SessionInfo | null;
  isConnected: boolean;
  setSession: (session: SessionInfo | null) => void;
}

export const createSessionSlice: StateCreator<SessionSlice> = (set) => ({
  session: null,
  isConnected: false,
  setSession: (session) =>
    set({ session, isConnected: session !== null }),
});
