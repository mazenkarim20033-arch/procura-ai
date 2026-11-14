import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { EmptyState } from "./components/ui";
import { Analytics } from "./pages/Analytics";
import { Audit } from "./pages/Audit";
import { Documents } from "./pages/Documents";
import { Overview } from "./pages/Overview";
import { Policies } from "./pages/Policies";
import { RequestDetail } from "./pages/RequestDetail";
import { Requests } from "./pages/Requests";
import { SettingsPage } from "./pages/Settings";
import { Vendors } from "./pages/Vendors";

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="requests" element={<Requests />} />
        <Route path="requests/:id" element={<RequestDetail />} />
        <Route path="documents" element={<Documents />} />
        <Route path="vendors" element={<Vendors />} />
        <Route path="policies" element={<Policies />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="audit" element={<Audit />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<EmptyState title="Page not found" body="Use the menu to get back to a page that exists." />} />
      </Route>
    </Routes>
  );
}
