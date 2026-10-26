import AppCore from "./AppCore";
import { EnvironmentBanner } from "./components/EnvironmentBanner";

export default function App() {
  return (
    <>
      <EnvironmentBanner />
      <AppCore />
    </>
  );
}
