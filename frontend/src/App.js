import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import Validator from "@/pages/Validator";

function App() {
  return (
    <div className="App mp-grid-bg min-h-screen">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Validator />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" theme="dark" richColors />
    </div>
  );
}

export default App;
