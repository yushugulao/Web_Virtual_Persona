import { Navigate, Route, Routes } from "react-router-dom";
import AppController from "./app/AppController";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/app" replace />} />
      <Route path="/login" element={<AppController />} />
      <Route path="/app" element={<AppController />} />
      <Route path="/app/public" element={<AppController />} />
      <Route path="/app/mine" element={<AppController />} />
      <Route path="/app/chat/:personaId" element={<AppController />} />
      <Route path="/app/admin/users" element={<AppController />} />
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  );
}
