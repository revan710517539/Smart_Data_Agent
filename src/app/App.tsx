import { RouterProvider } from "react-router";
import { router } from "./routes";
import { PlatformProvider } from "./platform/PlatformContext";

export default function App() {
  return (
    <PlatformProvider>
      <RouterProvider router={router} />
    </PlatformProvider>
  );
}
