import { RouterProvider } from "react-router";
import { router } from "./routes";
import { PlatformProvider } from "./platform/PlatformContext";
import { SkinThemeProvider } from "./theme/SkinThemeContext";

export default function App() {
  return (
    <PlatformProvider>
      <SkinThemeProvider>
        <RouterProvider router={router} />
      </SkinThemeProvider>
    </PlatformProvider>
  );
}
