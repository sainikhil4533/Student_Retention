import { SectionTitle } from "../components/ui";
import { ChatbotPage } from "../components/chatbot";

export function RoleChatPage() {
  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="Copilot workspace"
        title="A full conversation surface for longer analysis"
        description="The floating chatbot is great for quick help. This page is the expanded workspace for longer role-aware conversations, session history review, and grounded follow-up questions."
      />
      <ChatbotPage />
    </div>
  );
}
