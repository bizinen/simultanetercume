import {
  ConsoleTemplate,
  FullScreenContainer,
  ThemeProvider,
} from "@pipecat-ai/voice-ui-kit";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./style.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <FullScreenContainer>
        <ConsoleTemplate
          startBotParams={{
            endpoint: "/start",
            requestData: {
              createDailyRoom: true,
            },
          }}
          transportType="daily"
        />
      </FullScreenContainer>
    </ThemeProvider>
  </StrictMode>
);
