// The real BETA AID copilot behind the chat simulator: one session per persona, in the selected residency region.
// Real endpoints: POST /api/session, /api/message, /api/confirm, /api/stepup (see copilot/src/copilot/app.py).
import { api, ApiError, type RegionId } from "./api";
import type { ChatResponse, Persona } from "./types";

export class ChatBackend {
  persona: Persona;
  region: RegionId;
  token: string | null = null;

  constructor(region: RegionId, persona: Persona) {
    this.region = region;
    this.persona = persona;
  }

  async session(customer_id: string, otp: string): Promise<{ token: string } | { error: string }> {
    try {
      const r = await api<{ token: string }>(this.region, "/api/session", { body: { customer_id, otp } });
      this.token = r.token;
      return r;
    } catch (e) {
      return { error: e instanceof ApiError ? e.detail : String(e) };
    }
  }

  message(text: string): Promise<ChatResponse> {
    return api<ChatResponse>(this.region, "/api/message", { body: { text }, token: this.token });
  }

  confirm(yes: boolean): Promise<ChatResponse> {
    return api<ChatResponse>(this.region, "/api/confirm", { body: { yes }, token: this.token });
  }

  async stepup(otp: string): Promise<{ token: string; response: ChatResponse } | { error: string }> {
    const r = await api<ChatResponse & { token: string | null }>(this.region, "/api/stepup", {
      body: { otp },
      token: this.token,
    });
    if (r.outcome === "deny" || !r.token) return { error: r.text };
    this.token = r.token;
    return { token: r.token, response: r };
  }
}
