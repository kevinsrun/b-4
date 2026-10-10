import { Suspense } from "react";
import { SettingsWorkspace } from "@/components/settings/settings-workspace";

export const metadata = {
  title: "Settings & Integrations | BactroGen Research",
  description:
    "Platform configuration, sequencer connection management, AMP predictor operational health, and data storage settings.",
};

export default function SettingsPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-[1240px] px-4 py-16 text-center text-[13px] text-faint">
          Loading platform settings...
        </div>
      }
    >
      <SettingsWorkspace />
    </Suspense>
  );
}
